"""SD2: 窓内区間対比較の区間計算 (docs/design/service_days.md §2.2)。

「代表世代を選ぶ」のではなく「日付区間ごとに正しい相手と比較する」ための
純粋な日付演算。すべて決定的:

1. 各スナップショットの有効窓 (feed_info → 世代メタ → calendar 全期間の順)
2. 共通窓 = 両者の交差
3. 共通窓を、窓内にある calendar 期間の端点 (start_date / end_date+1) で
   区切った日付区間の列 (calendar_dates の断続は境界にしない — 断片化防止、
   T3 は据え置き)
4. 各区間で実効運行日を1日以上持つ service の集合 (= その区間の便世界)
5. 区間を (旧側 active 集合, 新側 active 集合) で束ねた比較ユニット。
   パイプラインはユニットの中から主比較 (primary) を選び、便世界を絞る:
   - ある unit が他の全 unit を両側とも包含する (上位集合) 場合はそれを採用
     — 通常フィードで service の期間端が揃っていないだけのケースは
     全便比較 = 現行挙動に退化する (誤縮小の防止)
   - そうでない場合 (真の世代同梱) は「内容が変化している unit のうち
     日数最大 (同数なら開始日が遅い方)」を採用し、他は claim イベントで説明
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from ..load.day_types import _exception_dates, _parse_date
from ..model.snapshot import GtfsSnapshot

_CALENDAR_DAY_COLUMNS = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]

_ONE_DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class DateInterval:
    """閉区間 [start, end] (datetime.date)。"""

    start: datetime.date
    end: datetime.date

    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_text(self) -> tuple[str, str]:
        return self.start.strftime("%Y%m%d"), self.end.strftime("%Y%m%d")


def snapshot_window(snapshot: GtfsSnapshot) -> DateInterval | None:
    """スナップショットの有効窓。feed_info → 世代メタ → calendar 全期間の順。

    (calendars.py の _service_period と同じ優先順の思想。feed_info を最優先に
    するのは SD1 の _feed_window と揃えるため)
    """
    fi = snapshot.table("feed_info")
    if fi is not None and not fi.empty and (
        {"feed_start_date", "feed_end_date"} <= set(fi.columns)
    ):
        start = _parse_date(str(fi.iloc[0]["feed_start_date"]))
        end = _parse_date(str(fi.iloc[0]["feed_end_date"]))
        if start is not None and end is not None and start <= end:
            return DateInterval(start, end)
    meta_from = _parse_date((snapshot.meta.from_date or "").replace("-", ""))
    meta_to = _parse_date((snapshot.meta.to_date or "").replace("-", ""))
    if meta_from is not None and meta_to is not None and meta_from <= meta_to:
        return DateInterval(meta_from, meta_to)
    dates: list[datetime.date] = []
    cal = snapshot.table("calendar")
    if cal is not None and not cal.empty and (
        {"start_date", "end_date"} <= set(cal.columns)
    ):
        for col in ("start_date", "end_date"):
            for text in cal[col]:
                d = _parse_date(str(text))
                if d is not None:
                    dates.append(d)
    cd = snapshot.table("calendar_dates")
    if cd is not None and not cd.empty and "date" in cd.columns:
        for text in cd["date"]:
            d = _parse_date(str(text))
            if d is not None:
                dates.append(d)
    if not dates:
        return None
    return DateInterval(min(dates), max(dates))


def common_window(old: GtfsSnapshot, new: GtfsSnapshot) -> DateInterval | None:
    """両世代の有効窓の交差。交差しない・求まらない場合は None。"""
    w_old = snapshot_window(old)
    w_new = snapshot_window(new)
    if w_old is None or w_new is None:
        return None
    start = max(w_old.start, w_new.start)
    end = min(w_old.end, w_new.end)
    if start > end:
        return None
    return DateInterval(start, end)


def _calendar_boundaries(snapshot: GtfsSnapshot, window: DateInterval) -> set[datetime.date]:
    """窓内に落ちる calendar 期間の端点を「区間開始日」の形で返す。

    start_date はそのまま、end_date は翌日 (end の次の日から別の区間) として
    数える。窓の外の端点は無視。
    """
    boundaries: set[datetime.date] = set()
    cal = snapshot.table("calendar")
    if cal is None or cal.empty or not (
        {"start_date", "end_date"} <= set(cal.columns)
    ):
        return boundaries
    for _, row in cal.iterrows():
        start = _parse_date(str(row["start_date"]))
        end = _parse_date(str(row["end_date"]))
        if start is not None and window.start < start <= window.end:
            boundaries.add(start)
        if end is not None and window.start <= end < window.end:
            boundaries.add(end + _ONE_DAY)
    return boundaries


def window_intervals(
    old: GtfsSnapshot, new: GtfsSnapshot
) -> tuple[DateInterval | None, list[DateInterval]]:
    """(共通窓, 共通窓を端点で区切った区間列)。窓が求まらなければ (None, [])。"""
    window = common_window(old, new)
    if window is None:
        return None, []
    starts = {window.start}
    starts |= _calendar_boundaries(old, window)
    starts |= _calendar_boundaries(new, window)
    ordered = sorted(starts)
    intervals: list[DateInterval] = []
    for i, s in enumerate(ordered):
        e = (ordered[i + 1] - _ONE_DAY) if i + 1 < len(ordered) else window.end
        intervals.append(DateInterval(s, e))
    return window, intervals


def active_services(snapshot: GtfsSnapshot, interval: DateInterval) -> set[str]:
    """区間内に実効運行日を1日以上持つ service の集合 (= 区間の便世界の担い手)。

    実効運行日 = 期間×曜日フラグ − calendar_dates 削除 + 追加 (SD1 と同じ定義。
    ここではクリップ先が interval)。
    """
    cal = snapshot.table("calendar")
    cd = snapshot.table("calendar_dates")
    added_map, removed_map = _exception_dates(cd)
    result: set[str] = set()

    flag_rows: dict[str, tuple[tuple[bool, ...], datetime.date, datetime.date]] = {}
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            sid = str(row.get("service_id", ""))
            flags = tuple(str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS)
            start = _parse_date(str(row["start_date"]))
            end = _parse_date(str(row["end_date"]))
            if start is None or end is None:
                # 期間が読めない service は保守的に「全区間で活動」とみなす
                if any(flags):
                    result.add(sid)
                continue
            flag_rows[sid] = (flags, start, end)

    for sid, (flags, start, end) in flag_rows.items():
        lo = max(start, interval.start)
        hi = min(end, interval.end)
        removed = removed_map.get(sid, set())
        d = lo
        while d <= hi:
            if flags[d.weekday()] and d.strftime("%Y%m%d") not in removed:
                result.add(sid)
                break
            d += _ONE_DAY

    # calendar_dates の追加運行日 (calendar に無い service を含む)
    for sid, dates in added_map.items():
        if sid in result:
            continue
        removed = removed_map.get(sid, set())
        for text in dates:
            if text in removed:
                continue
            d = _parse_date(text)
            if d is not None and interval.start <= d <= interval.end:
                result.add(sid)
                break
    return result


def known_services(snapshot: GtfsSnapshot) -> set[str]:
    """calendar / calendar_dates に現れる service_id の全集合。

    どちらにも現れない service (trips.txt からの参照だけがあるデータ不備) は
    比較スコープの判定対象にしない (保守的に全便世界へ残す)。
    """
    result: set[str] = set()
    cal = snapshot.table("calendar")
    if cal is not None and not cal.empty and "service_id" in cal.columns:
        result |= {str(s) for s in cal["service_id"]}
    cd = snapshot.table("calendar_dates")
    if cd is not None and not cd.empty and "service_id" in cd.columns:
        result |= {str(s) for s in cd["service_id"]}
    return result


@dataclass(frozen=True)
class ComparisonUnit:
    """(旧側 active service 集合, 新側 active service 集合) が等しい区間の束。"""

    old_services: frozenset[str]
    new_services: frozenset[str]
    intervals: tuple[DateInterval, ...]

    def days(self) -> int:
        return sum(iv.days() for iv in self.intervals)

    def start(self) -> datetime.date:
        return min(iv.start for iv in self.intervals)


def comparison_units(
    old: GtfsSnapshot, new: GtfsSnapshot
) -> tuple[DateInterval | None, list[DateInterval], list[ComparisonUnit]]:
    """(共通窓, 区間列, 比較ユニット列)。窓が求まらなければ (None, [], [])。"""
    window, intervals = window_intervals(old, new)
    if window is None:
        return None, [], []
    grouped: dict[tuple[frozenset[str], frozenset[str]], list[DateInterval]] = {}
    for iv in intervals:
        key = (
            frozenset(active_services(old, iv)),
            frozenset(active_services(new, iv)),
        )
        grouped.setdefault(key, []).append(iv)
    units = [
        ComparisonUnit(old_services=k[0], new_services=k[1], intervals=tuple(ivs))
        for k, ivs in grouped.items()
    ]
    units.sort(key=lambda u: u.start())
    return window, intervals, units


def superset_unit(units: list[ComparisonUnit]) -> ComparisonUnit | None:
    """他の全ユニットを両側とも包含するユニット (あれば)。

    通常フィードで service の期間端が揃っていないだけの場合はこれが存在し、
    全便比較 = 現行挙動への退化が保証される。"""
    for u in units:
        if all(
            u.old_services >= v.old_services and u.new_services >= v.new_services
            for v in units
        ):
            return u
    return None


@dataclass(frozen=True)
class WindowScope:
    """パイプラインが解決した比較スコープ (rules/generations.py の入力)。

    universe が None の側は「全便を比較」(退化)。excluded_* は比較対象外に
    した service / trip (窓外世代・非 primary 世代)。"""

    window: DateInterval
    intervals: tuple[DateInterval, ...]
    primary_intervals: tuple[DateInterval, ...]
    identical_intervals: tuple[DateInterval, ...]
    old_universe: frozenset[str] | None
    new_universe: frozenset[str] | None
    old_excluded_services: frozenset[str]
    new_excluded_services: frozenset[str]
    old_excluded_trips: frozenset[str]
    new_excluded_trips: frozenset[str]
    multi_generation: bool

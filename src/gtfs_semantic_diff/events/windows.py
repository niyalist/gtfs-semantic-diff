"""SD2: 窓内区間対比較の区間計算 (docs/design/service_days.md §2.2)。

「代表世代を選ぶ」のではなく「日付区間ごとに正しい相手と比較する」ための
純粋な日付演算。すべて決定的:

1. 各スナップショットの有効窓 (feed_info → 世代メタ → calendar 全期間の順)
2. 共通窓 = 両者の交差
3. 共通窓を、窓内にある calendar 期間の端点 (start_date / end_date+1) で
   区切った日付区間の列 (calendar_dates の断続は境界にしない — 断片化防止、
   T3 は据え置き)
4. 各区間で実効運行日を1日以上持つ service の集合 (= その区間の便世界)

パイプライン統合 (区間ごとの比較・claim イベント) は SD2 第2段。
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

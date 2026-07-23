"""calendar / calendar_dates → day_type 正規化。

service_id ごとに運行曜日の型を分類し、世代間で service_id が異なっても
「平日ダイヤ同士」を比較できるようにする (L1 同定・C群ルールの前提)。

区分 (M10 で精密化、docs/design/day_types.md):
- weekday        月–金のみ
- saturday       土のみ
- sunday_holiday 日のみ (日本のフィードでは日祝一体運用が多い)
- weekend        土日のみ
- daily          毎日
- dow_XXXXXXX    上記以外の曜日指定 (月→日の7ビット。例: dow_1010000 = 月・水曜)。
                 コミュバスの通学日・診療日運行等 — 完全に規則的な週次運行であり
                 「特定日」ではない (43フィード実測で旧 irregular の便数の83%)
- irregular      特定日運行 (calendar_dates のみで日数が少ない、または
                 曜日多数決に届かない)。年末年始ダイヤ・連休臨時等。
                 SD1 (2026-07-23) から、曜日フラグを持つ service でも
                 実効運行日 (期間×フラグ − 削除 + 追加、フィード有効期間で
                 クリップ) が short_service_max_days 以下ならここに落ちる —
                 米国流の祝日専用 service (土曜フラグ+通常土曜を全削除で
                 「祝日1日だけ」を表す) が通常ダイヤに合算されるのを防ぐ
                 (docs/design/service_days.md T1、intl_feeds.md IN-8)
- inactive       運行日なし (全フラグ0・追加運行日なし = 休止中の定義枠)

制約 (M0 時点): 日本の国民の祝日カレンダーは参照しない。祝日が平日に
かかる場合の calendar_dates 例外は irregular 側に倒れることがある。
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)

DAY_TYPE_WEEKDAY = "weekday"
DAY_TYPE_SATURDAY = "saturday"
DAY_TYPE_SUNDAY_HOLIDAY = "sunday_holiday"
DAY_TYPE_WEEKEND = "weekend"
DAY_TYPE_DAILY = "daily"
DAY_TYPE_IRREGULAR = "irregular"
DAY_TYPE_INACTIVE = "inactive"
DOW_PREFIX = "dow_"  # + 月→日の7ビット (例 dow_1010000 = 月・水曜)


def day_set_of(day_type: str) -> frozenset[int] | None:
    """day_type → 運行曜日集合 (月=0…日=6)。集合で表せない型は None。

    dow_* は値そのものから決まるため、消費者 (表示・包含判定) は
    追加のメタデータなしで曜日集合を復元できる。
    """
    fixed = {
        DAY_TYPE_WEEKDAY: frozenset(range(5)),
        DAY_TYPE_SATURDAY: frozenset({5}),
        DAY_TYPE_SUNDAY_HOLIDAY: frozenset({6}),
        DAY_TYPE_WEEKEND: frozenset({5, 6}),
        DAY_TYPE_DAILY: frozenset(range(7)),
    }
    if day_type in fixed:
        return fixed[day_type]
    if day_type.startswith(DOW_PREFIX) and len(day_type) == len(DOW_PREFIX) + 7:
        return frozenset(i for i, b in enumerate(day_type[len(DOW_PREFIX):]) if b == "1")
    return None

_CALENDAR_DAY_COLUMNS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def _classify_day_flags(flags: tuple[bool, ...]) -> str:
    """calendar.txt の曜日フラグ7つ (月→日) から day_type を判定する。"""
    mon_fri = flags[:5]
    sat, sun = flags[5], flags[6]
    if all(mon_fri) and not sat and not sun:
        return DAY_TYPE_WEEKDAY
    if all(flags):
        return DAY_TYPE_DAILY
    if not any(mon_fri):
        if sat and sun:
            return DAY_TYPE_WEEKEND
        if sat:
            return DAY_TYPE_SATURDAY
        if sun:
            return DAY_TYPE_SUNDAY_HOLIDAY
    # 6分類外の曜日指定 (月水金・木のみ等) は「特定日」ではなく
    # 規則的な週次運行 — フラグをそのまま型にする (M10)
    return DOW_PREFIX + "".join("1" if f else "0" for f in flags)


def _classify_dates(dates: list[str], majority: float, short_max_days: int) -> str:
    """calendar_dates の運行日リスト (YYYYMMDD) から day_type を判定する。

    運行日数が short_max_days 以下なら曜日分布に関わらず特定日 (irregular) とする
    (年末年始・お盆等の短期間専用ダイヤが平日等の時刻表に混ざるのを防ぐ)。
    それ以外は曜日分布の多数決。"""
    weekday_bins = {DAY_TYPE_WEEKDAY: 0, DAY_TYPE_SATURDAY: 0, DAY_TYPE_SUNDAY_HOLIDAY: 0}
    valid = 0
    for text in dates:
        try:
            d = datetime.datetime.strptime(text.strip(), "%Y%m%d").date()
        except ValueError:
            logger.warning("calendar_dates: 解析できない日付を無視: %r", text)
            continue
        valid += 1
        wd = d.weekday()  # 月=0 ... 日=6
        if wd <= 4:
            weekday_bins[DAY_TYPE_WEEKDAY] += 1
        elif wd == 5:
            weekday_bins[DAY_TYPE_SATURDAY] += 1
        else:
            weekday_bins[DAY_TYPE_SUNDAY_HOLIDAY] += 1
    if valid == 0 or valid <= short_max_days:
        return DAY_TYPE_IRREGULAR
    best_type, best_count = max(weekday_bins.items(), key=lambda kv: kv[1])
    if best_count / valid >= majority:
        return best_type
    return DAY_TYPE_IRREGULAR


def _parse_date(text: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(text.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def _exception_dates(
    calendar_dates: pd.DataFrame | None,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """service_id → 追加日集合 / 削除日集合 (YYYYMMDD 文字列)。"""
    added: dict[str, set[str]] = defaultdict(set)
    removed: dict[str, set[str]] = defaultdict(set)
    if calendar_dates is not None and not calendar_dates.empty and (
        {"service_id", "date", "exception_type"} <= set(calendar_dates.columns)
    ):
        for _, row in calendar_dates.iterrows():
            etype = str(row["exception_type"]).strip()
            target = added if etype == "1" else removed if etype == "2" else None
            if target is not None:
                target[str(row["service_id"])].add(str(row["date"]).strip())
    return added, removed


def effective_date_list(
    flags: tuple[bool, ...],
    start_text: str,
    end_text: str,
    added: set[str],
    removed: set[str],
    feed_window: tuple[str, str] | None,
) -> tuple[list[str], int] | None:
    """(実効運行日リスト (YYYYMMDD 昇順), フラグ該当日数) を返す。

    どちらもフィード有効期間でクリップした期間内で数える。期間が解析
    できない場合は None (→ フラグ分類)。
    - フラグ該当日数 = 期間×曜日フラグの日数 (削除を引く前)
    - 実効運行日 = フラグ該当日 − calendar_dates 削除 + 追加
    SD1 の分類 (密度判定) と SD3 の表示 (特定日の具体日付) が共用する。"""
    start = _parse_date(start_text)
    end = _parse_date(end_text)
    if start is None or end is None:
        return None
    lo, hi = start, end
    wlo = whi = None
    if feed_window is not None:
        wlo, whi = _parse_date(feed_window[0]), _parse_date(feed_window[1])
        if wlo is not None:
            lo = max(lo, wlo)
        if whi is not None:
            hi = min(hi, whi)
    flag_days = 0
    dates: list[str] = []
    d = lo
    one = datetime.timedelta(days=1)
    while d <= hi:
        if flags[d.weekday()]:
            flag_days += 1
            text = d.strftime("%Y%m%d")
            if text not in removed:
                dates.append(text)
        d += one
    for text in added:
        ad = _parse_date(text)
        if ad is None or text in removed:
            continue
        if (wlo is not None and ad < wlo) or (whi is not None and ad > whi):
            continue
        # 期間×フラグで数えた日と重複させない
        if lo <= ad <= hi and flags[ad.weekday()]:
            continue
        dates.append(text)
    return sorted(dates), flag_days


def _effective_day_stats(
    flags: tuple[bool, ...],
    start_text: str,
    end_text: str,
    added: set[str],
    removed: set[str],
    feed_window: tuple[str, str] | None,
) -> tuple[int, int] | None:
    """(実効運行日数, フラグ該当日数)。密度 (実効/フラグ該当) が SD1 の判定軸:
    祝日専用 service (PRT 型) は 1/17≒0.06、期間分割の正規ダイヤ
    (STM 四半期・桑名同居の残存窓) は 0.9〜1.0。"""
    result = effective_date_list(flags, start_text, end_text, added, removed, feed_window)
    if result is None:
        return None
    dates, flag_days = result
    return len(dates), flag_days


def normalize_day_types(
    calendar: pd.DataFrame | None,
    calendar_dates: pd.DataFrame | None,
    calendar_dates_majority: float,
    short_service_max_days: int = 10,
    feed_window: tuple[str, str] | None = None,
    min_flag_day_ratio: float = 0.5,
) -> dict[str, str]:
    """service_id → day_type の辞書を返す。

    - calendar.txt に曜日フラグを持つ service はフラグで判定。ただし SD1:
      start_date/end_date があれば実効運行日 (期間×フラグ − calendar_dates
      削除 + 追加、feed_window でクリップ) を数え、
      (a) 実効日ゼロ → inactive (期限切れ service 等)、
      (b) 密度 (実効日/フラグ該当日) が min_flag_day_ratio 未満 → irregular
          (米国流の祝日専用 service: フラグ日の大半を削除して特定日だけ残す型)。
      日数でなく密度で判定するのは、期間分割された正規ダイヤ (STM の四半期
      period、同居世代の残存窓) を誤って特定日に落とさないため — それらは
      日数が少なくても密度 0.9〜1.0。
    - 全フラグ 0 または calendar.txt に現れない service は、
      calendar_dates.txt の追加運行日 (exception_type=1) の曜日分布で判定。
    - feed_window は (YYYYMMDD, YYYYMMDD)。feed_info またはリポジトリ世代
      メタから。None ならクリップしない。
    """
    result: dict[str, str] = {}
    zero_flag_services: set[str] = set()
    added_map, removed_map = _exception_dates(calendar_dates)

    if calendar is not None and not calendar.empty:
        missing = [c for c in _CALENDAR_DAY_COLUMNS if c not in calendar.columns]
        if missing:
            logger.warning("calendar.txt に曜日カラムがありません: %s", missing)
        else:
            has_period = {"start_date", "end_date"} <= set(calendar.columns)
            for _, row in calendar.iterrows():
                service_id = row.get("service_id", "")
                flags = tuple(str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS)
                if not any(flags):
                    zero_flag_services.add(service_id)
                    continue
                if has_period:
                    stats = _effective_day_stats(
                        flags,
                        str(row["start_date"]),
                        str(row["end_date"]),
                        added_map.get(service_id, set()),
                        removed_map.get(service_id, set()),
                        feed_window,
                    )
                    if stats is not None:
                        effective, flag_days = stats
                        if effective == 0:
                            result[service_id] = DAY_TYPE_INACTIVE
                            continue
                        if flag_days > 0 and effective / flag_days < min_flag_day_ratio:
                            result[service_id] = DAY_TYPE_IRREGULAR
                            continue
                result[service_id] = _classify_day_flags(flags)

    if calendar_dates is not None and not calendar_dates.empty:
        if {"service_id", "date", "exception_type"} <= set(calendar_dates.columns):
            added = calendar_dates[calendar_dates["exception_type"].str.strip() == "1"]
            for service_id, group in added.groupby("service_id"):
                if service_id in result:
                    continue  # 曜日フラグでの判定を優先
                result[str(service_id)] = _classify_dates(
                    group["date"].tolist(), calendar_dates_majority,
                    short_service_max_days,
                )
        else:
            logger.warning("calendar_dates.txt に必須カラムがありません")

    # 全フラグ 0 で calendar_dates にも追加日がない service = 運行日なし
    # (休止中の定義枠。特定日と混ぜると「走らない便」が便数に紛れる)
    for service_id in zero_flag_services:
        result.setdefault(service_id, DAY_TYPE_INACTIVE)

    return result

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
                 曜日多数決に届かない)。年末年始ダイヤ・連休臨時等
- inactive       運行日なし (全フラグ0・追加運行日なし = 休止中の定義枠)

制約 (M0 時点): 日本の国民の祝日カレンダーは参照しない。祝日が平日に
かかる場合の calendar_dates 例外は irregular 側に倒れることがある。
"""

from __future__ import annotations

import datetime
import logging

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


def normalize_day_types(
    calendar: pd.DataFrame | None,
    calendar_dates: pd.DataFrame | None,
    calendar_dates_majority: float,
    short_service_max_days: int = 10,
) -> dict[str, str]:
    """service_id → day_type の辞書を返す。

    - calendar.txt に曜日フラグを持つ service はフラグで判定。
    - 全フラグ 0 または calendar.txt に現れない service は、
      calendar_dates.txt の追加運行日 (exception_type=1) の曜日分布で判定。
    """
    result: dict[str, str] = {}
    zero_flag_services: set[str] = set()

    if calendar is not None and not calendar.empty:
        missing = [c for c in _CALENDAR_DAY_COLUMNS if c not in calendar.columns]
        if missing:
            logger.warning("calendar.txt に曜日カラムがありません: %s", missing)
        else:
            for _, row in calendar.iterrows():
                service_id = row.get("service_id", "")
                flags = tuple(str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS)
                if not any(flags):
                    zero_flag_services.add(service_id)
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

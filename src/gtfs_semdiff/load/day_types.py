"""calendar / calendar_dates → day_type 正規化。

service_id ごとに運行曜日の型を分類し、世代間で service_id が異なっても
「平日ダイヤ同士」を比較できるようにする (L1 同定・C群ルールの前提)。

区分:
- weekday        月–金のみ
- saturday       土のみ
- sunday_holiday 日のみ (日本のフィードでは日祝一体運用が多い)
- weekend        土日のみ
- daily          毎日
- irregular      上記いずれにも該当しない (特定日運行など)

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
    return DAY_TYPE_IRREGULAR


def _classify_dates(dates: list[str], majority: float) -> str:
    """calendar_dates の運行日リスト (YYYYMMDD) から曜日分布で day_type を判定する。"""
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
    if valid == 0:
        return DAY_TYPE_IRREGULAR
    best_type, best_count = max(weekday_bins.items(), key=lambda kv: kv[1])
    if best_count / valid >= majority:
        return best_type
    return DAY_TYPE_IRREGULAR


def normalize_day_types(
    calendar: pd.DataFrame | None,
    calendar_dates: pd.DataFrame | None,
    calendar_dates_majority: float,
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
                    group["date"].tolist(), calendar_dates_majority
                )
        else:
            logger.warning("calendar_dates.txt に必須カラムがありません")

    # 全フラグ 0 で calendar_dates にも追加日がない service
    for service_id in zero_flag_services:
        result.setdefault(service_id, DAY_TYPE_IRREGULAR)

    return result

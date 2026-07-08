"""load/day_types.py の単体テスト。"""

import pandas as pd

from gtfs_semantic_diff.load.day_types import normalize_day_types

DAY_COLS = "monday,tuesday,wednesday,thursday,friday,saturday,sunday".split(",")


def calendar_df(rows: dict[str, str]) -> pd.DataFrame:
    """service_id → "1111100" 形式のフラグ文字列から calendar DataFrame を作る。"""
    records = []
    for service_id, flags in rows.items():
        rec = {"service_id": service_id}
        rec.update({col: flag for col, flag in zip(DAY_COLS, flags)})
        records.append(rec)
    return pd.DataFrame(records, dtype=str)


def dates_df(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["service_id", "date", "exception_type"], dtype=str)


def test_calendar_flag_classification():
    cal = calendar_df(
        {
            "WD": "1111100",
            "SAT": "0000010",
            "SUN": "0000001",
            "WE": "0000011",
            "ALL": "1111111",
            "MWF": "1010100",
        }
    )
    result = normalize_day_types(cal, None, 0.8)
    assert result == {
        "WD": "weekday",
        "SAT": "saturday",
        "SUN": "sunday_holiday",
        "WE": "weekend",
        "ALL": "daily",
        "MWF": "irregular",
    }


def _weekdays_of_april(service_id, n):
    """2026-04 の平日を先頭から n 日 (月〜金: 4/1〜)。"""
    days = ["20260401", "20260402", "20260403", "20260406", "20260407", "20260408",
            "20260409", "20260410", "20260413", "20260414", "20260415", "20260416",
            "20260417", "20260420", "20260421", "20260422"]
    return [(service_id, d, "1") for d in days[:n]]


def test_calendar_dates_only_service():
    # 平日12日分 (short_service_max_days=10 超) → weekday
    dates = dates_df(_weekdays_of_april("CD1", 12))
    result = normalize_day_types(None, dates, 0.8)
    assert result == {"CD1": "weekday"}


def test_calendar_dates_saturday_service():
    # 土曜のみ12日分 → saturday
    sats = ["20260404", "20260411", "20260418", "20260425", "20260502", "20260509",
            "20260516", "20260523", "20260530", "20260606", "20260613", "20260620"]
    dates = dates_df([("CD2", d, "1") for d in sats])
    assert normalize_day_types(None, dates, 0.8) == {"CD2": "saturday"}


def test_calendar_dates_mixed_is_irregular():
    # 平日と土曜が半々 (12日) → majority 0.8 に届かず irregular
    mixed = _weekdays_of_april("CD3", 6) + [
        ("CD3", d, "1") for d in ["20260404", "20260411", "20260418",
                                   "20260425", "20260502", "20260509"]
    ]
    assert normalize_day_types(None, dates_df(mixed), 0.8) == {"CD3": "irregular"}


def test_short_period_service_is_irregular():
    # 年末年始型: 平日中心でも10日以下なら特定日 (平日時刻表への混入防止)
    dates = dates_df(
        [("NY", d, "1") for d in ["20261229", "20261230", "20261231",
                                   "20270104", "20270105", "20270106"]]
    )
    assert normalize_day_types(None, dates, 0.8) == {"NY": "irregular"}


def test_exception_type_2_removals_ignored():
    rows = [("CD4", "20260406", "2")] + _weekdays_of_april("CD4", 12)
    assert normalize_day_types(None, dates_df(rows), 0.8) == {"CD4": "weekday"}


def test_calendar_flags_take_precedence_over_dates():
    cal = calendar_df({"S1": "1111100"})
    dates = dates_df([("S1", "20260404", "1")])  # 土曜の追加運行があっても平日ダイヤ扱い
    assert normalize_day_types(cal, dates, 0.8) == {"S1": "weekday"}


def test_zero_flag_service_falls_back_to_dates():
    cal = calendar_df({"Z1": "0000000"})
    sats = ["20260404", "20260411", "20260418", "20260425", "20260502", "20260509",
            "20260516", "20260523", "20260530", "20260606", "20260613", "20260620"]
    dates = dates_df([("Z1", d, "1") for d in sats])
    assert normalize_day_types(cal, dates, 0.8) == {"Z1": "saturday"}


def test_zero_flag_service_without_dates_is_irregular():
    cal = calendar_df({"Z2": "0000000"})
    assert normalize_day_types(cal, None, 0.8) == {"Z2": "irregular"}

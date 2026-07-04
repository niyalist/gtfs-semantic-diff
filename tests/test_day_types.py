"""load/day_types.py の単体テスト。"""

import pandas as pd

from gtfs_semdiff.load.day_types import normalize_day_types

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


def test_calendar_dates_only_service():
    # 2026-04 の月〜金 (4/6=月 ... 4/10=金) → weekday
    dates = dates_df([("CD1", f"2026040{d}", "1") for d in range(6, 10)] + [("CD1", "20260410", "1")])
    result = normalize_day_types(None, dates, 0.8)
    assert result == {"CD1": "weekday"}


def test_calendar_dates_saturday_service():
    # 2026-04 の土曜: 4/4, 4/11, 4/18, 4/25
    dates = dates_df([("CD2", d, "1") for d in ["20260404", "20260411", "20260418", "20260425"]])
    assert normalize_day_types(None, dates, 0.8) == {"CD2": "saturday"}


def test_calendar_dates_mixed_is_irregular():
    # 平日と土曜が半々 → majority 0.8 に届かず irregular
    dates = dates_df(
        [("CD3", d, "1") for d in ["20260406", "20260407", "20260404", "20260411"]]
    )
    assert normalize_day_types(None, dates, 0.8) == {"CD3": "irregular"}


def test_exception_type_2_removals_ignored():
    dates = dates_df([("CD4", "20260406", "2"), ("CD4", "20260407", "1")])
    assert normalize_day_types(None, dates, 0.8) == {"CD4": "weekday"}


def test_calendar_flags_take_precedence_over_dates():
    cal = calendar_df({"S1": "1111100"})
    dates = dates_df([("S1", "20260404", "1")])  # 土曜の追加運行があっても平日ダイヤ扱い
    assert normalize_day_types(cal, dates, 0.8) == {"S1": "weekday"}


def test_zero_flag_service_falls_back_to_dates():
    cal = calendar_df({"Z1": "0000000"})
    dates = dates_df([("Z1", "20260404", "1"), ("Z1", "20260411", "1")])
    assert normalize_day_types(cal, dates, 0.8) == {"Z1": "saturday"}


def test_zero_flag_service_without_dates_is_irregular():
    cal = calendar_df({"Z2": "0000000"})
    assert normalize_day_types(cal, None, 0.8) == {"Z2": "irregular"}

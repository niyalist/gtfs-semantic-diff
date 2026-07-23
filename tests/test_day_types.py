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
        "MWF": "dow_1010100",  # M10: 曜日指定は特定日ではなく一級の型
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


def test_zero_flag_service_without_dates_is_inactive():
    # M10: 運行日ゼロは「運行日なし」— 特定日と混ぜない (名古屋の休止枠の実例)
    cal = calendar_df({"Z2": "0000000"})
    assert normalize_day_types(cal, None, 0.8) == {"Z2": "inactive"}


# ---- SD1: 実効運行日ベースの分類 (docs/design/service_days.md §2.1) ----


def calendar_df_period(rows: dict[str, tuple[str, str, str]]) -> pd.DataFrame:
    """service_id → (フラグ7桁, start_date, end_date) の calendar DataFrame。"""
    records = []
    for service_id, (flags, start, end) in rows.items():
        rec = {"service_id": service_id, "start_date": start, "end_date": end}
        rec.update({col: flag for col, flag in zip(DAY_COLS, flags)})
        records.append(rec)
    return pd.DataFrame(records, dtype=str)


def test_sd1_holiday_only_service_is_irregular():
    # T1 (PRT 型): 土曜フラグ + 通常土曜を全削除 + 祝日1日だけ運行 → irregular。
    # 通常土曜 service は影響を受けず saturday のまま
    cal = calendar_df_period({
        "HOL": ("0000010", "20260628", "20261024"),
        "SAT": ("0000010", "20260628", "20261024"),
    })
    sats = ["20260704", "20260711", "20260718", "20260725", "20260801", "20260808",
            "20260815", "20260822", "20260829", "20260905", "20260912", "20260919",
            "20260926", "20261003", "20261010", "20261017", "20261024"]
    rows = [("HOL", d, "2") for d in sats if d != "20260704"]
    rows += [("HOL", "20260704", "1"), ("SAT", "20260704", "2")]
    result = normalize_day_types(cal, dates_df(rows), 0.8)
    assert result == {"HOL": "irregular", "SAT": "saturday"}


def test_sd1_expired_service_is_inactive():
    # T6 (PRT 型): 期間がフィード有効期間の丸ごと外 → inactive
    cal = calendar_df_period({
        "OLD": ("1111100", "20251019", "20260221"),
        "CUR": ("1111100", "20260628", "20261014"),
    })
    result = normalize_day_types(
        cal, None, 0.8, feed_window=("20260628", "20261014"))
    assert result == {"OLD": "inactive", "CUR": "weekday"}


def test_sd1_all_days_removed_is_inactive():
    # 期間×フラグの全日が calendar_dates で削除 → inactive
    cal = calendar_df_period({"X": ("0000010", "20260704", "20260718")})
    rows = [("X", d, "2") for d in ["20260704", "20260711", "20260718"]]
    assert normalize_day_types(cal, dates_df(rows), 0.8) == {"X": "inactive"}


def test_sd1_normal_service_unchanged():
    # 回帰: 実効日が十分ある通常 service は従来どおり (削除が少しあっても)
    cal = calendar_df_period({
        "WD": ("1111100", "20260401", "20261231"),
        "MWF": ("1010100", "20260401", "20261231"),
    })
    rows = [("WD", "20260720", "2"), ("WD", "20260811", "2")]
    result = normalize_day_types(cal, dates_df(rows), 0.8)
    assert result == {"WD": "weekday", "MWF": "dow_1010100"}


def test_sd1_short_period_regular_service_keeps_type():
    # 期間分割された正規ダイヤ (STM 四半期・同居世代の残存窓): 日数は少なくても
    # 密度 1.0 → 型を維持する (日数閾値でなく密度判定である理由)
    cal = calendar_df_period({
        "SAT6": ("0000010", "20260601", "20260710"),   # 土曜6回・削除なし
        "SAT10": ("0000010", "20260110", "20260321"),  # 土曜11回・祝日1回削除
    })
    rows = [("SAT10", "20260321", "2")]
    result = normalize_day_types(cal, dates_df(rows), 0.8)
    assert result == {"SAT6": "saturday", "SAT10": "saturday"}


def test_sd1_no_period_columns_falls_back_to_flags():
    # calendar に start/end が無ければ実効日判定はスキップ (従来挙動)
    cal = calendar_df({"WD": "1111100"})
    assert normalize_day_types(cal, None, 0.8) == {"WD": "weekday"}


def test_day_set_of():
    from gtfs_semantic_diff.load.day_types import day_set_of

    assert day_set_of("weekday") == frozenset(range(5))
    assert day_set_of("dow_1010000") == frozenset({0, 2})
    assert day_set_of("dow_1010000") < day_set_of("weekday")  # 増便型の包含判定
    assert day_set_of("irregular") is None
    assert day_set_of("inactive") is None

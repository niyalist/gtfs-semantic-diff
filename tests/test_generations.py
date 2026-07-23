"""SD2 (窓内区間対比較) のパイプライン統合テスト。

T2 (世代同梱) の合成フィードで、桑名で実測した2方向の誤説明
(全便半減 / 全便倍増) が出ないこと、および通常フィードでの退化を確認する。
"""

from __future__ import annotations

from gtfs_semantic_diff.events.pipeline import compare_snapshots
from gtfs_semantic_diff.load import load_snapshot

from .conftest import make_gtfs_zip

# 旧世代 (A) と新世代 (B) のダイヤ: B は T1 の時刻を5分繰り下げ
_TRIPS_A = (
    "route_id,service_id,trip_id\n"
    "R1,WD_A,TA1\nR1,WD_A,TA2\n"
)
_ST_A = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "TA1,08:00:00,08:00:00,S1,1\nTA1,08:05:00,08:05:00,S2,2\nTA1,08:10:00,08:10:00,S3,3\n"
    "TA2,09:00:00,09:00:00,S1,1\nTA2,09:05:00,09:05:00,S2,2\nTA2,09:10:00,09:10:00,S3,3\n"
)
_TRIPS_AB = (
    "route_id,service_id,trip_id\n"
    "R1,WD_A,TA1\nR1,WD_A,TA2\n"
    "R1,WD_B,TB1\nR1,WD_B,TB2\n"
)
_ST_AB = (
    _ST_A
    + "TB1,08:05:00,08:05:00,S1,1\nTB1,08:10:00,08:10:00,S2,2\nTB1,08:15:00,08:15:00,S3,3\n"
    + "TB2,09:00:00,09:00:00,S1,1\nTB2,09:05:00,09:05:00,S2,2\nTB2,09:10:00,09:10:00,S3,3\n"
)
_TRIPS_B = (
    "route_id,service_id,trip_id\n"
    "R1,WD_B,TB1\nR1,WD_B,TB2\n"
)
_ST_B = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "TB1,08:05:00,08:05:00,S1,1\nTB1,08:10:00,08:10:00,S2,2\nTB1,08:15:00,08:15:00,S3,3\n"
    "TB2,09:00:00,09:00:00,S1,1\nTB2,09:05:00,09:05:00,S2,2\nTB2,09:10:00,09:10:00,S3,3\n"
)

_CAL_PRE = (  # 改正前のみ: A が 6/1〜10/3
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\n"
    "WD_A,1,1,1,1,1,0,0,20260601,20261003\n"
)
_CAL_COEX = (  # 同居: A 6/1〜7/10 + B 7/11〜10/12
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\n"
    "WD_A,1,1,1,1,1,0,0,20260601,20260710\n"
    "WD_B,1,1,1,1,1,0,0,20260711,20261012\n"
)
_CAL_POST = (  # 改正後のみ: B が 7/11〜10/23
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\n"
    "WD_B,1,1,1,1,1,0,0,20260711,20261023\n"
)


def _load_pair(tmp_path, config, old_files, new_files):
    old = load_snapshot(
        make_gtfs_zip(tmp_path, old_files, name="old.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, new_files, name="new.zip"), config=config)
    return compare_snapshots(old, new, config)


def _counts(event_set):
    from collections import Counter
    return Counter(e.type for e in event_set.events)


def test_coexistence_as_new_side_no_false_increase(tmp_path, config):
    """改正前のみ vs 同居: 偽増便を出さず「7/11 改正」の中身 (時刻変更) が出る。"""
    event_set, rawdiffs = _load_pair(
        tmp_path, config,
        {"calendar.txt": _CAL_PRE, "trips.txt": _TRIPS_A, "stop_times.txt": _ST_A},
        {"calendar.txt": _CAL_COEX, "trips.txt": _TRIPS_AB, "stop_times.txt": _ST_AB},
    )
    counts = _counts(event_set)
    assert counts.get("SERVICE_INCREASED", 0) == 0  # 桑名実測2の偽増便が出ない
    assert counts.get("GENERATION_SCOPE", 0) == 1
    # 比較は A vs B: TA1 (8:00) → TB1 (8:05) の変化が便レベルで説明される
    assert event_set.accounting.explained_ratio == 1.0
    scope = event_set.context["comparison_scope"]
    assert scope["primary_periods"] == [["20260711", "20261003"]]
    assert scope["identical_periods"] == [["20260601", "20260710"]]
    assert scope["excluded"]["new_services"] == ["WD_A"]


def test_coexistence_as_old_side_no_false_decrease(tmp_path, config):
    """同居 vs 改正後のみ: 旧世代は窓外に落ち、偽減便を出さない。"""
    event_set, rawdiffs = _load_pair(
        tmp_path, config,
        {"calendar.txt": _CAL_COEX, "trips.txt": _TRIPS_AB, "stop_times.txt": _ST_AB},
        {"calendar.txt": _CAL_POST, "trips.txt": _TRIPS_B, "stop_times.txt": _ST_B},
    )
    counts = _counts(event_set)
    assert counts.get("SERVICE_REDUCED", 0) == 0  # 桑名実測1の偽減便が出ない
    assert counts.get("TRIP_DISCONTINUED", 0) == 0
    assert event_set.accounting.explained_ratio == 1.0
    scope = event_set.context["comparison_scope"]
    assert scope["excluded"]["old_services"] == ["WD_A"]
    assert scope["excluded"]["old_trips"] == 2


def test_coexistence_both_sides_all_identical(tmp_path, config):
    """同居 vs 同居 (窓が1日伸びただけ): 変化イベントなしに圧縮される。"""
    cal2 = _CAL_COEX.replace("20261012", "20261013")
    event_set, rawdiffs = _load_pair(
        tmp_path, config,
        {"calendar.txt": _CAL_COEX, "trips.txt": _TRIPS_AB, "stop_times.txt": _ST_AB},
        {"calendar.txt": cal2, "trips.txt": _TRIPS_AB, "stop_times.txt": _ST_AB},
    )
    counts = _counts(event_set)
    assert counts.get("SERVICE_INCREASED", 0) == 0
    assert counts.get("SERVICE_REDUCED", 0) == 0
    assert event_set.accounting.explained_ratio == 1.0


def test_uneven_service_periods_degenerate(tmp_path, config):
    """通常フィードで service の期間端がずれているだけ (上位集合ユニットが存在)
    なら退化し、スコープは付かない (学期末で終わる通学 service の例)。"""
    cal = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "WD,1,1,1,1,1,0,0,20260401,20270331\n"
        "SCHOOL,1,1,1,1,1,0,0,20260401,20260718\n"
    )
    trips = (
        "route_id,service_id,trip_id\n"
        "R1,WD,T1\nR1,WD,T2\nR1,SCHOOL,T3\n"
    )
    st = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\nT1,08:05:00,08:05:00,S2,2\nT1,08:10:00,08:10:00,S3,3\n"
        "T2,09:00:00,09:00:00,S1,1\nT2,09:05:00,09:05:00,S2,2\nT2,09:10:00,09:10:00,S3,3\n"
        "T3,07:00:00,07:00:00,S1,1\nT3,07:05:00,07:05:00,S2,2\nT3,07:10:00,07:10:00,S3,3\n"
    )
    files = {"calendar.txt": cal, "trips.txt": trips, "stop_times.txt": st}
    event_set, rawdiffs = _load_pair(tmp_path, config, files, dict(files))
    assert event_set.context["comparison_scope"] is None
    assert _counts(event_set).get("GENERATION_SCOPE", 0) == 0

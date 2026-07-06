"""report/presentation.py (V2 ビューモデル) の単体テスト。凍結要件 R1〜R17 準拠。"""

import json

from gtfs_semdiff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semdiff.load import load_snapshot
from gtfs_semdiff.report.presentation import (
    align_to_axis,
    build_presentation,
    build_stop_axis,
    merge_axis,
)

from .conftest import MINIMAL_FEED, make_gtfs_zip


def build(tmp_path, config, old_files=None, new_files=None):
    old = load_snapshot(make_gtfs_zip(tmp_path, files=old_files, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=new_files, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    model = build_presentation(event_set, identity, trip_delta, config)
    return model, event_set


def page_of(model, group):
    return next(p for p in model["route_pages"] if p["route_group"] == group)


# --- 停留所軸の併合 (R17: 途中止まり・経由違い・逆方向) ---


def test_merge_axis_subset():
    full = ("A", "B", "C", "D", "E")
    short = ("A", "B", "C")  # 途中止まり
    axis = merge_axis(full, short)
    assert axis == full  # 部分列はそのまま吸収


def test_merge_axis_branch():
    a = ("A", "B", "C", "D")
    b = ("A", "B", "X", "D")  # 経由違い
    axis = build_stop_axis([a, b])
    # 双方の超列である
    for seq in (a, b):
        assert all(p >= 0 for p in align_to_axis(seq, axis))
    assert set(axis) == {"A", "B", "C", "X", "D"}


def test_axis_supersequence_of_many():
    seqs = [
        ("A", "B", "C", "D", "E"),
        ("A", "C", "E"),          # 急行 (通過)
        ("A", "B", "Y", "D", "E"),  # 迂回
        ("B", "C", "D"),          # 区間便
    ]
    axis = build_stop_axis(seqs)
    for seq in seqs:
        positions = align_to_axis(seq, axis)
        assert all(p >= 0 for p in positions)
        assert positions == sorted(positions)  # 順序保存


def test_align_reverse_direction_not_forced():
    # 逆方向の列は同じ軸に無理に載らない (方向グループが分ける前提の防御確認)
    axis = ("A", "B", "C")
    positions = align_to_axis(("C", "B", "A"), axis)
    assert -1 in positions  # 全ては合わせられない (防御的挙動)


# --- 方向グループ (R15) と時刻表 ---

BIDIRECTIONAL = {
    "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\nR1,WD,T2\nR1,WD,R1t\nR1,WD,R2t\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\nT1,08:05:00,08:05:00,S2,2\nT1,08:10:00,08:10:00,S3,3\n"
        "T2,09:00:00,09:00:00,S1,1\nT2,09:05:00,09:05:00,S2,2\nT2,09:10:00,09:10:00,S3,3\n"
        "R1t,08:30:00,08:30:00,S3,1\nR1t,08:35:00,08:35:00,S2,2\nR1t,08:40:00,08:40:00,S1,3\n"
        "R2t,09:30:00,09:30:00,S3,1\nR2t,09:35:00,09:35:00,S2,2\nR2t,09:40:00,09:40:00,S1,3\n"
    ),
}


def test_direction_group_pairs_reverse_legs(tmp_path, config):
    model, _ = build(tmp_path, config, old_files=BIDIRECTIONAL, new_files=BIDIRECTIONAL)
    page = page_of(model, "1")
    dgs = page["overview"]["direction_groups"]
    assert len(dgs) == 1
    assert dgs[0]["kind"] == "bidirectional"
    legs = {s["leg"] for s in dgs[0]["systems"]}
    assert legs == {"forward", "reverse"}
    # 時刻表は (方向グループ, leg, 曜日) 単位
    tables = page["timetables"]
    assert {(t["leg"]) for t in tables} == {"forward", "reverse"}
    fwd = next(t for t in tables if t["leg"] == "forward")
    assert fwd["stop_axis"] == ["駅前", "市役所前", "病院前"]
    assert all(c["status"] == "unchanged" for c in fwd["columns"])


# --- ② Lev カスケード ---


def test_level1_suppresses_lower_levels(tmp_path, config):
    # 路線「99」が新設 → Lev.1 のみ
    from .test_rules import EXTRA_ROUTE_OLD

    model, _ = build(
        tmp_path, config,
        old_files={"stops.txt": EXTRA_ROUTE_OLD["stops.txt"]},
        new_files=EXTRA_ROUTE_OLD,
    )
    page = page_of(model, "99")
    assert page["summary"]["level1"] == {"kind": "added", "trips": 1}
    assert page["summary"]["level2"] == []
    assert page["summary"]["level4"] == []
    assert page["has_changes"]


def test_level2_system_added(tmp_path, config):
    # 既存路線に別コリドーの系統 (2便) が加わる → Lev.2 system_added
    new_files = {
        "stops.txt": MINIMAL_FEED["stops.txt"]
        + "S8,山手台,36.2000,139.2000\nS9,山手奥,36.2100,139.2100\n",
        "trips.txt": MINIMAL_FEED["trips.txt"] + "R1,WD,TX1\nR1,WD,TX2\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "TX1,10:00:00,10:00:00,S8,1\nTX1,10:10:00,10:10:00,S9,2\n"
        + "TX2,15:00:00,15:00:00,S8,1\nTX2,15:10:00,15:10:00,S9,2\n",
    }
    old_files = {"stops.txt": new_files["stops.txt"]}
    model, _ = build(tmp_path, config, old_files=old_files, new_files=new_files)
    page = page_of(model, "1")
    lev2 = page["summary"]["level2"]
    assert len(lev2) == 1
    assert lev2[0]["kind"] == "system_added"
    assert lev2[0]["label"] == "山手台→山手奥"
    assert lev2[0]["trips"] == 2


def test_level3_coverage(tmp_path, config):
    # 2便中1便だけ経由地追加 → coverage 0.5、full_coverage=False (R13)
    files = {
        "stops.txt": MINIMAL_FEED["stops.txt"] + "S5,経由地,36.005,139.005\n",
    }
    new_files = {
        "stops.txt": files["stops.txt"],
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:03:00,08:03:00,S5,2\n"
            "T1,08:05:00,08:05:00,S2,3\n"
            "T1,08:10:00,08:10:00,S3,4\n"
            "T2,09:00:00,09:00:00,S1,1\n"
            "T2,09:05:00,09:05:00,S2,2\n"
            "T2,09:10:00,09:10:00,S3,3\n"
        ),
    }
    model, _ = build(tmp_path, config, old_files=files, new_files=new_files)
    page = page_of(model, "1")
    lev3 = page["summary"]["level3"]
    assert len(lev3) == 1
    assert lev3[0]["affected_trips"] == 1
    assert lev3[0]["coverage"] == 0.5
    assert lev3[0]["full_coverage"] is False
    assert lev3[0]["changes"][0]["stops"] == ["経由地"]


def test_level4_signed_band_sums(tmp_path, config):
    # 7-9時帯 +1、9-16時帯 -1 → net 0 だが 増1・減1 (R14: シフトと区別)
    new_files = {
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\nR1,WD,T3\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
            "T3,07:30:00,07:30:00,S1,1\n"
            "T3,07:35:00,07:35:00,S2,2\n"
            "T3,07:40:00,07:40:00,S3,3\n"
        ),
    }
    model, _ = build(tmp_path, config, new_files=new_files)
    page = page_of(model, "1")
    lev4 = page["summary"]["level4"]
    assert len(lev4) == 1
    assert (lev4[0]["net"], lev4[0]["increased"], lev4[0]["decreased"]) == (0, 1, 1)


def test_level5_retimed_count(tmp_path, config):
    # T2 全体を20分シフト → Lev.5 の時刻微調整 1便、Lev.4 は空 (ビン内移動)
    new_st = (
        MINIMAL_FEED["stop_times.txt"]
        .replace("T2,09:00:00,09:00:00", "T2,09:20:00,09:20:00")
        .replace("T2,09:05:00,09:05:00", "T2,09:25:00,09:25:00")
        .replace("T2,09:10:00,09:10:00", "T2,09:30:00,09:30:00")
    )
    model, _ = build(tmp_path, config, new_files={"stop_times.txt": new_st})
    page = page_of(model, "1")
    assert page["summary"]["level5"]["retimed_trips"] == 1
    assert page["summary"]["level4"] == []


# --- ③ 本数マトリクス / ④ 時刻表の差分素材 ---


def test_band_matrix_structure_and_day_order(tmp_path, config):
    # 平日 + 土曜サービス → 集計行が曜日固定順 (R3, R16)。変更なしでも行が出る
    files = {
        "calendar.txt": MINIMAL_FEED["calendar.txt"]
        + "SAT,0,0,0,0,0,1,0,20260401,20270331\n",
        "trips.txt": MINIMAL_FEED["trips.txt"] + "R1,SAT,T7\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "T7,10:00:00,10:00:00,S1,1\nT7,10:05:00,10:05:00,S2,2\nT7,10:10:00,10:10:00,S3,3\n",
    }
    model, _ = build(tmp_path, config, old_files=files, new_files=files)
    page = page_of(model, "1")
    agg = [r for r in page["band_matrix"]["rows"] if r["kind"] == "aggregate"]
    assert [r["day_type"] for r in agg] == ["weekday", "saturday"]  # 固定順
    assert all(not r["changed"] for r in agg)  # 変更なし行も存在し changed=False
    assert not page["has_changes"]


def test_timetable_diff_columns(tmp_path, config):
    # T1 時刻変更 + T2 廃止 + T9 新設 → 差分素材 (status / changed_positions)
    new_files = {
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\nR1,WD,T9\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:18:00,08:18:00,S3,3\n"  # S3 のみ +8分
            "T9,11:00:00,11:00:00,S1,1\n"
            "T9,11:05:00,11:05:00,S2,2\n"
            "T9,11:10:00,11:10:00,S3,3\n"
        ),
    }
    model, _ = build(tmp_path, config, new_files=new_files)
    page = page_of(model, "1")
    tables = page["timetables"]
    assert len(tables) == 1
    cols = tables[0]["columns"]
    by_status = {c["status"]: c for c in cols}
    assert set(by_status) == {"retimed", "removed", "added"}
    assert by_status["retimed"]["changed_positions"] == [2]  # S3 のみ
    assert by_status["removed"]["times_new"] is None
    assert by_status["added"]["times_old"] is None
    # 発時刻順 (旧廃止便 09:00 は retimed 08:00 と added 11:00 の間)
    assert [c["status"] for c in cols] == ["retimed", "removed", "added"]


# --- 互換性 (コア不変の保証) ---


def test_presentation_does_not_mutate_events(tmp_path, config):
    from .test_diff0 import NEW_FILES

    old = load_snapshot(make_gtfs_zip(tmp_path, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    before = json.dumps(event_set.to_dict(), ensure_ascii=False, sort_keys=True)
    model = build_presentation(event_set, identity, trip_delta, config)
    after = json.dumps(event_set.to_dict(), ensure_ascii=False, sort_keys=True)
    assert before == after  # ビューモデル生成はイベント/会計を変更しない
    json.dumps(model, ensure_ascii=False)  # JSON 直列化可能

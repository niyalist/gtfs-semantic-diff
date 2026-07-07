"""report/presentation.py (V2 ビューモデル) の単体テスト。凍結要件 R1〜R17 準拠。"""

import json

from gtfs_semdiff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semdiff.load import load_snapshot
from gtfs_semdiff.report.presentation import (
    _is_subsequence,
    align_to_axis,
    build_presentation,
    build_stop_axis,
    merge_axis,
    order_agreement,
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


# --- 方向グループ R15 改訂 (V2.1): 順序整合度による束ね ---

SIX_STOPS = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S0,営業所,35.9900,138.9900\n"
        "S1,駅前,36.0000,139.0000\n"
        "S2,市役所前,36.0100,139.0100\n"
        "S3,病院前,36.0200,139.0200\n"
        "S4,高校前,36.0300,139.0300\n"
        "S5,温泉口,36.0400,139.0400\n"
        "S6,新道,36.0500,139.0500\n"
    ),
}


def _stop_times(specs):
    """specs: [(trip_id, 開始時, [stop_id,...]), ...] → stop_times.txt 文字列。"""
    lines = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    for trip, hour, stops in specs:
        for i, s in enumerate(stops):
            t = f"{hour:02d}:{i * 5:02d}:00"
            lines.append(f"{trip},{t},{t},{s},{i + 1}")
    return "\n".join(lines) + "\n"


def test_order_agreement_values():
    assert order_agreement(list("ABCDE"), list("EDCBA")) == (0.0, 5)
    assert order_agreement(list("ABCDE"), list("BCD")) == (1.0, 3)
    agree, shared = order_agreement(
        ["A", "B", "C", "D", "E"], ["C", "D", "X", "A", "B"]
    )
    assert shared == 4
    assert 0.2 < agree < 0.8  # 中間域


def test_direction_group_asymmetric_reversal(tmp_path, config):
    # 岩屋線型: 復路が往路の起点を超えて別の端点 (営業所) まで走る。
    # 端点は完全逆転でないが、順序整合度 0 なので往復として束ねる (R15 改訂)
    feed = dict(SIX_STOPS)
    feed["trips.txt"] = (
        "route_id,service_id,trip_id\nR1,WD,F1\nR1,WD,F2\nR1,WD,B1\nR1,WD,B2\n"
    )
    feed["stop_times.txt"] = _stop_times([
        ("F1", 8, ["S1", "S2", "S3", "S4", "S5"]),
        ("F2", 9, ["S1", "S2", "S3", "S4", "S5"]),
        ("B1", 8, ["S5", "S4", "S3", "S2", "S0"]),
        ("B2", 9, ["S5", "S4", "S3", "S2", "S0"]),
    ])
    model, _ = build(tmp_path, config, old_files=feed, new_files=feed)
    page = page_of(model, "1")
    dgs = page["overview"]["direction_groups"]
    assert len(dgs) == 1
    assert dgs[0]["kind"] == "bidirectional"
    assert {s["leg"] for s in dgs[0]["systems"]} == {"forward", "reverse"}


def test_direction_group_merges_short_turn_same_direction(tmp_path, config):
    # 区間便: 端点が違っても順序整合度 >= same_min なら同じ leg に束ね、
    # 同一の時刻表に併合される (区間外セルは None = 運行区間外)
    feed = dict(SIX_STOPS)
    feed["trips.txt"] = (
        "route_id,service_id,trip_id\nR1,WD,F1\nR1,WD,F2\nR1,WD,H1\nR1,WD,H2\n"
    )
    feed["stop_times.txt"] = _stop_times([
        ("F1", 8, ["S1", "S2", "S3", "S4", "S5"]),
        ("F2", 9, ["S1", "S2", "S3", "S4", "S5"]),
        ("H1", 10, ["S2", "S3", "S4"]),
        ("H2", 11, ["S2", "S3", "S4"]),
    ])
    model, _ = build(tmp_path, config, old_files=feed, new_files=feed)
    page = page_of(model, "1")
    dgs = page["overview"]["direction_groups"]
    assert len(dgs) == 1
    assert all(s["leg"] == "forward" for s in dgs[0]["systems"])
    tables = page["timetables"]
    assert len(tables) == 1  # (dg, forward, weekday) の1枚に併合
    assert len(tables[0]["columns"]) == 4
    axis = tables[0]["stop_axis"]
    assert axis == ["駅前", "市役所前", "病院前", "高校前", "温泉口"]
    short_col = tables[0]["columns"][2]  # 10時発の区間便
    assert short_col["times_new"][0] is None  # 駅前は運行区間外
    assert short_col["times_new"][-1] is None


def test_direction_group_mid_agreement_not_merged(tmp_path, config):
    # 順序整合度が中間域 (reversed_max < agree < same_min) のペアは束ねない
    feed = dict(SIX_STOPS)
    feed["trips.txt"] = (
        "route_id,service_id,trip_id\nR1,WD,F1\nR1,WD,F2\nR1,WD,G1\nR1,WD,G2\n"
    )
    feed["stop_times.txt"] = _stop_times([
        ("F1", 8, ["S1", "S2", "S3", "S4", "S5"]),
        ("F2", 9, ["S1", "S2", "S3", "S4", "S5"]),
        ("G1", 8, ["S3", "S4", "S6", "S1", "S2"]),
        ("G2", 9, ["S3", "S4", "S6", "S1", "S2"]),
    ])
    model, _ = build(tmp_path, config, old_files=feed, new_files=feed)
    page = page_of(model, "1")
    assert len(page["overview"]["direction_groups"]) == 2


# --- ①路線概要の leg ビュー (R2 改: 極大パターン線・鏡像畳み込み) ---


def test_is_subsequence():
    assert _is_subsequence(("B", "C"), ("A", "B", "C", "D"))
    assert _is_subsequence(("A", "C"), ("A", "B", "C"))  # 非連続も部分列
    assert not _is_subsequence(("C", "B"), ("A", "B", "C"))  # 順序が違う


def test_leg_view_prunes_contained_short_turn(tmp_path, config):
    # 区間便 (完全包含) は地図の線を増やさない。軸には全停留所が入る
    feed = dict(SIX_STOPS)
    feed["trips.txt"] = (
        "route_id,service_id,trip_id\nR1,WD,F1\nR1,WD,F2\nR1,WD,H1\nR1,WD,H2\n"
    )
    feed["stop_times.txt"] = _stop_times([
        ("F1", 8, ["S1", "S2", "S3", "S4", "S5"]),
        ("F2", 9, ["S1", "S2", "S3", "S4", "S5"]),
        ("H1", 10, ["S2", "S3", "S4"]),
        ("H2", 11, ["S2", "S3", "S4"]),
    ])
    model, _ = build(tmp_path, config, old_files=feed, new_files=feed)
    page = page_of(model, "1")
    dg = page["overview"]["direction_groups"][0]
    (leg,) = dg["legs"]
    assert len(leg["lines"]) == 1  # 区間便は極大パターンに吸収
    assert leg["lines"][0]["stops"] == ["駅前", "市役所前", "病院前", "高校前", "温泉口"]
    assert leg["axis"] == ["駅前", "市役所前", "病院前", "高校前", "温泉口"]
    # 区間便の端点は key_stops (tier2 以下) で強調される
    assert page["overview"]["key_stops"].get("市役所前", 3) <= 2
    assert page["overview"]["key_stops"].get("高校前", 3) <= 2


def test_axis_rows_mirror_collapsed(tmp_path, config):
    # 往復が完全な鏡像なら停車列は「A ⇄ B」1行に畳む
    model, _ = build(tmp_path, config, old_files=BIDIRECTIONAL, new_files=BIDIRECTIONAL)
    page = page_of(model, "1")
    dg = page["overview"]["direction_groups"][0]
    assert dg["axis_rows"] == [{
        "label": "駅前 ⇄ 病院前", "kind": "pair",
        "stops": ["駅前", "市役所前", "病院前"],
    }]


def test_axis_rows_asymmetric_stays_two_rows(tmp_path, config):
    # 岩屋線型 (非対称往復) は2行のままになり、非対称であることが見える
    feed = dict(SIX_STOPS)
    feed["trips.txt"] = (
        "route_id,service_id,trip_id\nR1,WD,F1\nR1,WD,F2\nR1,WD,B1\nR1,WD,B2\n"
    )
    feed["stop_times.txt"] = _stop_times([
        ("F1", 8, ["S1", "S2", "S3", "S4", "S5"]),
        ("F2", 9, ["S1", "S2", "S3", "S4", "S5"]),
        ("B1", 10, ["S5", "S4", "S3", "S2", "S0"]),  # 発時刻を後にして canon を往路に
        ("B2", 11, ["S5", "S4", "S3", "S2", "S0"]),
    ])
    model, _ = build(tmp_path, config, old_files=feed, new_files=feed)
    page = page_of(model, "1")
    dg = page["overview"]["direction_groups"][0]
    rows = dg["axis_rows"]
    assert [r["kind"] for r in rows] == ["leg", "leg"]
    assert rows[0]["stops"][-1] == "温泉口"
    assert rows[1]["stops"][-1] == "営業所"  # 復路の別端点が行として現れる


# --- 停留所の変化章 (V4) ---


def test_stop_changes_section(tmp_path, config):
    # S2 改称 (路線1に紐付く) + S4 新設 (どの路線にも属さない)
    new_files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "S1,駅前,36.0000,139.0000\n"
            "S2,市役所前東,36.0100,139.0100\n"
            "S3,病院前,36.0200,139.0200\n"
            "S4,新町,36.0500,139.0500\n"
        ),
    }
    model, _ = build(tmp_path, config, new_files=new_files)
    sc = model["stop_changes"]
    assert [(r["old_name"], r["new_name"]) for r in sc["renamed"]] == [
        ("市役所前", "市役所前東")
    ]
    assert sc["renamed"][0]["groups"] == ["1"]  # 関係路線
    assert sc["renamed"][0]["lat"] is not None
    # 新設は影響路線の組ごとにまとめる。S4 は路線に属さない
    assert len(sc["added"]) == 1
    assert sc["added"][0]["groups"] == []
    assert [s["name"] for s in sc["added"][0]["stops"]] == ["新町"]
    assert sc["removed"] == []


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
    assert lev3[0]["added_stops"] == ["経由地"]
    assert lev3[0]["removed_stops"] == []
    assert len(lev3[0]["systems"]) == 1


def test_level3_merges_directions_with_same_change(tmp_path, config):
    # 上り下りで同じ「S2→S5 置き換え」→ (追加集合, 削除集合) キーで1ユニットに束なる
    stops = MINIMAL_FEED["stops.txt"] + "S5,新経由地,36.011,139.011\n"
    old_files = {
        "stops.txt": stops,
        "trips.txt": BIDIRECTIONAL["trips.txt"],
        "stop_times.txt": BIDIRECTIONAL["stop_times.txt"],
    }
    new_files = {
        "stops.txt": stops,
        "trips.txt": BIDIRECTIONAL["trips.txt"],
        "stop_times.txt": BIDIRECTIONAL["stop_times.txt"].replace(",S2,", ",S5,"),
    }
    model, _ = build(tmp_path, config, old_files=old_files, new_files=new_files)
    page = page_of(model, "1")
    lev3 = page["summary"]["level3"]
    assert len(lev3) == 1  # 上り・下りが1ユニットに
    assert lev3[0]["added_stops"] == ["新経由地"]
    assert lev3[0]["removed_stops"] == ["市役所前"]
    assert len(lev3[0]["systems"]) == 2  # 対象系統の内訳として往復が残る
    assert lev3[0]["coverage"] == 1.0 and lev3[0]["full_coverage"]


def test_timetable_stop_axis_status(tmp_path, config):
    # S2 → S5 置き換え: 軸に両方残り、S2=old_only / S5=new_only / 他=both
    stops = MINIMAL_FEED["stops.txt"] + "S5,新経由地,36.011,139.011\n"
    old_files = {"stops.txt": MINIMAL_FEED["stops.txt"]}
    new_files = {
        "stops.txt": stops.replace(
            "S2,市役所前,36.0100,139.0100\n", ""),  # S2 は新世代に存在しない
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"].replace(",S2,", ",S5,"),
    }
    model, _ = build(tmp_path, config, old_files=old_files, new_files=new_files)
    page = page_of(model, "1")
    tb = page["timetables"][0]
    status = dict(zip(tb["stop_axis"], tb["stop_axis_status"]))
    assert status["駅前"] == "both"
    assert status["市役所前"] == "old_only"
    assert status["新経由地"] == "new_only"


def test_display_pairing_of_removed_added(tmp_path, config):
    # 畑線型: direction_id 付与 + trip_id 変更で厳密署名が組めないが時刻同一 →
    # 表示用ペアリングで1列 (retimed) になり、分単位の変更はゼロ
    old_files = {
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,畑1便 \nR1,WD,畑2便 \n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "畑1便 ,08:00:00,08:00:00,S1,1\n畑1便 ,08:05:00,08:05:00,S2,2\n"
            "畑1便 ,08:10:00,08:10:00,S3,3\n"
            "畑2便 ,09:00:00,09:00:00,S1,1\n畑2便 ,09:05:00,09:05:00,S2,2\n"
            "畑2便 ,09:10:00,09:10:00,S3,3\n"
        ),
    }
    new_files = {
        "trips.txt": ("route_id,service_id,trip_id,direction_id\n"
                      "R1,WD,畑1便,0\nR1,WD,畑2便,0\n"),
        "stop_times.txt": old_files["stop_times.txt"].replace("便 ,", "便,"),
    }
    model, _ = build(tmp_path, config, old_files=old_files, new_files=new_files)
    page = page_of(model, "1")
    cols = [c for tb in page["timetables"] for c in tb["columns"]]
    assert {c["status"] for c in cols} == {"retimed"}  # 廃/新に分裂しない
    assert all(c["changed_positions"] == [] for c in cols)  # 実質無変化


def test_display_pairing_respects_shift_limit(tmp_path, config):
    # 発時刻差が pair_max_shift_min (60分) を超える組は作らない
    new_files = {
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\nR1,WD,TX\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\nT1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
            "TX,12:00:00,12:00:00,S1,1\nTX,12:05:00,12:05:00,S2,2\n"
            "TX,12:10:00,12:10:00,S3,3\n"
        ),
    }
    # 旧 T2 (09:00) は削除、新 TX (12:00) は追加 — 差180分 → 組まない
    model, _ = build(tmp_path, config, new_files=new_files)
    page = page_of(model, "1")
    statuses = sorted(
        c["status"] for tb in page["timetables"] for c in tb["columns"]
    )
    assert statuses == ["added", "removed", "unchanged"]


def test_key_stops_tiers(tmp_path, config):
    # 本線 A-B-C-D-E + C から分岐する区間便 A-B-C-X。別路線 (99) も B を通る →
    # tier1: 起終点 (駅前/病院前) + ハブ判定は hub_min_groups=3 未満なので B は対象外
    # tier2: 分岐点 C (後続 D/X)、区間便端点 X
    files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,駅前,36.00,139.00\nB,二丁目,36.01,139.01\nC,分岐前,36.02,139.02\n"
            "D,四丁目,36.03,139.03\nE,病院前,36.04,139.04\nX,支線終点,36.05,139.00\n"
        ),
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "R1,A1,本線,,3\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,M1\nR1,WD,M2\nR1,WD,B1\nR1,WD,B2\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "M1,08:00:00,08:00:00,A,1\nM1,08:05:00,08:05:00,B,2\nM1,08:10:00,08:10:00,C,3\n"
            "M1,08:15:00,08:15:00,D,4\nM1,08:20:00,08:20:00,E,5\n"
            "M2,10:00:00,10:00:00,A,1\nM2,10:05:00,10:05:00,B,2\nM2,10:10:00,10:10:00,C,3\n"
            "M2,10:15:00,10:15:00,D,4\nM2,10:20:00,10:20:00,E,5\n"
            "B1,09:00:00,09:00:00,A,1\nB1,09:05:00,09:05:00,B,2\nB1,09:10:00,09:10:00,C,3\n"
            "B1,09:15:00,09:15:00,X,4\n"
            "B2,11:00:00,11:00:00,A,1\nB2,11:05:00,11:05:00,B,2\nB2,11:10:00,11:10:00,C,3\n"
            "B2,11:15:00,11:15:00,X,4\n"
        ),
    }
    model, _ = build(tmp_path, config, old_files=files, new_files=files)
    page = page_of(model, "本線")
    keys = page["overview"]["key_stops"]
    assert keys["駅前"] == 1  # canonical 起点
    assert keys["病院前"] <= 2  # 本線パターンの終点 (クラスタ束ね後も拾う)
    assert keys["分岐前"] == 2  # 分岐点 (後続が 四丁目/支線終点)
    assert keys["支線終点"] <= 2  # 区間便パターンの端点
    assert "二丁目" not in keys  # 中間の非分岐停留所は主要でない


def test_level3_includes_display_paired_trips(tmp_path, config):
    # 回帰テスト (汎用性レビューで発見): trip_id が張り替わる経路変更 (removed+added
    # を表示ペアリングで組んだ対) も Lev.3 の影響便数に入ること
    stops = MINIMAL_FEED["stops.txt"] + "S5,新経由地,36.011,139.011\n"
    old_files = {"stops.txt": stops}
    new_files = {
        "stops.txt": stops,
        "trips.txt": MINIMAL_FEED["trips.txt"].replace("T1", "U1").replace("T2", "U2"),
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        .replace("T1", "U1").replace("T2", "U2").replace(",S2,", ",S5,"),
    }
    model, _ = build(tmp_path, config, old_files=old_files, new_files=new_files)
    page = page_of(model, "1")
    lev3 = page["summary"]["level3"]
    assert len(lev3) == 1
    assert lev3[0]["added_stops"] == ["新経由地"]
    assert lev3[0]["removed_stops"] == ["市役所前"]
    assert lev3[0]["affected_trips"] == 2  # ペアリング経由でも全便が影響に数えられる


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


def test_band_matrix_leg_rows_match_timetable_labels(tmp_path, config):
    # R3 改 (07-07): 往復グループでは方向 (leg) 集計行が入り、
    # ラベル・便数が④時刻表の表題と一致する
    model, _ = build(tmp_path, config, old_files=BIDIRECTIONAL, new_files=BIDIRECTIONAL)
    page = page_of(model, "1")
    rows = page["band_matrix"]["rows"]
    legs = [r for r in rows if r["kind"] == "leg"]
    assert [r["label"] for r in legs] == ["駅前 → 病院前", "病院前 → 駅前"]
    # ④の表題と同一ラベル
    assert {r["label"] for r in legs} == {t["label"] for t in page["timetables"]}
    # leg 行の便数 = 対応する時刻表の列数
    by_label = {t["label"]: len(t["columns"]) for t in page["timetables"]}
    for r in legs:
        assert r["total"] == [by_label[r["label"]], by_label[r["label"]]]
    # 方向グループ集計 = leg 集計の和
    agg = next(r for r in rows if r["kind"] == "aggregate")
    assert agg["total"][1] == sum(r["total"][1] for r in legs)


def test_band_matrix_single_direction_has_no_leg_rows(tmp_path, config):
    # 片方向のみのグループでは leg 行は集計行と同じになるため出さない
    model, _ = build(tmp_path, config)
    page = page_of(model, "1")
    assert not [r for r in page["band_matrix"]["rows"] if r["kind"] == "leg"]


def test_day_totals_fixed_order_and_removed_day(tmp_path, config):
    # R18: 曜日タブ用の day_totals。固定順で列挙し、廃止された運行日
    # (old>0, new=0) も残す
    old_files = {
        "calendar.txt": MINIMAL_FEED["calendar.txt"]
        + "SAT,0,0,0,0,0,1,0,20260401,20270331\n",
        "trips.txt": MINIMAL_FEED["trips.txt"] + "R1,SAT,T7\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "T7,10:00:00,10:00:00,S1,1\nT7,10:05:00,10:05:00,S2,2\nT7,10:10:00,10:10:00,S3,3\n",
    }
    model, _ = build(tmp_path, config, old_files=old_files, new_files=None)
    page = page_of(model, "1")
    assert page["day_totals"] == [
        {"day_type": "weekday", "old": 2, "new": 2},
        {"day_type": "saturday", "old": 1, "new": 0},  # 廃止曜日もタブに残る
    ]


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

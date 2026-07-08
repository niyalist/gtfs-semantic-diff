"""route_group (M7) の合成 GTFS 単体テスト。

roadmap M7 DoD: 結合・非結合・語幹衝突 (ストップワード)・低凝集分割 の4ケース以上。
"""

import json

import pytest

from gtfs_semantic_diff.identity import stem_of
from gtfs_semantic_diff.report import render_markdown

from .conftest import MINIMAL_FEED
from .test_rules import events_of, run_compare

# --- 語幹抽出 ---


@pytest.mark.parametrize(
    "name,expected",
    [
        ("30A 前橋玉村線", "前橋玉村線"),
        ("０１　新幹線市街地線", "新幹線市街地線"),  # 全角コードも NFKC で除去
        ("K2-4/M4-1：甲佐行き", "甲佐行き"),
        ("マイバス東循環線", "マイバス東循環線"),  # コードなし → そのまま
        ("A系統", "A系統"),  # 語幹「系統」はストップワード → 元名のまま
        ("17 藤線", "藤線"),  # 2文字語幹は正当
        ("鶴12", "鶴12"),  # 先頭が非コード文字 → 除去しない
    ],
)
def test_stem_of(name, expected, config):
    assert stem_of(name, config) == expected


# --- 結合: 枝番系統が1つの route_group になる ---

# 30A (S1-S2-S3) と 30B (S4-S5): 停留所がほぼ重ならない別コリドー (実データの構図)
BRANCH_FEED = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,駅前,36.0000,139.0000\n"
        "S2,役場,36.0100,139.0100\n"
        "S3,病院前,36.0200,139.0200\n"
        "S4,大学入口,36.1000,139.1000\n"
        "S5,新町駅,36.1100,139.1100\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R30A,A1,30A 玉村線,,3\n"
        "R30B,A1,30B 玉村線,,3\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id\nR30A,WD,TA1\nR30A,WD,TA2\nR30B,WD,TB1\nR30B,WD,TB2\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "TA1,08:00:00,08:00:00,S1,1\nTA1,08:05:00,08:05:00,S2,2\nTA1,08:10:00,08:10:00,S3,3\n"
        "TA2,10:00:00,10:00:00,S1,1\nTA2,10:05:00,10:05:00,S2,2\nTA2,10:10:00,10:10:00,S3,3\n"
        "TB1,09:00:00,09:00:00,S4,1\nTB1,09:10:00,09:10:00,S5,2\n"
        "TB2,11:00:00,11:00:00,S4,1\nTB2,11:10:00,11:10:00,S5,2\n"
    ),
}


def _render(event_set) -> str:
    data = json.loads(json.dumps(event_set.to_dict(), ensure_ascii=False))
    return render_markdown(data)


def test_branch_variants_merge_into_one_group(tmp_path, config):
    # 30B の TB2 を削除 → SERVICE_REDUCED (subject に route_group が付く)
    new_files = dict(BRANCH_FEED)
    new_files["trips.txt"] = BRANCH_FEED["trips.txt"].replace("R30B,WD,TB2\n", "")
    new_files["stop_times.txt"] = "\n".join(
        line for line in BRANCH_FEED["stop_times.txt"].splitlines() if "TB2" not in line
    ) + "\n"
    event_set, _ = run_compare(tmp_path, config, old_files=BRANCH_FEED, new_files=new_files)

    reduced = events_of(event_set, "SERVICE_REDUCED")
    assert len(reduced) == 1
    assert reduced[0].subject["route_family"] == "30B 玉村線"
    assert reduced[0].subject["route_group"] == "玉村線"

    # context: group 構成と低凝集 (別コリドーなので cohesion ≈ 0)
    groups = {g["name"]: g for g in event_set.context["route_groups"]}
    assert groups["玉村線"]["families"] == ["30A 玉村線", "30B 玉村線"]
    assert groups["玉村線"]["cohesion"] < 0.2

    # レポート: 1章に集約され、構成系統と枝線構造注記が出る
    md = _render(event_set)
    assert "### 2.1 玉村線" in md
    assert "構成系統: 30A 玉村線, 30B 玉村線" in md
    assert "枝線構造" in md
    assert "[30B 玉村線] **減便**" in md
    assert "### 2.2" not in md  # 章は1つだけ


def test_different_stems_stay_separate(tmp_path, config):
    # 「鶴12」「鶴120」は語幹が異なる → 別 group
    files = dict(BRANCH_FEED)
    files["routes.txt"] = (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R30A,A1,鶴12,,3\n"
        "R30B,A1,鶴120,,3\n"
    )
    new_files = dict(files)
    new_files["trips.txt"] = files["trips.txt"].replace("R30B,WD,TB2\n", "")
    new_files["stop_times.txt"] = "\n".join(
        line for line in BRANCH_FEED["stop_times.txt"].splitlines() if "TB2" not in line
    ) + "\n"
    event_set, _ = run_compare(tmp_path, config, old_files=files, new_files=new_files)
    reduced = events_of(event_set, "SERVICE_REDUCED")[0]
    assert reduced.subject["route_group"] == "鶴120"
    group_names = {g["name"] for g in event_set.context["route_groups"]}
    assert {"鶴12", "鶴120"} <= group_names


def test_stopword_stem_not_grouped(tmp_path, config):
    # A系統 / B系統 → 語幹「系統」は一般語 → グループ化しない (熊本市電の実例)
    files = dict(BRANCH_FEED)
    files["routes.txt"] = (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R30A,A1,A系統,,3\n"
        "R30B,A1,B系統,,3\n"
    )
    event_set, _ = run_compare(tmp_path, config, old_files=files, new_files=files)
    group_names = {g["name"] for g in event_set.context["route_groups"]}
    assert {"A系統", "B系統"} <= group_names
    assert "系統" not in group_names


def test_low_cohesion_family_structure_subsection(tmp_path, config):
    # 1 family 内に本線 (S1-S2-S3) と区間便 (S3-S4-S5) が同居 (美合線型) →
    # family_structure に載り、レポートに「運行系統の構成」小見出しが出る
    files = {
        "stops.txt": BRANCH_FEED["stops.txt"],
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "R1,A1,美合線,,3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id\nR1,WD,TM1\nR1,WD,TM2\nR1,WD,TK1\nR1,WD,TK2\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "TM1,08:00:00,08:00:00,S1,1\nTM1,08:05:00,08:05:00,S2,2\nTM1,08:10:00,08:10:00,S3,3\n"
            "TM2,10:00:00,10:00:00,S1,1\nTM2,10:05:00,10:05:00,S2,2\nTM2,10:10:00,10:10:00,S3,3\n"
            "TK1,09:00:00,09:00:00,S4,1\nTK1,09:10:00,09:10:00,S5,2\n"
            "TK2,11:00:00,11:00:00,S4,1\nTK2,11:10:00,11:10:00,S5,2\n"
        ),
    }
    # 区間便 TK1 の時刻を 20 分シフト → 美合線にイベントが立つ
    new_files = dict(files)
    new_files["stop_times.txt"] = files["stop_times.txt"].replace(
        "TK1,09:00:00,09:00:00,S4,1\nTK1,09:10:00,09:10:00,S5,2\n",
        "TK1,09:20:00,09:20:00,S4,1\nTK1,09:30:00,09:30:00,S5,2\n",
    )
    event_set, _ = run_compare(tmp_path, config, old_files=files, new_files=new_files)

    structure = {
        s["route_family"]: s for s in event_set.context["family_structure"]
    }
    assert "美合線" in structure
    assert structure["美合線"]["min_cluster_jaccard"] < 0.2
    endpoints = {
        (c["first_stop"], c["last_stop"]) for c in structure["美合線"]["clusters"]
    }
    assert ("駅前", "病院前") in endpoints
    assert ("大学入口", "新町駅") in endpoints

    md = _render(event_set)
    assert "### 2.1 美合線" in md
    assert "運行系統の構成" in md
    assert "駅前 → 病院前 (3停・2便)" in md
    assert "大学入口 → 新町駅 (2停・2便)" in md


def test_single_family_group_degenerates_harmlessly(tmp_path, config):
    # 通常フィード (MINIMAL_FEED): family「1」は単独 group、レポート表示は従来通り
    new_files = {"trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
                 "stop_times.txt": (
                     "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                     "T1,08:00:00,08:00:00,S1,1\n"
                     "T1,08:05:00,08:05:00,S2,2\n"
                     "T1,08:10:00,08:10:00,S3,3\n"
                 )}
    event_set, _ = run_compare(tmp_path, config, new_files=new_files)
    reduced = events_of(event_set, "SERVICE_REDUCED")[0]
    assert reduced.subject["route_group"] == "1"  # 語幹ガード (min_len) で元名のまま
    md = _render(event_set)
    assert "### 2.1 1" in md
    assert "構成系統" not in md  # 単独 family group では出さない
    _ = MINIMAL_FEED  # 明示参照

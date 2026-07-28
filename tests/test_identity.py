"""identity/ (L1 世代間同定) の単体テスト。"""

import pytest

from gtfs_semantic_diff.identity import (
    build_identity,
    build_stop_clusters,
    extract_route_families,
    family_name_of,
    identity_stats,
    normalize_stop_base_name,
    pattern_similarity,
)
from gtfs_semantic_diff.load import load_snapshot

from .conftest import make_gtfs_zip

# --- 基底名正規化 ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("前橋駅", "前橋駅"),
        ("前橋駅 1", "前橋駅"),
        ("前橋駅　②", "前橋駅"),
        ("市役所前のりば", "市役所前"),
        ("センター前A", "センター前"),
        ("1", "1"),  # 全部除去されるケースは元名を保持
    ],
)
def test_normalize_stop_base_name(raw, expected):
    assert normalize_stop_base_name(raw) == expected


def test_family_name_priority():
    assert family_name_of("41号線", "駅前線", "R1") == "41号線"
    assert family_name_of("", "駅前線", "R1") == "駅前線"
    assert family_name_of(" ", "", "R1") == "R1"


# --- パターン類似度 ---


def test_pattern_similarity_identical_and_disjoint(config):
    a = ("駅前", "市役所前", "病院前")
    assert pattern_similarity(a, a, config) == 1.0
    assert pattern_similarity(a, ("空港", "港"), config) < 0.35


def test_pattern_similarity_truncation(config):
    full = ("駅前", "市役所前", "病院前", "団地", "終点")
    truncated = ("駅前", "市役所前", "病院前")
    sim = pattern_similarity(full, truncated, config)
    assert 0.5 <= sim < 1.0  # 同一クラスタに入る程度に高い


# --- 合成フィード: ID 全張り替え (technical churn) でも同定できること ---

OLD_FEED = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,駅前 1,36.0000,139.0000\n"
        "S1b,駅前 2,36.0002,139.0002\n"
        "S2,市役所前,36.0100,139.0100\n"
        "S3,病院前,36.0200,139.0200\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,A1,1,駅前線,3\n"
        "R1x,A1,1,駅前線,3\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id\nR1,WD,T1\nR1x,WD,T2\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T1,08:05:00,08:05:00,S2,2\n"
        "T1,08:10:00,08:10:00,S3,3\n"
        "T2,09:00:00,09:00:00,S1b,1\n"
        "T2,09:05:00,09:05:00,S2,2\n"
        "T2,09:10:00,09:10:00,S3,3\n"
    ),
}

# 新世代: stop_id / route_id / trip_id を全て張り替え、内容は同一
NEW_FEED = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "N1,駅前 1,36.0000,139.0000\n"
        "N1b,駅前 2,36.0002,139.0002\n"
        "N2,市役所前,36.0100,139.0100\n"
        "N3,病院前,36.0200,139.0200\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "Q1,A1,1,駅前線,3\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id\nQ1,HD,U1\nQ1,HD,U2\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "U1,08:00:00,08:00:00,N1,1\n"
        "U1,08:05:00,08:05:00,N2,2\n"
        "U1,08:10:00,08:10:00,N3,3\n"
        "U2,09:00:00,09:00:00,N1b,1\n"
        "U2,09:05:00,09:05:00,N2,2\n"
        "U2,09:10:00,09:10:00,N3,3\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "HD,1,1,1,1,1,0,0,20270401,20280331\n"
    ),
}


@pytest.fixture
def id_churn_snapshots(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, files=OLD_FEED, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FEED, name="new.zip"), config=config)
    return old, new


def test_stop_clusters_merge_platforms(id_churn_snapshots, config):
    old, _ = id_churn_snapshots
    clusters = build_stop_clusters(old, {"R1": "1", "R1x": "1"}, config)
    # 駅前 1 / 駅前 2 は近接 + 同一基底名で1クラスタに
    by_base = {c.base_name: c for c in clusters.values()}
    assert set(by_base) == {"駅前", "市役所前", "病院前"}
    assert sorted(by_base["駅前"].platform_ids) == ["S1", "S1b"]
    assert by_base["市役所前"].route_families == {"1"}


def test_route_families_group_same_name(id_churn_snapshots):
    old, _ = id_churn_snapshots
    families = extract_route_families(old)
    assert set(families) == {"1"}
    assert sorted(families["1"].route_ids) == ["R1", "R1x"]
    assert families["1"].trip_count == 2


def test_identity_survives_full_id_churn(id_churn_snapshots, config):
    old, new = id_churn_snapshots
    result = build_identity(old, new, config)
    stats = identity_stats(result)

    # 全 stop cluster が対応し、名称一致なので confidence は高い
    assert stats["stop_cluster"]["match_rate_old"] == 1.0
    assert stats["stop_cluster"]["match_rate_new"] == 1.0
    # family は名称一致 1本
    assert stats["route_family"]["confidence_hist"]["1.0"] == 1
    # パターンクラスタも1対1対応
    assert stats["pattern_cluster"]["match_rate_old"] == 1.0
    # day_type: 旧 WD=weekday, 新 HD=weekday → service エッジ1本
    assert stats["service"]["edges"] == 1

    # stop エッジの世代間ペアが正しい (駅前↔駅前 など基底名同士)
    for e in result.graph.for_type("stop_cluster"):
        old_base = result.old_stop_clusters[e.old_id].base_name
        new_base = result.new_stop_clusters[e.new_id].base_name
        if e.confidence >= 0.5:
            assert old_base == new_base


def test_renamed_family_linked_by_content(tmp_path, config):
    # 路線名変更 (1 → 100): 名称不一致だが停留所集合同一 → 内容主導エッジ (M9)
    renamed = dict(NEW_FEED)
    renamed["routes.txt"] = (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "Q1,A1,100,駅前線,3\n"
    )
    old = load_snapshot(make_gtfs_zip(tmp_path, files=OLD_FEED, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=renamed, name="new.zip"), config=config)
    result = build_identity(old, new, config)
    family_edges = result.graph.for_type("route_family")
    assert len(family_edges) == 1
    edge = family_edges[0]
    assert (edge.old_id, edge.new_id, edge.method) == ("1", "100", "stops_translated")
    assert edge.confidence == 1.0  # 停留所集合が完全一致
    assert result.family_components == [
        {"old": ["1"], "new": ["100"], "shape": "renamed",
         "similarity": 1.0, "demoted": False, "pruned": False}
    ]


def test_pattern_cluster_separates_dissimilar(tmp_path, config):
    # 同一 family 内の全く異なる2パターン → 別クラスタ
    feed = dict(OLD_FEED)
    feed["stops.txt"] = OLD_FEED["stops.txt"] + "S9,山奥,36.5000,139.5000\nS10,峠,36.5100,139.5100\n"
    feed["trips.txt"] = "route_id,service_id,trip_id\nR1,WD,T1\nR1,WD,T3\n"
    feed["stop_times.txt"] = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T1,08:05:00,08:05:00,S2,2\n"
        "T1,08:10:00,08:10:00,S3,3\n"
        "T3,10:00:00,10:00:00,S9,1\n"
        "T3,10:30:00,10:30:00,S10,2\n"
    )
    snap = load_snapshot(make_gtfs_zip(tmp_path, files=feed, name="f.zip"), config=config)
    result = build_identity(snap, snap, config)
    assert len(result.old_pattern_clusters) == 2
    # 自己比較なので全エンティティが完全対応
    stats = identity_stats(result)
    assert stats["pattern_cluster"]["match_rate_old"] == 1.0


# --- 同点証拠階層 (orientation.md §3、2026-07-28) ---


def _edge(old, new, conf):
    from gtfs_semantic_diff.model import MatchEdge
    from gtfs_semantic_diff.model.matchgraph import ENTITY_ROUTE_FAMILY

    return MatchEdge(entity_type=ENTITY_ROUTE_FAMILY, old_id=old, new_id=new,
                     confidence=conf, method="stops_translated")


def test_sequence_agreement_orientation():
    from gtfs_semantic_diff.identity.route_family import sequence_agreement

    fwd = ("A", "B", "C", "D")
    assert sequence_agreement(fwd, fwd) == 1.0
    assert sequence_agreement(fwd, tuple(reversed(fwd))) == 0.0
    assert sequence_agreement(fwd, ("X", "Y")) == 0.5  # 共通2停未満は中立


def test_rank_tied_new_orientation_wins():
    """層2: 集合が同一でも、向き (系列の順序) が一致する候補が勝つ。

    ラケット (往路/復路が別 family) の類似度1.0同点を正しく割る。"""
    from gtfs_semantic_diff.identity.route_family import rank_tied_new

    fwd = ("A", "B", "C", "D")
    rev = tuple(reversed(fwd))
    ranked = rank_tied_new("旧往路", ["新復路", "新往路"], fwd,
                           {"新往路": fwd, "新復路": rev}, set())
    assert ranked[0] == "新往路"


def test_rank_tied_new_name_layer():
    """層3: 向きで割れないとき、名称類似が交差改称を防ぐ。"""
    from gtfs_semantic_diff.identity.route_family import rank_tied_new

    seq = ("A", "B", "C")
    ranked = rank_tied_new("西３Ｄ復路", ["特西４Ｄ復路新", "西３Ｄ復路新"], seq,
                          {"特西４Ｄ復路新": seq, "西３Ｄ復路新": seq}, set())
    assert ranked[0] == "西３Ｄ復路新"


def test_rank_tied_new_prefers_unused():
    """層4: 向きも名称も同点なら、未使用の新 family を優先 (説明の最大化)。"""
    from gtfs_semantic_diff.identity.route_family import rank_tied_new

    ranked = rank_tied_new("X", ["N1", "N2"], (), {}, {"N1"})
    assert ranked[0] == "N2"
    # 未使用がなければ辞書順 (決定性)
    ranked = rank_tied_new("X", ["N1", "N2"], (), {}, {"N1", "N2"})
    assert ranked[0] == "N1"


def test_component_pruning_tie_splits_racket_pair():
    """段階1間引き: 類似度1.0×4 の 2×2 (ラケット対) は向きで 1:1+1:1 に割れる。

    旧タイブレーク (辞書順) は旧2 family を同一の新 family に吸わせ、
    片割れを偽の新設に落としていた (京都 西系の実例)。"""
    from gtfs_semantic_diff.identity.route_family import (
        classify_family_components)

    fwd = ("A", "B", "C", "D")
    rev = tuple(reversed(fwd))
    edges = [
        _edge("旧往路", "新往路", 1.0), _edge("旧往路", "新復路", 1.0),
        _edge("旧復路", "新往路", 1.0), _edge("旧復路", "新復路", 1.0),
    ]
    # 各 family を別 group にして max_groups=1 で間引きを強制発動
    f2g = {f: f for f in ("旧往路", "旧復路", "新往路", "新復路")}
    comps, _ = classify_family_components(
        edges, f2g, f2g, max_groups=1,
        old_seqs={"旧往路": fwd, "旧復路": rev},
        new_seqs={"新往路": fwd, "新復路": rev},
    )
    shapes = sorted((tuple(c["old"]), tuple(c["new"]), c["shape"]) for c in comps)
    assert shapes == [
        (("旧往路",), ("新往路",), "renamed"),
        (("旧復路",), ("新復路",), "renamed"),
    ]


def test_page_maps_tie_rescues_unmatched_new(tmp_path, config):
    """ページ割付: 同点タイで旧2 family が同一ページに吸われない。"""
    from gtfs_semantic_diff.identity import IdentityResult
    from gtfs_semantic_diff.identity.builder import page_family_maps
    from gtfs_semantic_diff.model import MatchGraph

    fwd = ("A", "B", "C", "D")
    rev = tuple(reversed(fwd))
    ident = IdentityResult(
        old_family_to_group={"旧往路": "旧往路", "旧復路": "旧復路"},
        new_family_to_group={"新往路": "新往路", "新復路": "新復路"},
        old_family_seq={"旧往路": fwd, "旧復路": rev},
        new_family_seq={"新往路": fwd, "新復路": rev},
        graph=MatchGraph(edges=[
            _edge("旧往路", "新往路", 1.0), _edge("旧往路", "新復路", 1.0),
            _edge("旧復路", "新往路", 1.0), _edge("旧復路", "新復路", 1.0),
        ]),
    )
    old_map, _ = page_family_maps(ident)
    assert old_map == {"旧往路": "新往路", "旧復路": "新復路"}

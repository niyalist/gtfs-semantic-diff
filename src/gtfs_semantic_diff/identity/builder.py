"""L1 オーケストレーション: GtfsSnapshot 2つ → IdentityResult (MatchGraph + 中間成果物)。

カスケード順 (docs/design/ontology.md):
  route family 抽出 → stop クラスタリング (family 接続を利用)
  → パターン抽出 (stop 基底名を利用) → family リンク (パターン Jaccard を利用)
  → パターンクラスタリンク → service (day_type) リンク
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Config
from ..model import GtfsSnapshot, MatchEdge, MatchGraph
from ..model.matchgraph import (
    ENTITY_PATTERN_CLUSTER,
    ENTITY_ROUTE_FAMILY,
    ENTITY_SERVICE,
    ENTITY_STOP_CLUSTER,
)
from .pattern_clustering import (
    PatternCluster,
    cluster_patterns,
    extract_patterns,
    link_pattern_clusters,
)
from .route_family import (
    METHOD_CONTENT,
    METHOD_NAME,
    RouteFamily,
    build_stop_translation,
    classify_family_components,
    extract_route_families,
    link_route_families,
    route_to_family_map,
)
from .route_group import RouteGroup, build_route_groups
from .stop_clustering import StopCluster, build_stop_clusters, link_stop_clusters

logger = logging.getLogger(__name__)


@dataclass
class IdentityResult:
    """L1 の全成果物。graph が MatchGraph 本体、他は下流ルールが参照する中間物。"""

    old_stop_clusters: dict[str, StopCluster] = field(default_factory=dict)
    new_stop_clusters: dict[str, StopCluster] = field(default_factory=dict)
    old_families: dict[str, RouteFamily] = field(default_factory=dict)
    new_families: dict[str, RouteFamily] = field(default_factory=dict)
    old_pattern_clusters: list[PatternCluster] = field(default_factory=list)
    new_pattern_clusters: list[PatternCluster] = field(default_factory=list)
    old_day_types: set[str] = field(default_factory=set)
    new_day_types: set[str] = field(default_factory=set)
    old_groups: list[RouteGroup] = field(default_factory=list)
    new_groups: list[RouteGroup] = field(default_factory=list)
    old_family_to_group: dict[str, str] = field(default_factory=dict)
    new_family_to_group: dict[str, str] = field(default_factory=dict)
    # M9: family 世代間対応の連結成分 (内容エッジを含むもののみ)。
    # {"old": [...], "new": [...], "shape": renamed|merged|split|restructured,
    #  "similarity": float, "demoted": bool}
    family_components: list[dict] = field(default_factory=list)
    # 同点証拠階層 (orientation.md §3) 用: family → 代表停車列 (最長パターン)
    old_family_seq: dict[str, tuple[str, ...]] = field(default_factory=dict)
    new_family_seq: dict[str, tuple[str, ...]] = field(default_factory=dict)
    graph: MatchGraph = field(default_factory=MatchGraph)


def build_identity(old: GtfsSnapshot, new: GtfsSnapshot, config: Config) -> IdentityResult:
    """世代間同定を実行し MatchGraph を構築する。"""
    old_families = extract_route_families(old)
    new_families = extract_route_families(new)
    old_r2f = route_to_family_map(old_families)
    new_r2f = route_to_family_map(new_families)

    old_stops = build_stop_clusters(old, old_r2f, config)
    new_stops = build_stop_clusters(new, new_r2f, config)
    stop_edges = link_stop_clusters(old_stops, new_stops, config)

    old_stop_to_base = {
        pid: c.base_name for c in old_stops.values() for pid in c.platform_ids
    }
    new_stop_to_base = {
        pid: c.base_name for c in new_stops.values() for pid in c.platform_ids
    }
    old_patterns = extract_patterns(old, old_r2f, old_stop_to_base)
    new_patterns = extract_patterns(new, new_r2f, new_stop_to_base)
    old_family_stops: dict[str, set[str]] = {name: set() for name in old_families}
    new_family_stops: dict[str, set[str]] = {name: set() for name in new_families}
    for p in old_patterns:
        old_families[p.family].pattern_keys.add(p.pattern_key)
        old_family_stops[p.family].update(p.base_names)
    for p in new_patterns:
        new_families[p.family].pattern_keys.add(p.pattern_key)
        new_family_stops[p.family].update(p.base_names)

    old_f2g, old_groups = build_route_groups(old_family_stops, config)
    new_f2g, new_groups = build_route_groups(new_family_stops, config)

    # M9: 内容主導 linking。停留所クラスタの世代間対応で旧基底名を新側へ
    # 翻訳してから家族の停留所集合を比較する (停留所改称との共倒れ防止)
    stop_link_min = config.get(
        "identity", "route_family", "stop_link_min", default=0.5
    )
    translation = build_stop_translation(
        old_stops, new_stops, stop_edges, stop_link_min
    )
    family_edges = link_route_families(
        old_families, new_families, config,
        old_family_stops=old_family_stops,
        new_family_stops=new_family_stops,
        stop_translation=translation,
    )
    # 同点証拠階層 (orientation.md §3.1) の代表停車列: family の最長パターン
    # (同長は列の辞書順で決定的に)。集合 Jaccard が潰す方向情報の回復用
    def rep_seqs(patterns) -> dict[str, tuple[str, ...]]:
        rep: dict[str, tuple[str, ...]] = {}
        for p in patterns:
            cur = rep.get(p.family)
            cand = tuple(p.base_names)
            if cur is None or (len(cand), cand) > (len(cur), cur):
                rep[p.family] = cand
        return rep

    old_family_seq = rep_seqs(old_patterns)
    new_family_seq = rep_seqs(new_patterns)

    max_groups = config.get(
        "identity", "route_family", "max_component_groups", default=6
    )
    family_components, family_edges = classify_family_components(
        family_edges, old_f2g, new_f2g, max_groups,
        old_seqs=old_family_seq, new_seqs=new_family_seq,
    )

    old_pcs = cluster_patterns(old_patterns, config)
    new_pcs = cluster_patterns(new_patterns, config)
    pattern_edges = link_pattern_clusters(old_pcs, new_pcs, family_edges, config)

    service_edges = [
        MatchEdge(
            entity_type=ENTITY_SERVICE,
            old_id=day_type,
            new_id=day_type,
            confidence=1.0,
            method="day_type",
        )
        for day_type in sorted(set(old.day_types.values()) & set(new.day_types.values()))
    ]

    graph = MatchGraph(edges=stop_edges + family_edges + pattern_edges + service_edges)
    logger.info("MatchGraph: エッジ %d 本", len(graph.edges))
    return IdentityResult(
        old_stop_clusters=old_stops,
        new_stop_clusters=new_stops,
        old_families=old_families,
        new_families=new_families,
        old_pattern_clusters=old_pcs,
        new_pattern_clusters=new_pcs,
        old_day_types=set(old.day_types.values()),
        new_day_types=set(new.day_types.values()),
        old_groups=old_groups,
        new_groups=new_groups,
        old_family_to_group=old_f2g,
        new_family_to_group=new_f2g,
        family_components=family_components,
        old_family_seq=old_family_seq,
        new_family_seq=new_family_seq,
        graph=graph,
    )


def blocking_family_maps(identity: IdentityResult) -> tuple[dict, dict]:
    """trip matching のブロック用: family → ブロック名 (旧新の group を成分で束ねる)。

    受理エッジ (名称一致 + 内容) の連結成分で route_group を union し、
    正準名 = 成分内の辞書順最小の group 名。ブロックは広めでも安全
    (precision は対ごとの内容ゲートが守る、trip_matching.md §3.1)。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    o_f2g, n_f2g = identity.old_family_to_group, identity.new_family_to_group
    for e in identity.graph.for_type(ENTITY_ROUTE_FAMILY):
        if e.method in (METHOD_NAME, METHOD_CONTENT):
            union(o_f2g.get(e.old_id, e.old_id), n_f2g.get(e.new_id, e.new_id))
    old_map = {f: find(g) for f, g in o_f2g.items()}
    new_map = {f: find(g) for f, g in n_f2g.items()}
    return old_map, new_map


def page_family_maps(identity: IdentityResult) -> tuple[dict, dict]:
    """レポートのページ用: family → ページ group 名 (新世代を背骨に)。

    - 新 family → 自身の新 group (ページ数は新世代の group 数で抑えられる)
    - 旧 family → 最良の受理エッジ (confidence 最大、**同点は同点証拠階層**
      rank_tied_new — 向き→名称類似→未使用優先→辞書順、orientation.md §3)
      の相手が属する新 group。受理エッジが無ければ自身の旧 group
      (廃止ページ)。1:N 分割でも旧 family の trips は1ページにのみ載る
      (もう一方の新ページには注記だけ、route_identity_review.md §3.3.1)。
      旧タイブレーク (辞書順のみ) は連続運行対で旧2 family を同一ページに
      吸わせていた (京都 20系、2026-07-28 改訂)
    """
    from .route_family import rank_tied_new

    o_f2g, n_f2g = identity.old_family_to_group, identity.new_family_to_group
    by_old: dict[str, list] = {}
    for e in identity.graph.for_type(ENTITY_ROUTE_FAMILY):
        if e.method in (METHOD_NAME, METHOD_CONTENT):
            by_old.setdefault(e.old_id, []).append(e)
    best: dict[str, str] = {}
    used_new: set[str] = set()
    for old_id in sorted(
        by_old, key=lambda f: (-max(e.confidence for e in by_old[f]), f)
    ):
        es = by_old[old_id]
        mx = max(e.confidence for e in es)
        tied = sorted({e.new_id for e in es if e.confidence == mx})
        pick = rank_tied_new(
            old_id, tied, identity.old_family_seq.get(old_id, ()),
            identity.new_family_seq, used_new,
        )[0]
        best[old_id] = pick
        used_new.add(pick)
    old_map = {
        f: (n_f2g.get(best[f], best[f]) if f in best else g)
        for f, g in o_f2g.items()
    }
    return old_map, dict(n_f2g)


def identity_stats(result: IdentityResult) -> dict:
    """対応率と confidence 分布 (検証ログ・コンソール表示用)。"""

    def entity_stats(entity_type: str, old_ids: list[str], new_ids: list[str]) -> dict:
        edges = result.graph.for_type(entity_type)
        best_by_old: dict[str, float] = {}
        matched_new: set[str] = set()
        for e in edges:
            if e.confidence > best_by_old.get(e.old_id, -1.0):
                best_by_old[e.old_id] = e.confidence
            matched_new.add(e.new_id)
        hist = {"1.0": 0, "0.75-1.0": 0, "0.5-0.75": 0, "<0.5": 0}
        for c in best_by_old.values():
            if c >= 1.0:
                hist["1.0"] += 1
            elif c >= 0.75:
                hist["0.75-1.0"] += 1
            elif c >= 0.5:
                hist["0.5-0.75"] += 1
            else:
                hist["<0.5"] += 1
        return {
            "old_count": len(old_ids),
            "new_count": len(new_ids),
            "edges": len(edges),
            "matched_old": len(best_by_old),
            "matched_new": len(matched_new),
            "match_rate_old": round(len(best_by_old) / len(old_ids), 4) if old_ids else 1.0,
            "match_rate_new": round(len(matched_new) / len(new_ids), 4) if new_ids else 1.0,
            "confidence_hist": hist,
        }

    return {
        "stop_cluster": entity_stats(
            ENTITY_STOP_CLUSTER,
            list(result.old_stop_clusters),
            list(result.new_stop_clusters),
        ),
        "route_family": entity_stats(
            ENTITY_ROUTE_FAMILY, list(result.old_families), list(result.new_families)
        ),
        "pattern_cluster": entity_stats(
            ENTITY_PATTERN_CLUSTER,
            [c.cluster_id for c in result.old_pattern_clusters],
            [c.cluster_id for c in result.new_pattern_clusters],
        ),
        "service": entity_stats(
            ENTITY_SERVICE, sorted(result.old_day_types), sorted(result.new_day_types)
        ),
    }

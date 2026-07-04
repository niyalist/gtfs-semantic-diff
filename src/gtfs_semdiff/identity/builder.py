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
    RouteFamily,
    extract_route_families,
    link_route_families,
    route_to_family_map,
)
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
    for p in old_patterns:
        old_families[p.family].pattern_keys.add(p.pattern_key)
    for p in new_patterns:
        new_families[p.family].pattern_keys.add(p.pattern_key)

    family_edges = link_route_families(old_families, new_families, config)

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
        graph=graph,
    )


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

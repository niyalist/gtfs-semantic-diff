"""Route Family 抽出 (旧 route_analyzer.py の Family 抽出部のみを移植)。

Route Family = 利用者が認識する「路線」。route_id は世代間で張り替わるため
(例: "101_1_1" → "101_1_2")、乗客向け名称でグループ化する。

名称の優先順: route_short_name → route_long_name → route_id。
正規化・あいまい一致は行わない (決定的挙動を優先、旧実装の設計判断を踏襲)。
名称が変わった family の対応 (ROUTE_RENAMED 候補) は、所属パターン集合の
Jaccard 類似度による低 confidence エッジとして保持する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Config
from ..model import GtfsSnapshot, MatchEdge
from ..model.matchgraph import ENTITY_ROUTE_FAMILY

logger = logging.getLogger(__name__)


@dataclass
class RouteFamily:
    """同一名称の route_id 群。"""

    name: str
    route_ids: list[str] = field(default_factory=list)
    trip_count: int = 0
    # 所属する停車パターンのハッシュ集合 (基底名列ベース、pattern_clustering が設定)
    pattern_keys: set[str] = field(default_factory=set)


def family_name_of(short_name: str, long_name: str, route_id: str) -> str:
    """route の表示名 (family キー) を決める。"""
    short = short_name.strip()
    if short:
        return short
    long_ = long_name.strip()
    if long_:
        return long_
    return route_id.strip()


def extract_route_families(snapshot: GtfsSnapshot) -> dict[str, RouteFamily]:
    """routes.txt から family 名 → RouteFamily を作る。"""
    routes = snapshot.table("routes")
    if routes is None or routes.empty:
        return {}
    short_col = routes["route_short_name"] if "route_short_name" in routes.columns else ""
    long_col = routes["route_long_name"] if "route_long_name" in routes.columns else ""

    families: dict[str, RouteFamily] = {}
    for i, route_id in enumerate(routes["route_id"]):
        short = short_col.iloc[i] if hasattr(short_col, "iloc") else ""
        long_ = long_col.iloc[i] if hasattr(long_col, "iloc") else ""
        name = family_name_of(short, long_, route_id)
        family = families.setdefault(name, RouteFamily(name=name))
        family.route_ids.append(route_id)

    trips = snapshot.table("trips")
    if trips is not None and not trips.empty:
        route_to_family = route_to_family_map(families)
        for route_id in trips["route_id"]:
            name = route_to_family.get(route_id)
            if name:
                families[name].trip_count += 1

    logger.info(
        "%s: routes %d 件 → family %d 件",
        snapshot.meta.label(),
        len(routes),
        len(families),
    )
    return families


def route_to_family_map(families: dict[str, RouteFamily]) -> dict[str, str]:
    """route_id → family 名の逆引き。"""
    return {rid: f.name for f in families.values() for rid in f.route_ids}


def link_route_families(
    old_families: dict[str, RouteFamily],
    new_families: dict[str, RouteFamily],
    config: Config,
) -> list[MatchEdge]:
    """family の世代間対応。名称一致は confidence 1.0、
    不一致分はパターン集合 Jaccard による仮説エッジ (link_floor 以上) を保持。"""
    link_floor = config.get("identity", "route_family", "link_floor", default=0.3)
    edges: list[MatchEdge] = []

    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for name in sorted(old_families.keys() & new_families.keys()):
        edges.append(
            MatchEdge(
                entity_type=ENTITY_ROUTE_FAMILY,
                old_id=name,
                new_id=name,
                confidence=1.0,
                method="name_exact",
            )
        )
        matched_old.add(name)
        matched_new.add(name)

    # 名称不一致の family: パターン集合の Jaccard で RENAMED 候補を残す
    for old_name in sorted(old_families.keys() - matched_old):
        old_keys = old_families[old_name].pattern_keys
        if not old_keys:
            continue
        for new_name in sorted(new_families.keys() - matched_new):
            new_keys = new_families[new_name].pattern_keys
            if not new_keys:
                continue
            jaccard = len(old_keys & new_keys) / len(old_keys | new_keys)
            if jaccard >= link_floor:
                edges.append(
                    MatchEdge(
                        entity_type=ENTITY_ROUTE_FAMILY,
                        old_id=old_name,
                        new_id=new_name,
                        confidence=round(jaccard, 4),
                        method="pattern_jaccard",
                    )
                )
    logger.info(
        "route family link: old %d / new %d → 名称一致 %d + 仮説 %d",
        len(old_families),
        len(new_families),
        len(matched_old),
        len(edges) - len(matched_old),
    )
    return edges

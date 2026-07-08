"""2段階 Stop Clustering (旧 stop_analyzer.py の移植)。

段階1 (世代内名寄せ): parent_station があればそれで束ね、なければ
  「のりば表記を除いた基底名 + 近接 (intra_generation_radius_m)」で
  プラットフォーム (stop_id) を物理停留所クラスタにまとめる。
段階2 (世代間リンク): クラスタ同士を
  プラットフォーム共有率 / 接続 route family 集合の Jaccard /
  距離 / 名称類似度 の重み付きスコアで対応付け、confidence 付き
  MatchEdge として全仮説を保持する (貪欲な早期確定はしない)。

route_id は世代間で張り替わるため、路線接続の比較には route family 名を使う。
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..config import Config
from ..model import GtfsSnapshot, MatchEdge
from ..model.matchgraph import ENTITY_STOP_CLUSTER

logger = logging.getLogger(__name__)

# のりば・乗り場表記の除去対象 (基底名の正規化)
_PLATFORM_INDICATORS = [
    "のりば", "乗り場", "乗場", "ホーム", "番線",
    "A", "B", "C", "D", "E", "F",
    "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨",
    "１", "２", "３", "４", "５", "６", "７", "８", "９",
]


@dataclass
class StopCluster:
    """物理停留所1つ (プラットフォーム群の集合)。"""

    cluster_id: str
    name: str  # 代表表示名 (最頻の stop_name)
    base_name: str  # 正規化済み基底名
    lat: float
    lon: float
    platform_ids: list[str] = field(default_factory=list)
    route_families: set[str] = field(default_factory=set)  # 接続する route family 名


def normalize_stop_base_name(name: str) -> str:
    """stop_name からのりば表記を除いた基底名を返す。"""
    base = name.strip()
    changed = True
    while changed:
        changed = False
        for indicator in _PLATFORM_INDICATORS:
            for pattern in (indicator, " " + indicator, "　" + indicator):
                if len(base) > len(pattern) and base.endswith(pattern):
                    base = base[: -len(pattern)].strip()
                    changed = True
    return base or name.strip()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の距離 (メートル)。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _stop_route_families(
    snapshot: GtfsSnapshot, route_to_family: dict[str, str]
) -> dict[str, set[str]]:
    """stop_id → その停留所に停車する route family 名の集合。"""
    trips = snapshot.table("trips")
    stop_times = snapshot.table("stop_times")
    if trips is None or stop_times is None:
        return {}
    trip_to_family = {
        t: route_to_family.get(r, "")
        for t, r in zip(trips["trip_id"], trips["route_id"])
    }
    result: dict[str, set[str]] = defaultdict(set)
    for trip_id, stop_id in zip(stop_times["trip_id"], stop_times["stop_id"]):
        family = trip_to_family.get(trip_id)
        if family:
            result[stop_id].add(family)
    return result


def build_stop_clusters(
    snapshot: GtfsSnapshot,
    route_to_family: dict[str, str],
    config: Config,
) -> dict[str, StopCluster]:
    """段階1: 世代内のプラットフォームを物理停留所クラスタにまとめる。"""
    stops = snapshot.table("stops")
    if stops is None or stops.empty:
        return {}
    radius = config.get("identity", "stop_clustering", "intra_generation_radius_m", default=100)
    stop_families = _stop_route_families(snapshot, route_to_family)

    has_location_type = "location_type" in stops.columns
    has_parent = "parent_station" in stops.columns

    clusters: dict[str, StopCluster] = {}
    # 基底名 → クラスタ ID 群 (近接判定の候補絞り込み)
    by_base_name: dict[str, list[str]] = defaultdict(list)

    def coord(row) -> tuple[float, float]:
        try:
            return float(row["stop_lat"]), float(row["stop_lon"])
        except (ValueError, KeyError):
            return (0.0, 0.0)

    # parent_station (location_type=1) を先にクラスタとして登録
    if has_location_type:
        parents = stops[stops["location_type"].str.strip() == "1"]
        for _, row in parents.iterrows():
            lat, lon = coord(row)
            cid = f"parent:{row['stop_id']}"
            clusters[cid] = StopCluster(
                cluster_id=cid,
                name=row["stop_name"],
                base_name=normalize_stop_base_name(row["stop_name"]),
                lat=lat,
                lon=lon,
            )

    boarding = stops
    if has_location_type:
        lt = stops["location_type"].str.strip()
        boarding = stops[(lt == "") | (lt == "0")]

    # stop_id 順で決定的に処理
    for _, row in boarding.sort_values("stop_id").iterrows():
        stop_id = row["stop_id"]
        name = row["stop_name"]
        lat, lon = coord(row)
        parent = row["parent_station"].strip() if has_parent else ""

        if parent and f"parent:{parent}" in clusters:
            cluster = clusters[f"parent:{parent}"]
        else:
            base = normalize_stop_base_name(name)
            cluster = None
            for cid in by_base_name[base]:
                cand = clusters[cid]
                if haversine_m(cand.lat, cand.lon, lat, lon) <= radius:
                    cluster = cand
                    break
            if cluster is None:
                cid = f"{base}#{len(by_base_name[base])}"
                cluster = StopCluster(
                    cluster_id=cid, name=name, base_name=base, lat=lat, lon=lon
                )
                clusters[cid] = cluster
                by_base_name[base].append(cid)

        cluster.platform_ids.append(stop_id)
        cluster.route_families |= stop_families.get(stop_id, set())

    # 代表座標をプラットフォーム重心に更新はせず先着座標のまま (決定性優先・半径が小さいため実害なし)
    result = {cid: c for cid, c in clusters.items() if c.platform_ids}
    logger.info(
        "%s: stops %d 件 → クラスタ %d 件", snapshot.meta.label(), len(stops), len(result)
    )
    return result


def link_stop_clusters(
    old_clusters: dict[str, StopCluster],
    new_clusters: dict[str, StopCluster],
    config: Config,
) -> list[MatchEdge]:
    """段階2: 世代間のクラスタ対応仮説を confidence 付きで列挙する。"""
    sc = lambda *keys, d=None: config.get("identity", "stop_clustering", *keys, default=d)  # noqa: E731
    inter_radius = sc("inter_generation_radius_m", d=300)
    link_floor = sc("link_floor", d=0.25)
    w_platform = sc("weight_shared_platform", d=0.35)
    w_route = sc("weight_route_similarity", d=0.25)
    w_dist = sc("weight_distance", d=0.25)
    w_name = sc("weight_name_similarity", d=0.15)

    # 空間グリッドで候補を絞る (セル幅 ≈ inter_radius)
    cell_deg = inter_radius / 111000.0
    grid: dict[tuple[int, int], list[StopCluster]] = defaultdict(list)
    for c in new_clusters.values():
        grid[(int(c.lat / cell_deg), int(c.lon / cell_deg))].append(c)

    # プラットフォーム (stop_id) を共有するクラスタは距離に関係なく候補に含める。
    # 同一 stop_id のまま inter_radius を超えて移設されるケース (実データで確認) のため。
    new_by_platform: dict[str, StopCluster] = {}
    for c in new_clusters.values():
        for pid in c.platform_ids:
            new_by_platform[pid] = c

    edges: list[MatchEdge] = []
    for old in old_clusters.values():
        ci, cj = int(old.lat / cell_deg), int(old.lon / cell_deg)
        candidates = {
            c.cluster_id: c
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            for c in grid.get((ci + di, cj + dj), ())
        }
        for pid in old.platform_ids:
            shared = new_by_platform.get(pid)
            if shared is not None:
                candidates[shared.cluster_id] = shared
        for new in candidates.values():
            dist = haversine_m(old.lat, old.lon, new.lat, new.lon)
            has_shared_platform = bool(set(old.platform_ids) & set(new.platform_ids))
            if dist > inter_radius and not has_shared_platform:
                continue
            shared = len(set(old.platform_ids) & set(new.platform_ids))
            platform_ratio = shared / max(len(old.platform_ids), len(new.platform_ids))
            union_families = old.route_families | new.route_families
            route_sim = (
                len(old.route_families & new.route_families) / len(union_families)
                if union_families
                else 0.0
            )
            dist_score = max(0.0, 1.0 - dist / inter_radius)
            name_sim = SequenceMatcher(None, old.base_name, new.base_name).ratio()

            score = (
                w_platform * platform_ratio
                + w_route * route_sim
                + w_dist * dist_score
                + w_name * name_sim
            )
            if score < link_floor:
                continue
            method = "name_exact" if old.base_name == new.base_name else "composite"
            edges.append(
                MatchEdge(
                    entity_type=ENTITY_STOP_CLUSTER,
                    old_id=old.cluster_id,
                    new_id=new.cluster_id,
                    confidence=round(min(1.0, score), 4),
                    method=method,
                )
            )
    logger.info(
        "stop cluster link: old %d / new %d → エッジ %d 本",
        len(old_clusters),
        len(new_clusters),
        len(edges),
    )
    return edges

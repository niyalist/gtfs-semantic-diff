"""停車パターンの類似度クラスタリング (旧 pattern_clustering.py の移植)。

移植時の変更 (docs/PORTING.md):
- debug_routes ハードコード・print/Rich 出力を除去 (logging へ)
- 類似度の重み・閾値を config/default.toml [identity.pattern_clustering] へ
- パターン列は stop_id ではなく「停留所クラスタの基底名」の列で表現する。
  stop_id は世代間で張り替わるため、世代間比較を可能にするのが目的
  (カスケード順: stop 同定 → パターン照合、の依存関係がここに現れる)。

類似度 = lcs_weight * LCS類似 + direction_weight * 順序整合 + containment_weight * 包含。
クラスタリングは類似度 ≥ similarity_threshold の連結成分。
パターン数が hierarchical_switch_patterns を超える場合は
(始点, 終点, 長さバケット) で予備グループ化してから成分分解する (O(patterns²) 回避)。
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from ..config import Config
from ..model import GtfsSnapshot, MatchEdge
from ..model.matchgraph import ENTITY_PATTERN_CLUSTER

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StopPattern:
    """family × 方向 内の一意な停車パターン。"""

    pattern_id: str
    family: str
    direction: str  # trips.direction_id ("" 可)
    base_names: tuple[str, ...]  # 停留所クラスタ基底名の列 (世代間比較の共通語彙)
    display_names: tuple[str, ...]  # 表示用 stop_name の列
    trip_count: int

    @property
    def pattern_key(self) -> str:
        """基底名列のダイジェスト。family の pattern_keys (Jaccard 比較) に使う。"""
        joined = "\x1f".join(self.base_names)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


@dataclass
class PatternCluster:
    """類似パターンの束 (subject: family × 方向 × クラスタ)。"""

    cluster_id: str
    family: str
    direction: str
    representative: StopPattern
    patterns: list[StopPattern] = field(default_factory=list)

    @property
    def trip_count(self) -> int:
        return sum(p.trip_count for p in self.patterns)


# --- パターン抽出 ---


def extract_patterns(
    snapshot: GtfsSnapshot,
    route_to_family: dict[str, str],
    stop_to_base: dict[str, str],
) -> list[StopPattern]:
    """trips + stop_times から family × 方向ごとの一意パターンを列挙する。"""
    trips = snapshot.table("trips")
    stop_times = snapshot.table("stop_times")
    stops = snapshot.table("stops")
    if trips is None or stop_times is None or stop_times.empty:
        return []

    stop_names = (
        dict(zip(stops["stop_id"], stops["stop_name"])) if stops is not None else {}
    )
    direction_col = (
        trips["direction_id"] if "direction_id" in trips.columns else [""] * len(trips)
    )
    trip_meta = {
        trip_id: (route_to_family.get(route_id, ""), str(direction).strip())
        for trip_id, route_id, direction in zip(
            trips["trip_id"], trips["route_id"], direction_col
        )
    }

    st = stop_times[["trip_id", "stop_id", "stop_sequence"]].copy()
    st["_seq"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
    st = st.sort_values(["trip_id", "_seq"], kind="stable")
    sequences = st.groupby("trip_id", sort=False)["stop_id"].agg(tuple)

    # (family, direction, 基底名列) → [trip 数, 代表 stop_id 列]
    counter: dict[tuple, list] = {}
    for trip_id, stop_ids in sequences.items():
        family, direction = trip_meta.get(trip_id, ("", ""))
        if not family:
            continue
        base_seq = tuple(stop_to_base.get(s, s) for s in stop_ids)
        key = (family, direction, base_seq)
        if key in counter:
            counter[key][0] += 1
        else:
            counter[key] = [1, stop_ids]

    patterns: list[StopPattern] = []
    # 決定的順序: family, direction, -trip_count, 基底名列
    ordered = sorted(counter.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1][0], kv[0][2]))
    seq_no: dict[tuple[str, str], int] = defaultdict(int)
    for (family, direction, base_seq), (count, stop_ids) in ordered:
        idx = seq_no[(family, direction)]
        seq_no[(family, direction)] += 1
        patterns.append(
            StopPattern(
                pattern_id=f"{family}|{direction}|p{idx}",
                family=family,
                direction=direction,
                base_names=base_seq,
                display_names=tuple(stop_names.get(s, s) for s in stop_ids),
                trip_count=count,
            )
        )
    logger.info(
        "%s: trip %d 本 → 一意パターン %d 件",
        snapshot.meta.label(),
        len(sequences),
        len(patterns),
    )
    return patterns


# --- 類似度 ---


def _lcs_length(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[n]


def _direction_consistency(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """共通停留所の相対順序の保存率 (0-1)。共通2未満は中立 0.5。"""
    common = set(a) & set(b)
    if len(common) < 2:
        return 0.5
    first_a = {}
    for i, x in enumerate(a):
        if x in common and x not in first_a:
            first_a[x] = i
    first_b = {}
    for i, x in enumerate(b):
        if x in common and x not in first_b:
            first_b[x] = i
    items = sorted(first_a.items(), key=lambda kv: kv[1])
    matches = 0
    total = 0
    for i in range(len(items) - 1):
        for j in range(i + 1, len(items)):
            xa, xb = items[i][0], items[j][0]
            total += 1
            if first_b[xa] < first_b[xb]:
                matches += 1
    return matches / total if total else 0.5


def pattern_similarity(
    a: tuple[str, ...], b: tuple[str, ...], config: Config
) -> float:
    """2つの停車パターン (基底名列) の類似度 (0-1)。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    pc = lambda key, d: config.get("identity", "pattern_clustering", key, default=d)  # noqa: E731
    lcs_sim = 2.0 * _lcs_length(a, b) / (len(a) + len(b))
    direction = _direction_consistency(a, b)
    set_a, set_b = set(a), set(b)
    if set_a <= set_b or set_b <= set_a:
        containment = min(len(a), len(b)) / max(len(a), len(b))
    else:
        containment = 0.0
    return min(
        1.0,
        pc("lcs_weight", 0.6) * lcs_sim
        + pc("direction_weight", 0.3) * direction
        + pc("containment_weight", 0.1) * containment,
    )


# --- 世代内クラスタリング ---


def cluster_patterns(patterns: list[StopPattern], config: Config) -> list[PatternCluster]:
    """family × 方向ごとに類似パターンを連結成分でクラスタ化する。"""
    threshold = config.get(
        "identity", "pattern_clustering", "similarity_threshold", default=0.5
    )
    switch = config.get(
        "identity", "pattern_clustering", "hierarchical_switch_patterns", default=50
    )

    by_group: dict[tuple[str, str], list[StopPattern]] = defaultdict(list)
    for p in patterns:
        by_group[(p.family, p.direction)].append(p)

    clusters: list[PatternCluster] = []
    for (family, direction), group in sorted(by_group.items()):
        if len(group) > switch:
            components: list[list[StopPattern]] = []
            pre: dict[tuple, list[StopPattern]] = defaultdict(list)
            for p in group:
                key = (p.base_names[0], p.base_names[-1], len(p.base_names) // 5)
                pre[key].append(p)
            for sub in pre.values():
                components.extend(_connected_components(sub, threshold, config))
            logger.info(
                "%s|%s: %d パターン → 予備グループ %d 経由で成分分解",
                family, direction, len(group), len(pre),
            )
        else:
            components = _connected_components(group, threshold, config)

        # trip 数の多い成分から採番 (決定的)
        components.sort(key=lambda c: (-sum(p.trip_count for p in c), c[0].pattern_id))
        for i, component in enumerate(components):
            representative = max(component, key=lambda p: (p.trip_count, -len(p.base_names)))
            clusters.append(
                PatternCluster(
                    cluster_id=f"{family}|{direction}|c{i}",
                    family=family,
                    direction=direction,
                    representative=representative,
                    patterns=sorted(component, key=lambda p: p.pattern_id),
                )
            )
    return clusters


def _connected_components(
    group: list[StopPattern], threshold: float, config: Config
) -> list[list[StopPattern]]:
    n = len(group)
    visited = [False] * n
    components = []
    for i in range(n):
        if visited[i]:
            continue
        queue = [i]
        visited[i] = True
        member = []
        while queue:
            k = queue.pop()
            member.append(group[k])
            for j in range(n):
                if not visited[j] and (
                    pattern_similarity(group[k].base_names, group[j].base_names, config)
                    >= threshold
                ):
                    visited[j] = True
                    queue.append(j)
        components.append(member)
    return components


# --- 世代間リンク ---


def link_pattern_clusters(
    old_clusters: list[PatternCluster],
    new_clusters: list[PatternCluster],
    family_edges: list[MatchEdge],
    config: Config,
) -> list[MatchEdge]:
    """対応づいた family ペア内でクラスタ代表パターン同士を照合する。"""
    link_floor = config.get("identity", "pattern_clustering", "link_floor", default=0.3)
    old_by_family: dict[str, list[PatternCluster]] = defaultdict(list)
    for c in old_clusters:
        old_by_family[c.family].append(c)
    new_by_family: dict[str, list[PatternCluster]] = defaultdict(list)
    for c in new_clusters:
        new_by_family[c.family].append(c)

    edges: list[MatchEdge] = []
    for fe in family_edges:
        for old in old_by_family.get(fe.old_id, ()):
            for new in new_by_family.get(fe.new_id, ()):
                sim = pattern_similarity(
                    old.representative.base_names, new.representative.base_names, config
                )
                confidence = sim * fe.confidence
                if confidence < link_floor:
                    continue
                edges.append(
                    MatchEdge(
                        entity_type=ENTITY_PATTERN_CLUSTER,
                        old_id=old.cluster_id,
                        new_id=new.cluster_id,
                        confidence=round(confidence, 4),
                        method="pattern_similarity",
                    )
                )
    logger.info(
        "pattern cluster link: old %d / new %d → エッジ %d 本",
        len(old_clusters),
        len(new_clusters),
        len(edges),
    )
    return edges

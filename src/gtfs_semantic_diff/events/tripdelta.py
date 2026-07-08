"""trip の世代間照合 (trip matching v2 — 大域コスト割当)。設計: docs/design/trip_matching.md。

trip_id の連続性は仮定しない。ID の一致は「同一便」の定義ではなく、
数ある証拠の一つ (弱い事前) として扱う — 連番型 ID 運用 (八戸型) では
便の増減で同じ ID が別の時刻の便を指すため (docs/verification/trip_identity_survey.md)。

手順:
1. 内容署名 (family, direction, day_type, 停車列, 時刻列) の完全一致 → exact_pairs
   (trip_id が違えば TECHNICAL_ID_CHURN の対象)
2. 残りを (対応 family グループ, day_type) のブロック内で**コスト最小の割当**:
     cost = w_time · min(Δt_shared, cap)/cap + w_route · (1 − LCS率) − w_id · [同一ID]
   - Δt_shared = 共有停留所での発時刻差の中央値 (区間短縮・延長に頑健)
   - 受理ゲート: LCS率 ≥ min_route_sim かつ Δt_shared ≤ max_shift_min
   - コスト昇順の決定的貪欲 (感度分析で正解/非正解のコストは大きく二極化しており、
     閾値に敏感でない。docs/design/trip_matching.md §5)
   → modified (時刻修正・経路変更)
3. 残り → removed / added (C群ルールの便数比較プール)

この分類が C群 (便数・時刻)・B群 (パターン変化)・TECHNICAL_ID_CHURN・
④差分時刻表の共通土台になる。
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from ..model import GtfsSnapshot
from .timebands import parse_gtfs_time

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TripInfo:
    trip_id: str
    route_id: str
    family: str
    direction: str
    day_type: str
    base_seq: tuple[str, ...]  # 停留所クラスタ基底名列
    times: tuple[tuple[str, str], ...]  # (arrival, departure) 列

    @property
    def signature(self) -> tuple:
        return (self.family, self.direction, self.day_type, self.base_seq, self.times)

    @property
    def first_departure(self) -> str:
        if not self.times:
            return ""
        arr, dep = self.times[0]
        return dep or arr


@dataclass
class TripDelta:
    old_trips: dict[str, TripInfo] = field(default_factory=dict)
    new_trips: dict[str, TripInfo] = field(default_factory=dict)
    exact_pairs: list[tuple[TripInfo, TripInfo]] = field(default_factory=list)
    modified: list[tuple[TripInfo, TripInfo]] = field(default_factory=list)  # 割当結果
    removed: list[TripInfo] = field(default_factory=list)
    added: list[TripInfo] = field(default_factory=list)

    @property
    def churn_pairs(self) -> list[tuple[TripInfo, TripInfo]]:
        """内容同一だが trip_id が張り替わった組。"""
        return [(o, n) for o, n in self.exact_pairs if o.trip_id != n.trip_id]


def collect_trips(snapshot: GtfsSnapshot, route_to_family: dict[str, str],
                  stop_to_base: dict[str, str]) -> dict[str, TripInfo]:
    """スナップショットの全 trip を TripInfo 化する。"""
    trips = snapshot.table("trips")
    stop_times = snapshot.table("stop_times")
    if trips is None or stop_times is None:
        return {}

    st = stop_times[["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"]].copy()
    st["_seq"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
    st = st.sort_values(["trip_id", "_seq"], kind="stable")
    grouped = st.groupby("trip_id", sort=False)
    seqs = grouped["stop_id"].agg(tuple)
    arrs = grouped["arrival_time"].agg(tuple)
    deps = grouped["departure_time"].agg(tuple)

    direction_col = trips["direction_id"] if "direction_id" in trips.columns else [""] * len(trips)
    result: dict[str, TripInfo] = {}
    for trip_id, route_id, service_id, direction in zip(
        trips["trip_id"], trips["route_id"], trips["service_id"], direction_col
    ):
        stop_seq = seqs.get(trip_id, ())
        result[trip_id] = TripInfo(
            trip_id=trip_id,
            route_id=route_id,
            family=route_to_family.get(route_id, ""),
            direction=str(direction).strip(),
            day_type=snapshot.day_types.get(service_id, "irregular"),
            base_seq=tuple(stop_to_base.get(s, s) for s in stop_seq),
            times=tuple(zip(arrs.get(trip_id, ()), deps.get(trip_id, ()))),
        )
    return result


# --- コスト成分 ---


def dt_shared_minutes(o: TripInfo, n: TripInfo) -> float | None:
    """共有停留所 (初出) での発時刻差の中央値 (分)。共有なしは始発時刻差。

    区間短縮・延長・途中経由変更では共有部分の時刻がほぼ据え置きになるため、
    始発時刻差より頑健な「同じ便か」の証拠になる。
    """
    old_time: dict[str, str] = {}
    for s, (arr, dep) in zip(o.base_seq, o.times):
        old_time.setdefault(s, dep or arr)
    diffs: list[float] = []
    seen: set[str] = set()
    for s, (arr, dep) in zip(n.base_seq, n.times):
        if s in old_time and s not in seen:
            seen.add(s)
            a = parse_gtfs_time(old_time[s])
            b = parse_gtfs_time(dep or arr)
            if a is not None and b is not None:
                diffs.append(abs(b - a) / 60)
    if diffs:
        return statistics.median(diffs)
    a = parse_gtfs_time(o.first_departure)
    b = parse_gtfs_time(n.first_departure)
    if a is None or b is None:
        return None
    return abs(b - a) / 60


def lcs_ratio(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """停車列の LCS 長 / max(len)。順序を考慮するため逆方向便は低くなる。"""
    m, n = len(a), len(b)
    if not m or not n:
        return 0.0
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = cur[j - 1] if cur[j - 1] >= prev[j] else prev[j]
        prev = cur
    return prev[n] / max(m, n)


@dataclass(frozen=True)
class MatchingParams:
    """[matching] の閾値。既定値は感度分析 (trip_matching.md §5) に基づく。"""

    min_route_sim: float = 0.5   # 受理に必要な停車列 LCS率の下限
    max_shift_min: float = 60.0  # 受理に必要な Δt_shared の上限 (分)
    time_cap_min: float = 60.0   # コストの時刻項の正規化上限 (分)
    w_route: float = 1.0         # 経路不整合の重み
    w_id: float = 0.05           # 同一 trip_id の減点 (弱い事前。二極化ギャップ ≪)

    @classmethod
    def from_config(cls, config) -> "MatchingParams":
        if config is None:
            return cls()
        g = lambda k, d: config.get("matching", k, default=d)  # noqa: E731
        return cls(
            min_route_sim=g("min_route_sim", cls.min_route_sim),
            max_shift_min=g("max_shift_min", cls.max_shift_min),
            time_cap_min=g("time_cap_min", cls.time_cap_min),
            w_route=g("w_route", cls.w_route),
            w_id=g("w_id", cls.w_id),
        )


def build_trip_delta(
    old_trips: dict[str, TripInfo],
    new_trips: dict[str, TripInfo],
    config=None,
    family_links: dict[str, str] | None = None,
) -> TripDelta:
    """世代間の便対応付け。

    family_links: 旧 family 名 → 新 family 名 (identity の対応。名称一致は
    恒等でよいので省略可)。ブロッキング (候補対の範囲) に使う。
    """
    params = MatchingParams.from_config(config)
    family_links = family_links or {}
    delta = TripDelta(old_trips=old_trips, new_trips=new_trips)

    # --- 段1: 内容署名の完全一致 (同一 trip_id を優先ペアリング) ---
    by_sig_old: dict[tuple, list[TripInfo]] = defaultdict(list)
    for t in old_trips.values():
        by_sig_old[t.signature].append(t)
    by_sig_new: dict[tuple, list[TripInfo]] = defaultdict(list)
    for t in new_trips.values():
        by_sig_new[t.signature].append(t)

    paired_old: set[str] = set()
    paired_new: set[str] = set()
    for sig in by_sig_old.keys() & by_sig_new.keys():
        olds = sorted(by_sig_old[sig], key=lambda t: t.trip_id)
        news = sorted(by_sig_new[sig], key=lambda t: t.trip_id)
        new_by_id = {t.trip_id: t for t in news}
        rest_old, rest_new = [], list(news)
        for o in olds:
            if o.trip_id in new_by_id and new_by_id[o.trip_id] in rest_new:
                n = new_by_id[o.trip_id]
                delta.exact_pairs.append((o, n))
                rest_new.remove(n)
                paired_old.add(o.trip_id)
                paired_new.add(n.trip_id)
            else:
                rest_old.append(o)
        for o, n in zip(rest_old, rest_new):
            delta.exact_pairs.append((o, n))
            paired_old.add(o.trip_id)
            paired_new.add(n.trip_id)

    # --- 段2: ブロック内のコスト最小割当 ---
    def block_key(t: TripInfo, gen: str) -> tuple:
        fam = family_links.get(t.family, t.family) if gen == "old" else t.family
        return (fam, t.day_type)

    blocks: dict[tuple, tuple[list[TripInfo], list[TripInfo]]] = defaultdict(
        lambda: ([], [])
    )
    for t in old_trips.values():
        if t.trip_id not in paired_old:
            blocks[block_key(t, "old")][0].append(t)
    for t in new_trips.values():
        if t.trip_id not in paired_new:
            blocks[block_key(t, "new")][1].append(t)

    for key in sorted(blocks):
        olds, news = blocks[key]
        candidates = []
        for o in olds:
            for n in news:
                sim = lcs_ratio(o.base_seq, n.base_seq)
                if sim < params.min_route_sim:
                    continue
                dt = dt_shared_minutes(o, n)
                if dt is None or dt > params.max_shift_min:
                    continue
                cost = (
                    min(dt, params.time_cap_min) / params.time_cap_min
                    + params.w_route * (1.0 - sim)
                    - (params.w_id if o.trip_id == n.trip_id else 0.0)
                )
                candidates.append(
                    (round(cost, 6), round(dt, 3), o.trip_id, n.trip_id, o, n)
                )
        candidates.sort(key=lambda c: c[:4])
        used_old: set[str] = set()
        used_new: set[str] = set()
        for _, _, o_id, n_id, o, n in candidates:
            if o_id in used_old or n_id in used_new:
                continue
            used_old.add(o_id)
            used_new.add(n_id)
            delta.modified.append((o, n))
            paired_old.add(o_id)
            paired_new.add(n_id)

    delta.modified.sort(key=lambda p: (p[0].trip_id, p[1].trip_id))
    delta.removed = sorted(
        (t for t in old_trips.values() if t.trip_id not in paired_old),
        key=lambda t: t.trip_id,
    )
    delta.added = sorted(
        (t for t in new_trips.values() if t.trip_id not in paired_new),
        key=lambda t: t.trip_id,
    )
    logger.info(
        "trip delta: exact %d (うち churn %d) / modified %d / removed %d / added %d",
        len(delta.exact_pairs),
        len(delta.churn_pairs),
        len(delta.modified),
        len(delta.removed),
        len(delta.added),
    )
    return delta

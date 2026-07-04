"""trip の世代間照合 (内容署名ベース)。trip_id の連続性は仮定しない。

各 trip を内容署名 (family, direction, day_type, 停車クラスタ基底名列,
全停留所の発着時刻列) で表し:

- 署名が完全一致する old/new の組 → exact_pairs
  (trip_id が違えば TECHNICAL_ID_CHURN の対象、同じなら「変更なし」)
- 署名不一致でも同一 trip_id が両世代にある → modified (時刻修正・経路変更)
- 残り → removed / added (C群ルールの便数比較プール)

この分類が C群 (便数・時刻) と TECHNICAL_ID_CHURN の共通土台になる。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from ..model import GtfsSnapshot

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
    modified: list[tuple[TripInfo, TripInfo]] = field(default_factory=list)  # 同一 trip_id
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


def build_trip_delta(
    old_trips: dict[str, TripInfo], new_trips: dict[str, TripInfo]
) -> TripDelta:
    delta = TripDelta(old_trips=old_trips, new_trips=new_trips)

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
        # 同一 trip_id 同士を優先ペアリング
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

    # 同一 trip_id が残っていれば内容変更 (modified)
    for trip_id in sorted((old_trips.keys() & new_trips.keys()) - paired_old - paired_new):
        delta.modified.append((old_trips[trip_id], new_trips[trip_id]))
        paired_old.add(trip_id)
        paired_new.add(trip_id)

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

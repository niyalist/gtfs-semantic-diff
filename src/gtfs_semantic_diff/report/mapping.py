"""ID 対応表 (mapping.json、IM1 — docs/design/ai_interface.md §5.1)。

identity 層 (MatchGraph + family_components) と TripDelta を直列化し、
「差分を乗り越える」外部システム (乗客データの経年結合・整備資産の
世代引き継ぎ) のバックエンドにする。原則:

- **N:M を 1:1 に潰さない**: 対応は常に old/new とも配列。
- **confidence・根拠を必ず付ける**: 判定手法 (method)・信頼度と、
  関連 ChangeEvent の event_id (説明台帳への入口)。
- **判断は消費側に残す**: 「移設 120m を同一停留所と扱うか」等は
  事実 (moved_m・renamed) を渡すだけで、こちらで決めない。

注意 (契約): identity アルゴリズムの改良でツール版が上がると対応結果も
変わり得る。mapping は版付き成果物なので消費側は版をピンして再現できる。
"""
from __future__ import annotations

import math
from typing import Any

MAPPING_SCHEMA = 1


def _moved_m(a, b) -> int | None:
    """クラスタ代表点間の距離 (m)。座標欠損は None。"""
    try:
        la, lo, lb, lob = float(a.lat), float(a.lon), float(b.lat), float(b.lon)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (la, lo, lb, lob)):
        return None
    x = math.radians(lob - lo) * math.cos(math.radians((la + lb) / 2))
    y = math.radians(lb - la)
    return round(math.hypot(x, y) * 6371000)


def _event_index(event_set) -> dict[str, list[str]]:
    """subject の文字列値 → event_id 群 (名前ベースの緩い逆引き)。"""
    idx: dict[str, list[str]] = {}
    for e in event_set.events:
        for v in (e.subject or {}).values():
            if isinstance(v, str) and v:
                idx.setdefault(v, []).append(e.event_id)
    return idx


def build_mapping(identity, trip_delta, event_set, meta: dict | None = None) -> dict[str, Any]:
    ev_idx = _event_index(event_set)

    def events_for(*names) -> list[str]:
        out: list[str] = []
        for n in names:
            for eid in ev_idx.get(n, []):
                if eid not in out:
                    out.append(eid)
        return out

    # --- 停留所 (クラスタ対応 = GTFS stop_id 群の旧新対応) ---
    stops = []
    seen_old: set[str] = set()
    seen_new: set[str] = set()
    for e in identity.graph.for_type("stop_cluster"):
        old_c = identity.old_stop_clusters.get(e.old_id) if e.old_id else None
        new_c = identity.new_stop_clusters.get(e.new_id) if e.new_id else None
        if old_c:
            seen_old.add(e.old_id)
        if new_c:
            seen_new.add(e.new_id)
        if old_c and new_c:
            relation = "renamed" if old_c.name != new_c.name else "continued"
        elif new_c:
            relation = "added"
        else:
            relation = "removed"
        entry: dict[str, Any] = {"relation": relation}
        if old_c:
            entry["old"] = {"name": old_c.name, "stop_ids": list(old_c.platform_ids)}
        if new_c:
            entry["new"] = {"name": new_c.name, "stop_ids": list(new_c.platform_ids)}
        if old_c and new_c:
            entry["confidence"] = e.confidence
            entry["method"] = e.method
            m = _moved_m(old_c, new_c)
            if m:
                entry["moved_m"] = m
        evs = events_for(*(c.name for c in (old_c, new_c) if c))
        if evs:
            entry["events"] = evs
        stops.append(entry)
    for cid, c in identity.old_stop_clusters.items():
        if cid not in seen_old:
            stops.append({"relation": "removed",
                          "old": {"name": c.name, "stop_ids": list(c.platform_ids)},
                          **({"events": e} if (e := events_for(c.name)) else {})})
    for cid, c in identity.new_stop_clusters.items():
        if cid not in seen_new:
            stops.append({"relation": "added",
                          "new": {"name": c.name, "stop_ids": list(c.platform_ids)},
                          **({"events": e} if (e := events_for(c.name)) else {})})

    # --- 路線 (family 対応 = route_id 群の旧新対応)。N:M は成分のまま ---
    def fam_side(names, families) -> list[dict]:
        return [{"name": n, "route_ids": list(families[n].route_ids)}
                for n in names if n in families]

    routes = []
    in_component_old: set[str] = set()
    in_component_new: set[str] = set()
    for comp in identity.family_components:
        old_names = list(comp.get("old", []))
        new_names = list(comp.get("new", []))
        in_component_old.update(old_names)
        in_component_new.update(new_names)
        entry = {
            "relation": comp.get("shape", "restructured"),
            "old": fam_side(old_names, identity.old_families),
            "new": fam_side(new_names, identity.new_families),
            "similarity": comp.get("similarity"),
        }
        evs = events_for(*old_names, *new_names)
        if evs:
            entry["events"] = evs
        routes.append(entry)
    matched_old: set[str] = set(in_component_old)
    matched_new: set[str] = set(in_component_new)
    for e in identity.graph.for_type("route_family"):
        if not (e.old_id and e.new_id):
            continue
        if e.old_id in in_component_old or e.new_id in in_component_new:
            continue
        matched_old.add(e.old_id)
        matched_new.add(e.new_id)
        entry = {
            "relation": "continued",
            "old": fam_side([e.old_id], identity.old_families),
            "new": fam_side([e.new_id], identity.new_families),
            "confidence": e.confidence,
            "method": e.method,
        }
        evs = events_for(e.old_id, e.new_id)
        if evs:
            entry["events"] = evs
        routes.append(entry)
    for name in identity.old_families:
        if name not in matched_old:
            routes.append({"relation": "removed",
                           "old": fam_side([name], identity.old_families),
                           "new": [],
                           **({"events": e} if (e := events_for(name)) else {})})
    for name in identity.new_families:
        if name not in matched_new:
            routes.append({"relation": "added", "old": [],
                           "new": fam_side([name], identity.new_families),
                           **({"events": e} if (e := events_for(name)) else {})})

    # --- 便 (trip_id 対応) ---
    trips = []
    for o, n in trip_delta.exact_pairs:
        trips.append({"relation": "exact" if o.trip_id == n.trip_id else "id_churn",
                      "old": o.trip_id, "new": n.trip_id})
    for o, n in trip_delta.modified:
        trips.append({"relation": "modified", "old": o.trip_id, "new": n.trip_id})
    for t in trip_delta.removed:
        trips.append({"relation": "removed", "old": t.trip_id, "new": None})
    for t in trip_delta.added:
        trips.append({"relation": "added", "old": None, "new": t.trip_id})

    day_types = [
        {"old": e.old_id or None, "new": e.new_id or None,
         "confidence": e.confidence}
        for e in identity.graph.for_type("service")
    ]

    counts = {
        "stops": len(stops),
        "routes": len(routes),
        "trips": len(trips),
        "trips_by_relation": {},
    }
    for t in trips:
        r = t["relation"]
        counts["trips_by_relation"][r] = counts["trips_by_relation"].get(r, 0) + 1

    return {
        "mapping_schema": MAPPING_SCHEMA,
        "meta": dict(meta or {}),
        "note": ("対応は identity 層の判定 (内容主導・決定的)。N:M は配列のまま。"
                 "同一視の最終判断は利用側で行うこと。events は説明台帳への入口"),
        "counts": counts,
        "stops": stops,
        "routes": routes,
        "trips": trips,
        "day_types": day_types,
    }

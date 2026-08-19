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
    # **採択された対応だけを出す**: ①同一クラスタ ID (同名) の継続、
    # ②STOP_RENAMED イベント (ルール段が採択した改称)。MatchGraph の
    # 仮説エッジ (近接候補・双方向) はルール段が棄却したものを含むため、
    # そのまま流さない — 説明台帳と同じ結論だけが mapping になる。
    stops = []
    seen_old: set[str] = set()
    seen_new: set[str] = set()

    def _stop_entry(relation, old_c, new_c, **extra) -> dict[str, Any]:
        entry: dict[str, Any] = {"relation": relation}
        if old_c is not None:
            entry["old"] = {"name": old_c.name, "stop_ids": list(old_c.platform_ids)}
        if new_c is not None:
            entry["new"] = {"name": new_c.name, "stop_ids": list(new_c.platform_ids)}
        if old_c is not None and new_c is not None:
            m = _moved_m(old_c, new_c)
            if m:
                entry["moved_m"] = m
        entry.update({k: v for k, v in extra.items() if v})
        return entry

    for cid, old_c in identity.old_stop_clusters.items():
        new_c = identity.new_stop_clusters.get(cid)
        if new_c is None:
            continue
        seen_old.add(cid)
        seen_new.add(cid)
        stops.append(_stop_entry(
            "continued", old_c, new_c, confidence=1.0, method="name",
            events=events_for(old_c.name) or None))

    def _cluster_by_name(clusters, name):
        for cid, c in clusters.items():
            if c.name == name:
                return cid, c
        return None, None

    for e in event_set.events:
        if e.type != "STOP_RENAMED":
            continue
        old_cid, old_c = _cluster_by_name(
            identity.old_stop_clusters, (e.old_ref or {}).get("name", ""))
        new_cid, new_c = _cluster_by_name(
            identity.new_stop_clusters, (e.new_ref or {}).get("name", ""))
        if old_c is None or new_c is None:
            continue
        seen_old.add(old_cid)
        seen_new.add(new_cid)
        edge_conf = next(
            (ed.confidence for ed in identity.graph.for_type("stop_cluster")
             if ed.old_id == old_cid and ed.new_id == new_cid), None)
        stops.append(_stop_entry(
            "renamed", old_c, new_c, confidence=edge_conf,
            events=[e.event_id]))

    for cid, c in identity.old_stop_clusters.items():
        if cid not in seen_old:
            stops.append(_stop_entry("removed", c, None,
                                     events=events_for(c.name) or None))
    for cid, c in identity.new_stop_clusters.items():
        if cid not in seen_new:
            stops.append(_stop_entry("added", None, c,
                                     events=events_for(c.name) or None))

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
    # 成分外は**同名の継続のみ**を採択 (名前が違う対応は M9 成分が
    # RENAMED 等として持つ。graph に残る名前違いエッジは仮説であり出さない)
    for name in identity.old_families:
        if name in matched_old or name not in identity.new_families:
            continue
        matched_old.add(name)
        matched_new.add(name)
        entry = {
            "relation": "continued",
            "old": fam_side([name], identity.old_families),
            "new": fam_side([name], identity.new_families),
            "confidence": 1.0,
            "method": "name",
        }
        evs = events_for(name)
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

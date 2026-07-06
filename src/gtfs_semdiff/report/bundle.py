"""HTML ビューア用の結果バンドル生成 (docs/design/web.md)。

ChangeEventSet JSON に加え、ビューアのドリルダウンに必要な素材を JSON 化する:
- geometry: 停留所クラスタの座標 (新旧・異動ステータス付き) と、イベントに
  現れる shape の新旧ポリライン (GeoJSON FeatureCollection)
- timetables: イベントが立った (family, direction, day_type) グループの
  新旧発車時刻一覧 (時刻表 before/after 描画用)
- catalog: イベントタイプの ja/en 表示名 (ビューアの i18n)
- meta: ツール情報

core には依存する (identity / trip_delta の成果物を素材にする) が、
core は bundle を知らない (設計原則 3 の consumer)。
"""

from __future__ import annotations

import datetime
import importlib.metadata
import json
from typing import Any

from ..config import Config
from ..identity import IdentityResult
from ..model import EVENT_TYPES, ChangeEventSet, GtfsSnapshot, RawDiffSet
from ..model.matchgraph import ENTITY_STOP_CLUSTER


def build_bundle(
    old: GtfsSnapshot,
    new: GtfsSnapshot,
    config: Config,
    event_set: ChangeEventSet,
    rawdiffs: RawDiffSet,
    identity: IdentityResult,
    trip_delta,
) -> dict[str, Any]:
    """ビューアに埋め込む全データ (JSON 化可能な dict)。"""
    from .presentation import build_presentation

    return {
        "events": event_set.to_dict(),
        "rawdiffs": [d.to_dict() for d in rawdiffs.diffs],
        "presentation": build_presentation(event_set, identity, trip_delta, config),
        "geometry": _geometry(event_set, identity, old, new, config),
        "timetables": _timetables(event_set, trip_delta),
        "catalog": {
            t.type_id: {"ja": t.display_name_ja, "en": t.display_name_en,
                        "category": t.category}
            for t in EVENT_TYPES.values()
        },
        "meta": {
            "tool": "gtfs-semdiff",
            "version": _version(),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "feed": event_set.feed,
        },
    }


def _version() -> str:
    try:
        return importlib.metadata.version("gtfs-semdiff")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# --- 幾何 ---


def _geometry(
    event_set: ChangeEventSet,
    identity: IdentityResult,
    old: GtfsSnapshot,
    new: GtfsSnapshot,
    config: Config,
) -> dict:
    """停留所クラスタ点 (異動ステータス付き) + イベント関連 shape 線 (GeoJSON)。"""
    features: list[dict] = []

    accept = config.get("events", "accept_confidence", default=0.5)
    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for e in identity.graph.for_type(ENTITY_STOP_CLUSTER):
        if e.confidence >= accept:
            matched_old.add(e.old_id)
            matched_new.add(e.new_id)

    for cid, c in sorted(identity.new_stop_clusters.items()):
        status = "matched" if cid in matched_new else "added"
        features.append(_point(c, "new", status))
    for cid, c in sorted(identity.old_stop_clusters.items()):
        if cid not in matched_old:
            features.append(_point(c, "old", "removed"))

    # イベントに現れる shape の新旧ポリライン
    wanted: dict[str, set[str]] = {"old": set(), "new": set()}
    for e in event_set.events:
        if e.type not in ("SHAPE_CHANGED", "TECHNICAL_ID_CHURN"):
            continue
        subject_shape = e.subject.get("shape_id", "")
        wanted["old"].add(e.quantification.get("old_shape", subject_shape))
        wanted["new"].add(e.quantification.get("new_shape", subject_shape))

    if wanted["old"] or wanted["new"]:
        from ..events.rules.shapes import _polylines

        max_points = config.get("events", "shape", "max_polyline_points", default=200)
        for snapshot, gen in ((old, "old"), (new, "new")):
            lines = _polylines(snapshot, max_points)
            for shape_id in sorted(wanted[gen]):
                pts = lines.get(shape_id)
                if not pts:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[lon, lat] for lat, lon in pts],
                        },
                        "properties": {
                            "shape_id": shape_id,
                            "generation": gen,
                            "kind": "shape",
                        },
                    }
                )
    return {"type": "FeatureCollection", "features": features}


def _point(cluster, gen: str, status: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [cluster.lon, cluster.lat]},
        "properties": {
            "name": cluster.name,
            "base_name": cluster.base_name,
            "cluster_id": cluster.cluster_id,
            "generation": gen,
            "status": status,  # matched / added / removed
            "platforms": len(cluster.platform_ids),
        },
    }


# --- 時刻表 ---


def _timetables(event_set: ChangeEventSet, trip_delta) -> list[dict]:
    """イベントが立ったグループの新旧発車時刻一覧。"""
    groups: set[tuple[str, str, str]] = set()
    for e in event_set.events:
        family = e.subject.get("route_family")
        if family and "day_type" in e.subject:
            groups.add(
                (family, e.subject.get("direction", ""), e.subject["day_type"])
            )

    def trips_of(trips: dict, key: tuple) -> list[dict]:
        rows = [
            {
                "trip_id": t.trip_id,
                "departure": t.first_departure,
                "from": t.base_seq[0] if t.base_seq else "",
                "to": t.base_seq[-1] if t.base_seq else "",
                "stops": len(t.base_seq),
            }
            for t in trips.values()
            if (t.family, t.direction, t.day_type) == key
        ]
        return sorted(rows, key=lambda r: r["departure"])

    result = []
    for key in sorted(groups):
        family, direction, day_type = key
        result.append(
            {
                "route_family": family,
                "direction": direction,
                "day_type": day_type,
                "old": trips_of(trip_delta.old_trips, key),
                "new": trips_of(trip_delta.new_trips, key),
            }
        )
    return result


def render_html(bundle: dict[str, Any], template_html: str) -> str:
    """ビルド済みビューアテンプレートにバンドル JSON を埋め込む。"""
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # </script> でパースが壊れないようエスケープ
    payload = payload.replace("</", "<\\/")
    return template_html.replace("__GTFS_SEMDIFF_DATA__", payload)

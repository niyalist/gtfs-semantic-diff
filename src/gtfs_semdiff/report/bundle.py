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

    presentation = build_presentation(event_set, identity, trip_delta, config)
    # 第1部 (フィード全体) と第4部 (その他) はスナップショット・RawDiff を
    # 素材にするためここで付与する (presentation.py は events/identity/delta のみ)
    presentation["feed_overview"] = _feed_overview(
        old, new, event_set, rawdiffs, trip_delta
    )

    return {
        "events": event_set.to_dict(),
        "rawdiffs": [d.to_dict() for d in rawdiffs.diffs],
        "presentation": presentation,
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


# --- 第1部 (フィード全体の変化) と第4部 (その他の変化) の素材 ---

# 第1部で読み下すフィード級イベント (E群 + F群のメタ系)
_PART1_EVENT_TYPES = frozenset({
    "DAYTYPE_RESTRUCTURED", "HOLIDAY_EXCEPTION_CHANGED", "SEASONAL_SERVICE_CHANGED",
    "FEED_VALIDITY_CHANGED", "AGENCY_INFO_CHANGED", "TRANSLATION_CHANGED",
    "FARE_CHANGED", "DEMAND_RESPONSIVE_CHANGE",
})


def _feed_overview(old, new, event_set, rawdiffs, trip_delta) -> dict:
    """4部構成レポートの第1部・第4部ビュー。

    - files: txt ファイルごとの新旧対応表 (有無・行数・RawDiff 内訳)
    - day_types: 曜日区分ごとの便数 旧→新
    - meta_events: フィード級イベント (期間・事業者・カレンダー・運賃等)
    - others (第4部): 第1〜3部のどこにも現れないイベントの種類別件数。
      レポート面の取りこぼしを常に可視化する (V5 で presentation_refs による
      機械的な網羅判定に昇格予定)
    """
    from .presentation import day_sort_key

    # ファイル対応表
    old_names = {f"{n}.txt" for n in old.tables}
    new_names = {f"{n}.txt" for n in new.tables}
    per_file: dict[str, dict[str, int]] = {}
    for d in rawdiffs.diffs:
        b = per_file.setdefault(d.file, {})
        b[d.kind] = b.get(d.kind, 0) + 1
    files = []
    for name in sorted(old_names | new_names | set(per_file)):
        stem = name.removesuffix(".txt")
        t_old = old.tables.get(stem)
        t_new = new.tables.get(stem)
        counts = per_file.get(name, {})
        files.append({
            "name": name,
            "status": ("continued" if name in old_names and name in new_names
                       else "added" if name in new_names else "removed"),
            "rows_old": len(t_old) if t_old is not None else None,
            "rows_new": len(t_new) if t_new is not None else None,
            "row_added": counts.get("row_added", 0),
            "row_removed": counts.get("row_removed", 0),
            "field_changed": counts.get("field_changed", 0),
            "column_changes": counts.get("column_added", 0)
            + counts.get("column_removed", 0),
        })

    # 曜日区分ごとの便数 旧→新
    day_counts: dict[str, list[int]] = {}
    for trips, side in ((trip_delta.old_trips, 0), (trip_delta.new_trips, 1)):
        for t in trips.values():
            day_counts.setdefault(t.day_type, [0, 0])[side] += 1
    day_types = [
        {"day_type": d, "old": c[0], "new": c[1]}
        for d, c in sorted(day_counts.items(), key=lambda kv: day_sort_key(kv[0]))
    ]

    # フィード級イベント (第1部) — 表示はビューアが catalog の表示名で行う
    meta_events = [
        {
            "type": e.type,
            "subject": e.subject,
            "quantification": e.quantification,
            "old_ref": e.old_ref,
            "new_ref": e.new_ref,
        }
        for e in event_set.events
        if e.type in _PART1_EVENT_TYPES
    ]

    # 第4部: 第1〜3部のどこにも現れないイベントの種類別件数。
    # 路線ページが受け持つ A/B/C 群 (SHAPE_CHANGED は Lev.5 の件数のみで座標の
    # 詳細を見せていないため第4部へ)、停留所章が受け持つ D 群、第1部、
    # HEADSIGN_CHANGED (路線 Lev.5) を除いた残り全て — 将来のイベント追加も
    # 自動的にここへ落ちる
    route_covered = {
        t.type_id for t in EVENT_TYPES.values() if t.category in ("A", "B", "C")
    } - {"SHAPE_CHANGED"}
    stop_covered = {t.type_id for t in EVENT_TYPES.values() if t.category == "D"}
    covered = route_covered | stop_covered | _PART1_EVENT_TYPES | {"HEADSIGN_CHANGED"}
    others: dict[str, int] = {}
    for e in event_set.events:
        if e.type not in covered:
            others[e.type] = others.get(e.type, 0) + 1

    return {
        "files": files,
        "day_types": day_types,
        "meta_events": meta_events,
        "others": [
            {"type": t, "count": n} for t, n in sorted(others.items())
        ],
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

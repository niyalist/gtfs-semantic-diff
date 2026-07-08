"""D群: 停留所レベルのイベント (subject: stop cluster / platform)。

検出条件 (docs/design/ontology.md D群):
- STOP_ADDED / STOP_REMOVED: stop cluster が世代間で対応相手を持たない
  (best confidence < events.accept_confidence)。evidence は構成プラット
  フォームの stops.txt row_added / row_removed。
- STOP_RENAMED: 対応済みクラスタ対で stop_name の field_changed がある。
- STOP_RELOCATED: 対応済みクラスタ対で座標が relocated_threshold_m 超移動
  (stop_lat/stop_lon の field_changed を evidence に)。
- PLATFORM_ADDED / PLATFORM_REMOVED: 対応済みクラスタ内で stop_id 集合が増減。
- PLATFORM_CHANGED: stop_times.txt の stop_id が同一クラスタ内の別
  プラットフォームへ付け替わった (「乗り場変更」)。新旧 stop_id の属する
  クラスタが世代間で対応していることを条件とする。
- ACCESSIBILITY_CHANGED (F群だが停留所属性のためここで処理):
  wheelchair_boarding の field_changed。
"""

from __future__ import annotations

from ...model.matchgraph import ENTITY_STOP_CLUSTER
from ..evidence import EvidenceIndex
from .base import RuleContext

NAME = "stops"


def extract(ctx: RuleContext) -> None:
    threshold_m = ctx.config.get("events", "stops", "relocated_threshold_m", default=300)
    old_clusters = ctx.identity.old_stop_clusters
    new_clusters = ctx.identity.new_stop_clusters

    matched_new: set[str] = set()

    for old_id in sorted(old_clusters):
        old = old_clusters[old_id]
        best = ctx.best_match_for_old(ENTITY_STOP_CLUSTER, old_id)
        if best is None:
            evidence = _row_diffs(ctx.index, old.platform_ids, "row_removed")
            ctx.emit(
                "STOP_REMOVED",
                subject={"stop_cluster": old.base_name, "name": old.name},
                evidence=evidence,
                quantification={"platform_count": len(old.platform_ids)},
                old_ref={"cluster_id": old_id, "platform_ids": sorted(old.platform_ids)},
            )
            continue

        new = new_clusters[best.new_id]
        matched_new.add(best.new_id)
        shared = set(old.platform_ids) & set(new.platform_ids)

        # 改称: 共有プラットフォームの stop_name field_changed
        rename_ids = [
            d.rawdiff_id
            for pid in sorted(shared)
            for d in ctx.index.for_key("stops.txt", pid)
            if d.kind == "field_changed" and d.column == "stop_name"
        ]
        if rename_ids:
            ctx.emit(
                "STOP_RENAMED",
                subject={"stop_cluster": new.base_name},
                evidence=rename_ids,
                old_ref={"name": old.name},
                new_ref={"name": new.name},
                confidence=best.confidence,
            )

        # 移設: 座標 field_changed が閾値超
        reloc_ids = [
            d.rawdiff_id
            for pid in sorted(shared)
            for d in ctx.index.for_key("stops.txt", pid)
            if d.kind == "field_changed" and d.column in ("stop_lat", "stop_lon")
        ]
        if reloc_ids:
            from ...identity.stop_clustering import haversine_m

            moved = haversine_m(old.lat, old.lon, new.lat, new.lon)
            ctx.emit(
                "STOP_RELOCATED" if moved > threshold_m else "PLATFORM_CHANGED",
                subject={"stop_cluster": new.base_name, "name": new.name},
                evidence=reloc_ids,
                quantification={"moved_m": round(moved, 1)},
                confidence=best.confidence,
                severity="info" if moved <= threshold_m else "",
            )

        # プラットフォーム増減 (乗り場の新設・廃止)
        removed_platforms = sorted(set(old.platform_ids) - set(new.platform_ids))
        added_platforms = sorted(set(new.platform_ids) - set(old.platform_ids))
        if removed_platforms:
            ev = _row_diffs(ctx.index, removed_platforms, "row_removed")
            if ev:
                ctx.emit(
                    "PLATFORM_REMOVED",
                    subject={"stop_cluster": new.base_name},
                    evidence=ev,
                    quantification={"platform_ids": removed_platforms},
                    confidence=best.confidence,
                )
        if added_platforms:
            ev = _row_diffs(ctx.index, added_platforms, "row_added")
            if ev:
                ctx.emit(
                    "PLATFORM_ADDED",
                    subject={"stop_cluster": new.base_name},
                    evidence=ev,
                    quantification={"platform_ids": added_platforms},
                    confidence=best.confidence,
                )

        # バリアフリー情報
        wheelchair_ids = [
            d.rawdiff_id
            for pid in sorted(shared)
            for d in ctx.index.for_key("stops.txt", pid)
            if d.kind == "field_changed" and d.column == "wheelchair_boarding"
        ]
        if wheelchair_ids:
            ctx.emit(
                "ACCESSIBILITY_CHANGED",
                subject={"stop_cluster": new.base_name},
                evidence=wheelchair_ids,
                confidence=best.confidence,
            )

    for new_id in sorted(set(new_clusters) - matched_new):
        new = new_clusters[new_id]
        if ctx.best_match_for_new(ENTITY_STOP_CLUSTER, new_id) is not None:
            continue  # 対応済み (多対1で旧側から届いている)
        evidence = _row_diffs(ctx.index, new.platform_ids, "row_added")
        ctx.emit(
            "STOP_ADDED",
            subject={"stop_cluster": new.base_name, "name": new.name},
            evidence=evidence,
            quantification={"platform_count": len(new.platform_ids)},
            new_ref={"cluster_id": new_id, "platform_ids": sorted(new.platform_ids)},
        )


    _platform_reassignments(ctx)


def _platform_reassignments(ctx: RuleContext) -> None:
    """stop_times の stop_id 付け替えのうち同一クラスタ内のもの → PLATFORM_CHANGED。"""
    old_p2c = {
        pid: c for c in ctx.identity.old_stop_clusters.values() for pid in c.platform_ids
    }
    new_p2c = {
        pid: c for c in ctx.identity.new_stop_clusters.values() for pid in c.platform_ids
    }
    grouped: dict[str, list[str]] = {}
    for d in ctx.index.by_file.get("stop_times.txt", []):
        if d.kind != "field_changed" or d.column != "stop_id":
            continue
        if ctx.ledger.primary_event_of(d.rawdiff_id) is not None:
            continue
        old_cluster = old_p2c.get(d.old_value or "")
        new_cluster = new_p2c.get(d.new_value or "")
        if old_cluster is None or new_cluster is None:
            continue
        # 新旧クラスタが対応しているか (基底名一致 or MatchGraph エッジ)
        linked = old_cluster.base_name == new_cluster.base_name or any(
            e.new_id == new_cluster.cluster_id
            for e in ctx.identity.graph.matches_for_old(
                ENTITY_STOP_CLUSTER, old_cluster.cluster_id
            )
            if e.confidence >= ctx.accept_confidence
        )
        if linked:
            grouped.setdefault(new_cluster.base_name, []).append(d.rawdiff_id)

    for base_name in sorted(grouped):
        ctx.emit(
            "PLATFORM_CHANGED",
            subject={"stop_cluster": base_name},
            evidence=grouped[base_name],
            quantification={"stop_time_rows": len(grouped[base_name])},
        )


def _row_diffs(index: EvidenceIndex, platform_ids: list[str], kind: str) -> list[str]:
    return [
        d.rawdiff_id
        for pid in sorted(platform_ids)
        for d in index.for_key("stops.txt", pid)
        if d.kind == kind
    ]

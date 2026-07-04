"""F群: 運賃・形状・メタデータ層 (網羅性の受け皿)。

M3 では説明会計の完成度を優先した粗い粒度で実装する
(運賃表の詳細分解・Fréchet 距離による形状局在化は roadmap M5):

- FARE_CHANGED: fare_attributes.txt / fare_rules.txt の全差分を1イベントで
  消費。quantification に種別ごとの件数を保持。
- SHAPE_CHANGED: shapes.txt 差分を shape_id 単位で消費。subject には
  その shape を使う route family を新旧 trips から引いて付す。
  trips.txt の shape_id field_changed も併せて消費。
- FEED_VALIDITY_CHANGED: feed_info.txt の全差分。
- AGENCY_INFO_CHANGED: agency.txt / agency_jp.txt の全差分。
- TRANSLATION_CHANGED: translations.txt の全差分。
"""

from __future__ import annotations

from collections import defaultdict

from .base import RuleContext

NAME = "metadata"


def extract(ctx: RuleContext) -> None:
    _fare(ctx)
    _shapes(ctx)
    _simple_file(ctx, "FEED_VALIDITY_CHANGED", ["feed_info.txt"])
    _simple_file(ctx, "AGENCY_INFO_CHANGED", ["agency.txt", "agency_jp.txt"])
    _simple_file(ctx, "TRANSLATION_CHANGED", ["translations.txt"])


def _fare(ctx: RuleContext) -> None:
    evidence = ctx.index.file_ids("fare_attributes.txt") + ctx.index.file_ids("fare_rules.txt")
    evidence = ctx.unconsumed_ids(evidence)
    if not evidence:
        return
    kind_counts: dict[str, int] = defaultdict(int)
    for d in ctx.index.by_file.get("fare_attributes.txt", []) + ctx.index.by_file.get(
        "fare_rules.txt", []
    ):
        kind_counts[f"{d.file}:{d.kind}"] += 1
    ctx.emit(
        "FARE_CHANGED",
        subject={"scope": "feed"},
        evidence=evidence,
        quantification=dict(sorted(kind_counts.items())),
    )


def _shapes(ctx: RuleContext) -> None:
    shape_diffs = ctx.index.by_file.get("shapes.txt", [])
    if not shape_diffs:
        return
    # shape_id → 使用 family (新旧 trips から)
    shape_to_families: dict[str, set[str]] = defaultdict(set)
    for snapshot, families in (
        (ctx.old, ctx.identity.old_families),
        (ctx.new, ctx.identity.new_families),
    ):
        trips = snapshot.table("trips")
        if trips is None or "shape_id" not in trips.columns:
            continue
        route_to_family = {
            rid: f.name for f in families.values() for rid in f.route_ids
        }
        for route_id, shape_id in zip(trips["route_id"], trips["shape_id"]):
            if shape_id.strip():
                shape_to_families[shape_id].add(route_to_family.get(route_id, ""))

    by_shape: dict[str, list[str]] = defaultdict(list)
    for d in shape_diffs:
        key = d.key[0] if d.key else ""
        by_shape[key].append(d.rawdiff_id)

    for shape_id in sorted(by_shape):
        evidence = ctx.unconsumed_ids(by_shape[shape_id])
        if not evidence:
            continue
        families = sorted(f for f in shape_to_families.get(shape_id, ()) if f)
        ctx.emit(
            "SHAPE_CHANGED",
            subject={"shape_id": shape_id, "route_families": families},
            evidence=evidence,
            quantification={"rawdiff_count": len(evidence)},
        )

    # trips.txt の shape_id 付け替え
    swap_ids = [
        d.rawdiff_id
        for d in ctx.index.by_file.get("trips.txt", [])
        if d.kind == "field_changed" and d.column == "shape_id"
    ]
    swap_ids = ctx.unconsumed_ids(swap_ids)
    if swap_ids:
        ctx.emit(
            "SHAPE_CHANGED",
            subject={"scope": "trip_shape_assignment"},
            evidence=swap_ids,
            quantification={"trips_changed": len(swap_ids)},
        )


def _simple_file(ctx: RuleContext, type_: str, filenames: list[str]) -> None:
    evidence = []
    changed: dict[str, str] = {}
    for filename in filenames:
        for d in ctx.index.by_file.get(filename, []):
            evidence.append(d.rawdiff_id)
            if d.kind == "field_changed":
                changed[d.column] = f"{d.old_value} → {d.new_value}"
    evidence = ctx.unconsumed_ids(evidence)
    if not evidence:
        return
    ctx.emit(
        type_,
        subject={"files": filenames},
        evidence=evidence,
        quantification={"changed_fields": changed} if changed else {},
    )

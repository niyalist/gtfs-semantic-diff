"""SHAPE_CHANGED 詳細 (B群) と shape_id churn (F群)。

検出条件 (docs/design/ontology.md):
- 両世代に存在する shape_id で shapes.txt に差分がある場合、ポリラインの
  離散 Fréchet 距離を計算し、events.shape.frechet_threshold_m 以上なら
  SHAPE_CHANGED (minor, significant=true)。未満なら点列の振り直し・精度変更
  とみなし SHAPE_CHANGED (info, significant=false)。
- trip の shape_id 付け替え (trips.txt field_changed) で旧→新 shape が
  対応づく場合、幾何が閾値未満なら TECHNICAL_ID_CHURN (shape_id 張り替え)、
  閾値以上なら SHAPE_CHANGED として報告する。
- quantification: frechet_m, max_deviation_m とその位置 (旧経路上の座標)。
  停留所間区間への局在化は将来課題 (現状は最大乖離点の座標で代替)。
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from ...model import GtfsSnapshot
from ..geometry import discrete_frechet_m, downsample, max_deviation
from .base import RuleContext

NAME = "shapes"


def _polylines(snapshot: GtfsSnapshot, max_points: int) -> dict[str, list[tuple[float, float]]]:
    shapes = snapshot.table("shapes")
    if shapes is None or shapes.empty:
        return {}
    df = shapes[["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]].copy()
    df["_seq"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
    df["_lat"] = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
    df["_lon"] = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
    df = df.dropna(subset=["_seq", "_lat", "_lon"]).sort_values(
        ["shape_id", "_seq"], kind="stable"
    )
    result = {}
    for shape_id, group in df.groupby("shape_id", sort=False):
        result[shape_id] = downsample(
            list(zip(group["_lat"], group["_lon"])), max_points
        )
    return result


def _shape_families(ctx: RuleContext) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for snapshot, families in (
        (ctx.old, ctx.identity.old_families),
        (ctx.new, ctx.identity.new_families),
    ):
        trips = snapshot.table("trips")
        if trips is None or "shape_id" not in trips.columns:
            continue
        route_to_family = {rid: f.name for f in families.values() for rid in f.route_ids}
        for route_id, shape_id in zip(trips["route_id"], trips["shape_id"]):
            if shape_id.strip():
                out[shape_id].add(route_to_family.get(route_id, ""))
    return out


def extract(ctx: RuleContext) -> None:
    shape_diffs = ctx.index.by_file.get("shapes.txt", [])
    swap_diffs = [
        d
        for d in ctx.index.by_file.get("trips.txt", [])
        if d.kind == "field_changed" and d.column == "shape_id"
    ]
    if not shape_diffs and not swap_diffs:
        return

    threshold = ctx.config.get("events", "shape", "frechet_threshold_m", default=150)
    max_points = ctx.config.get("events", "shape", "max_polyline_points", default=200)
    old_lines = _polylines(ctx.old, max_points)
    new_lines = _polylines(ctx.new, max_points)
    families = _shape_families(ctx)

    by_shape: dict[str, list[str]] = defaultdict(list)
    for d in shape_diffs:
        by_shape[d.key[0] if d.key else ""].append(d.rawdiff_id)

    # trip の shape 付け替えマッピング (旧 shape → 新 shape の最頻)
    swap_pairs = Counter()
    swap_ids_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in swap_diffs:
        pair = (d.old_value or "", d.new_value or "")
        swap_pairs[pair] += 1
        swap_ids_by_pair[pair].append(d.rawdiff_id)

    def geometry_quant(old_id: str, new_id: str) -> dict | None:
        a, b = old_lines.get(old_id), new_lines.get(new_id)
        if not a or not b:
            return None
        frechet = discrete_frechet_m(a, b)
        deviation, at = max_deviation(a, b)
        q = {"frechet_m": round(frechet, 1), "max_deviation_m": round(deviation, 1)}
        if at:
            q["max_deviation_at"] = [round(at[0], 6), round(at[1], 6)]
        return q

    # 1) 付け替えペア: 幾何比較で churn / 実変更を判別
    for (old_id, new_id), count in sorted(swap_pairs.items()):
        evidence = ctx.unconsumed_ids(
            swap_ids_by_pair[(old_id, new_id)]
            + by_shape.get(old_id, [])
            + by_shape.get(new_id, [])
        )
        if not evidence:
            continue
        quant = geometry_quant(old_id, new_id)
        fams = sorted(f for f in families.get(new_id, families.get(old_id, set())) if f)
        if quant is not None and quant["frechet_m"] < threshold:
            ctx.emit(
                "TECHNICAL_ID_CHURN",
                subject={"entity": "shape_id", "route_families": fams},
                evidence=evidence,
                quantification={**quant, "old_shape": old_id, "new_shape": new_id,
                                "trips_changed": count},
            )
        else:
            ctx.emit(
                "SHAPE_CHANGED",
                subject={"shape_id": new_id or old_id, "route_families": fams},
                evidence=evidence,
                quantification={**(quant or {}), "significant": True,
                                "old_shape": old_id, "new_shape": new_id},
            )

    # 2) 同一 shape_id の変形 (field/row 差分)
    for shape_id in sorted(by_shape):
        evidence = ctx.unconsumed_ids(by_shape[shape_id])
        if not evidence:
            continue
        fams = sorted(f for f in families.get(shape_id, set()) if f)
        quant = geometry_quant(shape_id, shape_id)
        significant = quant is None or quant["frechet_m"] >= threshold
        ctx.emit(
            "SHAPE_CHANGED",
            subject={"shape_id": shape_id, "route_families": fams},
            evidence=evidence,
            quantification={**(quant or {}), "significant": significant},
            severity="minor" if significant else "info",
        )

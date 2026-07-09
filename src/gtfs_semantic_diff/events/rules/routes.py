"""A群: 路線・系統レベルのイベント (subject: route family)。

検出条件 (docs/design/ontology.md A群、M9 で内容主導化):
- ROUTE_RENAMED / ROUTE_MERGED / ROUTE_SPLIT / ROUTE_RESTRUCTURED:
  identity の family 対応成分 (identity.family_components — 翻訳済み
  停留所集合 Jaccard による受理エッジの連結成分) を形で分類して発火。
  1:1=改称 / N:1=統合 / 1:N=分割 / N:M=再編。降格成分 (demoted) は対象外
  (廃止/新設 + 類似候補注記に落ちる)。ADDED/DISCONTINUED より先に確定。
- ROUTE_DISCONTINUED / ROUTE_ADDED: 上記でも対応しなかった family の消滅・出現。
  evidence は routes.txt の行と、その family に属する trip の
  trips.txt / stop_times.txt 行のカスケード。
- TECHNICAL_ID_CHURN (route_id 張り替え): 対応済み family 内で route_id
  集合だけが変わった場合。routes.txt の行差分と trips.txt の route_id
  field_changed を消費する。
- THROUGH_SERVICE_*: 未実装 (detection.md §7)。
"""

from __future__ import annotations

from ...model.matchgraph import ENTITY_ROUTE_FAMILY
from .base import RuleContext

NAME = "routes"

# 成分の形 → イベントタイプ
_SHAPE_EVENT = {
    "renamed": "ROUTE_RENAMED",
    "merged": "ROUTE_MERGED",
    "split": "ROUTE_SPLIT",
    "restructured": "ROUTE_RESTRUCTURED",
}


def _family_trip_ids(trips_by_family: dict[str, list[str]], family: str) -> list[str]:
    return trips_by_family.get(family, [])


def _all_irregular(trips: dict, trip_ids: list[str]) -> bool:
    day_types = {trips[t].day_type for t in trip_ids if t in trips}
    return bool(day_types) and day_types == {"irregular"}


def _classify_disappearance(trips: dict, trip_ids: list[str]) -> tuple[str, float]:
    if _all_irregular(trips, trip_ids):
        return "SEASONAL_SERVICE_CHANGED", 0.6
    return "ROUTE_DISCONTINUED", 1.0


def _classify_appearance(trips: dict, trip_ids: list[str]) -> tuple[str, float]:
    if _all_irregular(trips, trip_ids):
        return "SEASONAL_SERVICE_CHANGED", 0.6
    return "ROUTE_ADDED", 1.0


def extract(ctx: RuleContext) -> None:
    old_families = ctx.identity.old_families
    new_families = ctx.identity.new_families

    old_trips_by_family: dict[str, list[str]] = {}
    for t in ctx.trip_delta.old_trips.values():
        old_trips_by_family.setdefault(t.family, []).append(t.trip_id)
    new_trips_by_family: dict[str, list[str]] = {}
    for t in ctx.trip_delta.new_trips.values():
        new_trips_by_family.setdefault(t.family, []).append(t.trip_id)

    handled_old: set[str] = set()
    handled_new: set[str] = set()

    # 1) family 対応成分 (M9) を形で分類して先に確定。
    #    成分は名称一致エッジも含みうる (例: 旧A+旧B → 新A の吸収統合)。
    #    改称・再編に伴う trips.txt の route_id 付け替えもここで消費する
    for comp in ctx.identity.family_components:
        if comp["demoted"]:
            continue  # 破滅回避で注記に降格 (廃止/新設 + 類似候補注記へ)
        renamed_old = [f for f in comp["old"] if f not in new_families]
        renamed_new = [f for f in comp["new"] if f not in old_families]
        route_ids = sorted(
            {rid for f in comp["old"] for rid in old_families[f].route_ids}
            | {rid for f in comp["new"] for rid in new_families[f].route_ids}
        )
        evidence = [
            d.rawdiff_id
            for rid in route_ids
            for d in ctx.index.for_key("routes.txt", rid)
        ]
        # 改称した family に属する trip の route_id 変更 (中身は trip 対応側で説明)
        for f in renamed_new:
            evidence += [
                d.rawdiff_id
                for tid in sorted(_family_trip_ids(new_trips_by_family, f))
                for d in ctx.index.for_key("trips.txt", tid)
                if d.kind == "field_changed" and d.column == "route_id"
            ]
        type_ = _SHAPE_EVENT[comp["shape"]]
        if type_ == "ROUTE_RENAMED":
            subject = {"route_family": comp["new"][0]}
            old_ref = {"name": comp["old"][0],
                       "route_ids": sorted(old_families[comp["old"][0]].route_ids)}
            new_ref = {"name": comp["new"][0],
                       "route_ids": sorted(new_families[comp["new"][0]].route_ids)}
        else:
            subject = ({"route_family": comp["new"][0]} if len(comp["new"]) == 1
                       else {"route_families": comp["new"]})
            old_ref = {"names": comp["old"]}
            new_ref = {"names": comp["new"]}
        ctx.emit(
            type_,
            subject=subject,
            evidence=evidence,
            old_ref=old_ref,
            new_ref=new_ref,
            quantification={"stop_set_similarity": comp["similarity"]},
            confidence=comp["similarity"],
        )
        handled_old.update(renamed_old)
        handled_new.update(renamed_new)

    # 2) 対応済み family の route_id 張り替え (TECHNICAL_ID_CHURN)
    name_matched = {
        e.old_id
        for e in ctx.identity.graph.for_type(ENTITY_ROUTE_FAMILY)
        if e.method == "name_exact"
    }
    for name in sorted(name_matched):
        old_f, new_f = old_families[name], new_families[name]
        removed_rids = sorted(set(old_f.route_ids) - set(new_f.route_ids))
        added_rids = sorted(set(new_f.route_ids) - set(old_f.route_ids))
        if not removed_rids and not added_rids:
            continue
        evidence = [
            d.rawdiff_id
            for rid in removed_rids + added_rids
            for d in ctx.index.for_key("routes.txt", rid)
        ]
        # family 所属 trip の route_id 付け替え
        evidence += [
            d.rawdiff_id
            for tid in sorted(_family_trip_ids(new_trips_by_family, name))
            for d in ctx.index.for_key("trips.txt", tid)
            if d.kind == "field_changed" and d.column == "route_id"
        ]
        if evidence:
            ctx.emit(
                "TECHNICAL_ID_CHURN",
                subject={"route_family": name, "entity": "route_id"},
                evidence=evidence,
                quantification={
                    "removed_route_ids": removed_rids,
                    "added_route_ids": added_rids,
                },
            )

    # 3) 消滅 family → ROUTE_DISCONTINUED (trip カスケードごと消費)。
    #    全 trip が特定日運行 (day_type=irregular) の family は季節・期間限定
    #    サービスの消滅の可能性が高いため SEASONAL_SERVICE_CHANGED として
    #    報告する (confidence 0.6 の仮説。例: 冬季限定の観光路線)。
    for name in sorted(old_families.keys() - new_families.keys() - handled_old):
        old_f = old_families[name]
        trip_ids = _family_trip_ids(old_trips_by_family, name)
        evidence = [
            d.rawdiff_id
            for rid in sorted(old_f.route_ids)
            for d in ctx.index.for_key("routes.txt", rid)
        ] + ctx.index.trip_cascade_ids(trip_ids)
        type_, confidence = _classify_disappearance(ctx.trip_delta.old_trips, trip_ids)
        ctx.emit(
            type_,
            subject={"route_family": name},
            evidence=evidence,
            old_ref={"route_ids": sorted(old_f.route_ids), "trip_count": len(trip_ids)},
            quantification={"trip_count": len(trip_ids), "change": "disappeared"},
            confidence=confidence,
        )

    # 4) 出現 family → ROUTE_ADDED (同様に特定日のみなら SEASONAL)
    for name in sorted(new_families.keys() - old_families.keys() - handled_new):
        new_f = new_families[name]
        trip_ids = _family_trip_ids(new_trips_by_family, name)
        evidence = [
            d.rawdiff_id
            for rid in sorted(new_f.route_ids)
            for d in ctx.index.for_key("routes.txt", rid)
        ] + ctx.index.trip_cascade_ids(trip_ids)
        type_, confidence = _classify_appearance(ctx.trip_delta.new_trips, trip_ids)
        ctx.emit(
            type_,
            subject={"route_family": name},
            evidence=evidence,
            new_ref={"route_ids": sorted(new_f.route_ids), "trip_count": len(trip_ids)},
            quantification={"trip_count": len(trip_ids), "change": "appeared"},
            confidence=confidence,
        )

    # 5) 対応済み family 内の routes.txt field_changed (長名変更等) → ROUTE_RENAMED (minor)
    for name in sorted(name_matched):
        shared_rids = sorted(
            set(old_families[name].route_ids) & set(new_families[name].route_ids)
        )
        name_ids = [
            d.rawdiff_id
            for rid in shared_rids
            for d in ctx.index.for_key("routes.txt", rid)
            if d.kind == "field_changed"
            and d.column in ("route_short_name", "route_long_name")
        ]
        if name_ids:
            ctx.emit(
                "ROUTE_RENAMED",
                subject={"route_family": name},
                evidence=name_ids,
                quantification={"scope": "route_long_name"},
            )

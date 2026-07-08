"""コアパイプライン: GtfsSnapshot 2つ → ChangeEventSet (純粋関数)。

L0 (diff0) → L1 (identity) → L2 (ルールカスケード) → 説明会計 → 残差。
"""

from __future__ import annotations

import datetime
import logging

from ..config import Config
from ..diff0 import enumerate_rawdiffs
from ..identity import build_identity
from ..identity.route_family import route_to_family_map
from ..model import ChangeEventSet, GtfsSnapshot, RawDiffSet
from .accounting import EvidenceLedger
from .evidence import EvidenceIndex
from .rules import CASCADE
from .rules.base import RuleContext
from .timebands import TimeBands
from .tripdelta import build_trip_delta, collect_trips

logger = logging.getLogger(__name__)


def compare_snapshots(
    old: GtfsSnapshot, new: GtfsSnapshot, config: Config
) -> tuple[ChangeEventSet, RawDiffSet]:
    """世代ペアを比較し、(ChangeEventSet, RawDiff 全件) を返す。"""
    event_set, rawdiffs, _, _ = compare_snapshots_with_artifacts(old, new, config)
    return event_set, rawdiffs


def compare_snapshots_with_artifacts(old: GtfsSnapshot, new: GtfsSnapshot, config: Config):
    """compare_snapshots + 中間成果物 (identity, trip_delta)。

    戻り値: (ChangeEventSet, RawDiffSet, IdentityResult, TripDelta)。
    HTML バンドル生成 (report/bundle.py) など、幾何や時刻表の素材を必要とする
    消費者向け。JSON の安定インタフェースには影響しない。
    """
    rawdiffs = enumerate_rawdiffs(old, new)
    ledger = EvidenceLedger(rawdiffs)
    index = EvidenceIndex(rawdiffs)

    identity = build_identity(old, new, config)

    old_stop_to_base = {
        pid: c.base_name
        for c in identity.old_stop_clusters.values()
        for pid in c.platform_ids
    }
    new_stop_to_base = {
        pid: c.base_name
        for c in identity.new_stop_clusters.values()
        for pid in c.platform_ids
    }
    # family の世代間対応 (名称変更を含む) を trip 対応付けのブロッキングに渡す
    from ..model.matchgraph import ENTITY_ROUTE_FAMILY

    accept = config.get("events", "accept_confidence", default=0.5)
    family_links = {
        e.old_id: e.new_id
        for e in identity.graph.for_type(ENTITY_ROUTE_FAMILY)
        if e.confidence >= accept
    }
    trip_delta = build_trip_delta(
        collect_trips(old, route_to_family_map(identity.old_families), old_stop_to_base),
        collect_trips(new, route_to_family_map(identity.new_families), new_stop_to_base),
        config=config,
        family_links=family_links,
        old_family_group=identity.old_family_to_group,
        new_family_group=identity.new_family_to_group,
    )

    ctx = RuleContext(
        old=old,
        new=new,
        config=config,
        identity=identity,
        rawdiffs=rawdiffs,
        index=index,
        ledger=ledger,
        trip_delta=trip_delta,
        time_bands=TimeBands(
            config.get("events", "frequency", "time_bands", default=[])
        ),
    )
    for rule in CASCADE:
        before = len(ctx.events)
        rule.extract(ctx)
        logger.info("rule %s: %d イベント", rule.NAME, len(ctx.events) - before)

    events = list(ctx.events)
    events += ledger.residual_events(event_id_start=len(events) + 1)
    accounting = ledger.accounting()

    # subject に route_group (路線ブランド) を付与。新世代の対応を優先
    family_to_group = {**identity.old_family_to_group, **identity.new_family_to_group}
    for e in events:
        family = e.subject.get("route_family")
        if family and family in family_to_group:
            e.subject["route_group"] = family_to_group[family]
    logger.info(
        "explained_ratio = %.4f (%d / %d)",
        accounting.explained_ratio,
        accounting.explained,
        accounting.rawdiff_total,
    )

    event_set = ChangeEventSet(
        feed={
            "org_id": new.meta.org_id or old.meta.org_id,
            "feed_id": new.meta.feed_id or old.meta.feed_id,
            "old_rid": old.meta.rid,
            "new_rid": new.meta.rid,
            "old_source": old.meta.source,
            "new_source": new.meta.source,
            "old_period": [old.meta.from_date, old.meta.to_date],
            "new_period": [new.meta.from_date, new.meta.to_date],
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        config_snapshot=config.raw,
        events=events,
        accounting=accounting,
        context={
            "band_profiles": _band_profiles(ctx, family_to_group),
            "route_groups": _route_groups_context(identity),
            "family_structure": _family_structure(identity, config),
        },
    )
    return event_set, rawdiffs, identity, trip_delta


def _band_profiles(ctx: RuleContext, family_to_group: dict[str, str]) -> list[dict]:
    """(family, 方向, day_type) ごとの時間帯別本数 (旧→新)。レポートの本数表用。"""
    profiles: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    for trips, side in ((ctx.trip_delta.old_trips, 0), (ctx.trip_delta.new_trips, 1)):
        for t in trips.values():
            key = (t.family, t.direction, t.day_type)
            bands = profiles.setdefault(key, {})
            band = ctx.time_bands.band_of(t.first_departure)
            bands.setdefault(band, [0, 0])[side] += 1
    return [
        {
            "route_family": family,
            "route_group": family_to_group.get(family, family),
            "direction": direction,
            "day_type": day_type,
            "bands": {b: counts for b, counts in sorted(bands.items())},
        }
        for (family, direction, day_type), bands in sorted(profiles.items())
    ]


def _route_groups_context(identity) -> list[dict]:
    """route_group の構成と凝集度 (新世代優先、旧のみの group も含める)。"""
    merged: dict[str, dict] = {}
    for group in identity.old_groups + identity.new_groups:  # 後勝ち = 新世代優先
        entry = merged.setdefault(group.name, {"name": group.name, "families": set()})
        entry["families"] |= set(group.families)
        entry["cohesion"] = group.cohesion
    return [
        {"name": g["name"], "families": sorted(g["families"]), "cohesion": g.get("cohesion")}
        for g in sorted(merged.values(), key=lambda g: g["name"])
    ]


def _family_structure(identity, config: Config) -> list[dict]:
    """family 内の運行系統構成 (低凝集 family のレポート小見出し分割用)。

    2 クラスタ以上を持つ family について、各クラスタの区間ラベルと
    クラスタ間の停留所集合 Jaccard の最小値を出す。新世代優先。
    """
    from ..identity.route_group import stop_jaccard

    min_trips = config.get("identity", "route_group", "structure_min_trips", default=2)
    by_family: dict[str, list] = {}
    seen_new = set()
    for c in identity.new_pattern_clusters:
        if c.trip_count >= min_trips:
            by_family.setdefault(c.family, []).append(c)
            seen_new.add(c.family)
    for c in identity.old_pattern_clusters:  # 旧のみの family (廃止路線) を補完
        if c.family not in seen_new and c.trip_count >= min_trips:
            by_family.setdefault(c.family, []).append(c)

    result = []
    for family in sorted(by_family):
        clusters = by_family[family]
        if len(clusters) < 2:
            continue
        stop_sets = [set(c.representative.base_names) for c in clusters]
        min_j = min(
            stop_jaccard(a, b)
            for i, a in enumerate(stop_sets)
            for b in stop_sets[i + 1:]
        )
        result.append(
            {
                "route_family": family,
                "min_cluster_jaccard": round(min_j, 4),
                "clusters": [
                    {
                        "direction": c.direction,
                        "first_stop": c.representative.base_names[0],
                        "last_stop": c.representative.base_names[-1],
                        "stop_count": len(c.representative.base_names),
                        "trip_count": c.trip_count,
                    }
                    for c in sorted(clusters, key=lambda c: -c.trip_count)
                ],
            }
        )
    return result

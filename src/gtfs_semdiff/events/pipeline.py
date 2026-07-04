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
    trip_delta = build_trip_delta(
        collect_trips(old, route_to_family_map(identity.old_families), old_stop_to_base),
        collect_trips(new, route_to_family_map(identity.new_families), new_stop_to_base),
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
        context={"band_profiles": _band_profiles(ctx)},
    )
    return event_set, rawdiffs


def _band_profiles(ctx: RuleContext) -> list[dict]:
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
            "direction": direction,
            "day_type": day_type,
            "bands": {b: counts for b, counts in sorted(bands.items())},
        }
        for (family, direction, day_type), bands in sorted(profiles.items())
    ]

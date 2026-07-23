"""コアパイプライン: GtfsSnapshot 2つ → ChangeEventSet (純粋関数)。

L0 (diff0) → L1 (identity) → L2 (ルールカスケード) → 説明台帳 → 残差。
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
from .tripdelta import TripInfo, build_trip_delta, collect_trips
from .windows import (
    WindowScope,
    comparison_units,
    known_services,
    superset_unit,
)

logger = logging.getLogger(__name__)


def _regular_day_type(day_type: str | None) -> bool:
    """週次レギュラー型 (平日/土曜/日祝/週末/毎日/dow_*) か。

    特定日 (irregular)・運行日なし (inactive) は「特定日世界同士の比較」が
    従来から成立しているため、窓の外にあっても比較対象から外さない
    (名古屋の年次アーカイブペアで検証 — service_days.md §2.2)。"""
    return day_type is not None and day_type not in ("irregular", "inactive")


def _covered_enough(families: set[str], covered: set[str], coverage_min: float) -> bool:
    """service の路線ブロックが後継側にどれだけカバーされているか (≥ 閾値)。

    厳密包含 (1.0) を要求すると、改正時に family 名の対応が切れる再編
    (伊勢市おかげバス「環状線 → 右回り/左回り」で M9 対応が名前一致の持ち越し
    世代側に付く) で後継を見逃す。閾値は config `[events.windows]
    carryover_coverage_min`。"""
    if not families:
        return False
    return len(families & covered) / len(families) >= coverage_min


def _resolve_window_scope(
    old: GtfsSnapshot,
    new: GtfsSnapshot,
    old_trips: dict[str, TripInfo],
    new_trips: dict[str, TripInfo],
    old_family_block: dict[str, str],
    new_family_block: dict[str, str],
    coverage_min: float = 0.8,
) -> WindowScope | None:
    """SD2 (窓内区間対比較): 比較スコープを解決する。None = 全便比較 (退化)。

    docs/design/service_days.md §2.2。比較対象から外すのは次の2種だけ:
    (a) 共通窓内に実効運行日を持たない週次レギュラー型 service (期限切れ・
        将来世代。特定日型は除外しない — 特定日世界同士の比較は従来どおり)
    (b) 内容同一ユニットの「持ち越しコピー」(同居世代のうち、変化のある
        ユニットに現れない側の service — 桑名 実測2 の新側旧世代コピー)
    単一世代フィード同士・期間端がずれているだけの通常フィードでは None を
    返し、現行挙動に完全一致する。"""
    from collections import Counter

    window, intervals, units = comparison_units(old, new)
    if window is None or not units:
        return None

    old_known = known_services(old)
    new_known = known_services(new)
    old_active_any = frozenset().union(*(u.old_services for u in units))
    new_active_any = frozenset().union(*(u.new_services for u in units))

    def families_by_service(snapshot, trip_infos, family_block):
        """service_id → 便が属する路線ブロック集合 (family の世代間対応成分)。

        route_id は世代サフィックスで張り替わる (桑名 `3_101_20260601` →
        `3_101_20260711`) ため後継判定は内容主導の family で行い、さらに
        改称・分割・統合を跨いで束ねるため対応成分 (route_group ブロック、M9)
        の粒度に落とす — 伊勢市おかげバスの「環状線 → 右回り/左回り」分割を
        後継として認識するため (ID は弱い事前 — M8/M9 と同じ原則)。"""
        trips = snapshot.table("trips")
        if trips is None or trips.empty:
            return {}
        result: dict[str, set[str]] = {}
        for tid, rid, sid in zip(
            trips["trip_id"], trips["route_id"], trips["service_id"]
        ):
            info = trip_infos.get(str(tid))
            family = info.family if info and info.family else str(rid)
            result.setdefault(str(sid), set()).add(family_block.get(family, family))
        return result

    def window_excluded(snapshot, trip_infos, family_block, known, active_any):
        """(a) 期限切れ・将来世代の service。次の両方を満たすものだけ:
        - 週次レギュラー型 (特定日世界は従来どおり比較する — 名古屋の年次ペア)
        - その service の全路線 (family) が、同じ側の窓内 active service でも
          運行されている (= 後継世代が存在する。後継がない路線 — 集約フィードで
          路線ごとに時刻表の掲載期限が違う佐賀の三瀬神埼線 — は従来どおり比較する)"""
        by_service = families_by_service(snapshot, trip_infos, family_block)
        covered: set[str] = set()
        for s in active_any:
            covered |= by_service.get(s, set())
        return frozenset(
            s for s in known - active_any
            if _regular_day_type(snapshot.day_types.get(s))
            and _covered_enough(by_service.get(s, set()), covered, coverage_min)
        )

    a_old = window_excluded(old, old_trips, old_family_block, old_known, old_active_any)
    a_new = window_excluded(new, new_trips, new_family_block, new_known, new_active_any)

    # ユニットの変化判定 (内容シグネチャの多重集合比較) と primary の決定
    identical: tuple = ()
    b_old: frozenset[str] = frozenset()
    b_new: frozenset[str] = frozenset()
    primary = superset_unit(units)
    if primary is None and len(units) > 1:

        def service_of(snapshot):
            trips = snapshot.table("trips")
            return dict(zip(trips["trip_id"], trips["service_id"]))

        old_service_of = service_of(old)
        new_service_of = service_of(new)

        def sig_counter(trips, service_of, services):
            return Counter(
                t.signature for tid, t in trips.items()
                if str(service_of.get(tid, "")) in services
            )

        changed = [
            u for u in units
            if sig_counter(old_trips, old_service_of, u.old_services)
            != sig_counter(new_trips, new_service_of, u.new_services)
        ]
        identical = tuple(
            iv for u in units if u not in changed for iv in u.intervals
        )
        pool = changed or units
        primary = max(pool, key=lambda u: (u.days(), u.start().toordinal()))
        if changed:
            # (b) 世代同梱の「持ち越し世代」: primary の便世界に現れない
            #     レギュラー型 service のうち、同じ側の primary 世代に family
            #     後継があるもの ((a) と同じ後継原則)。厳密な内容同一は要求
            #     しない — 実データでは持ち越し世代にも乗り場 ID 張り替え等の
            #     編集が入る (伊勢市おかげバス prev_2 で実証)。
            #     後継のない service (補完期間の内容 — 佐賀の年末年始等) と
            #     特定日型は残し、従来どおり比較する
            def carryover(snapshot, trip_infos, family_block, active_any, primary_side):
                by_service = families_by_service(snapshot, trip_infos, family_block)
                covered: set[str] = set()
                for s in primary_side:
                    covered |= by_service.get(s, set())
                return frozenset(
                    s for s in active_any - primary_side
                    if _regular_day_type(snapshot.day_types.get(s))
                    and _covered_enough(by_service.get(s, set()), covered, coverage_min)
                )

            b_old = carryover(
                old, old_trips, old_family_block, old_active_any, primary.old_services
            )
            b_new = carryover(
                new, new_trips, new_family_block, new_active_any, primary.new_services
            )
    elif primary is None:
        primary = units[0]

    if not (a_old or a_new or b_old or b_new):
        return None  # 除外なし = 現行挙動

    def excluded_trips(snapshot, excluded):
        trips = snapshot.table("trips")
        if trips is None or trips.empty:
            return frozenset()
        return frozenset(
            str(tid) for tid, sid in zip(trips["trip_id"], trips["service_id"])
            if str(sid) in excluded
        )

    old_excluded = a_old | b_old
    new_excluded = a_new | b_new
    return WindowScope(
        window=window,
        intervals=tuple(intervals),
        primary_intervals=primary.intervals,
        identical_intervals=identical,
        old_universe=old_active_any - b_old,
        new_universe=new_active_any - b_new,
        old_excluded_services=old_excluded,
        new_excluded_services=new_excluded,
        old_excluded_trips=excluded_trips(old, old_excluded),
        new_excluded_trips=excluded_trips(new, new_excluded),
        multi_generation=len(units) > 1,
    )


def _filter_trips(
    trips: dict[str, TripInfo], excluded_trip_ids: frozenset[str]
) -> dict[str, TripInfo]:
    if not excluded_trip_ids:
        return trips
    return {tid: t for tid, t in trips.items() if tid not in excluded_trip_ids}


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
    rawdiffs = enumerate_rawdiffs(old, new, config)
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
    # family の世代間対応 (改称・統合・分割を含む) を trip 対応付けの
    # ブロッキングに渡す。成分で束ねた route_group がブロック (M9)
    from ..identity.builder import blocking_family_maps

    old_family_block, new_family_block = blocking_family_maps(identity)
    old_trips_all = collect_trips(
        old, route_to_family_map(identity.old_families), old_stop_to_base
    )
    new_trips_all = collect_trips(
        new, route_to_family_map(identity.new_families), new_stop_to_base
    )
    # SD2 (窓内区間対比較): 同梱世代があるフィードでは比較の便世界を
    # primary 区間の世代に絞る。通常フィードでは scope=None (現行挙動)
    scope = _resolve_window_scope(
        old, new, old_trips_all, new_trips_all, old_family_block, new_family_block,
        coverage_min=config.get(
            "events", "windows", "carryover_coverage_min", default=0.8
        ),
    )
    if scope is not None:
        logger.info(
            "window scope: 窓 %s, primary %s, 除外 old %d / new %d service",
            scope.window.as_text(),
            [iv.as_text() for iv in scope.primary_intervals],
            len(scope.old_excluded_services),
            len(scope.new_excluded_services),
        )
        old_trips_all = _filter_trips(old_trips_all, scope.old_excluded_trips)
        new_trips_all = _filter_trips(new_trips_all, scope.new_excluded_trips)
    trip_delta = build_trip_delta(
        old_trips_all,
        new_trips_all,
        config=config,
        old_family_block=old_family_block,
        new_family_block=new_family_block,
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
        window_scope=scope,
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
            # uid = gtfs-data.jp の世代恒久 UUID (rid は取得時点の相対 ID)。
            # 再比較・正準 URL の同定はこちらを正とする (W3-2a)
            "old_uid": old.meta.uid,
            "new_uid": new.meta.uid,
            "old_source": old.meta.source,
            "new_source": new.meta.source,
            "old_period": [old.meta.from_date, old.meta.to_date],
            "new_period": [new.meta.from_date, new.meta.to_date],
            "old_published_at": old.meta.published_at,
            "new_published_at": new.meta.published_at,
            "feed_license": new.meta.feed_license or old.meta.feed_license,
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        config_snapshot=config.raw,
        events=events,
        accounting=accounting,
        context={
            "band_profiles": _band_profiles(ctx, family_to_group),
            "route_groups": _route_groups_context(identity),
            "family_structure": _family_structure(identity, config),
            "comparison_scope": _scope_context(scope),
        },
    )
    return event_set, rawdiffs, identity, trip_delta


def _scope_context(scope: WindowScope | None) -> dict | None:
    """比較スコープの context 表現 (SD2)。None = 全便比較 (従来どおり)。"""
    if scope is None:
        return None
    return {
        "comparison_window": list(scope.window.as_text()),
        "intervals": [list(iv.as_text()) for iv in scope.intervals],
        "primary_periods": [list(iv.as_text()) for iv in scope.primary_intervals],
        "identical_periods": [list(iv.as_text()) for iv in scope.identical_intervals],
        "excluded": {
            "old_services": sorted(scope.old_excluded_services),
            "new_services": sorted(scope.new_excluded_services),
            "old_trips": len(scope.old_excluded_trips),
            "new_trips": len(scope.new_excluded_trips),
        },
    }


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

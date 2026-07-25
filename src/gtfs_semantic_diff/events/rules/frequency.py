"""C群: 便数・時刻レベルのイベント (subject: family × 方向 × 運行日種別 × 時間帯)。

trip_id の連続性は仮定しない (trip_delta が内容署名で照合済み)。

検出条件 (docs/design/ontology.md C群):
- SERVICE_REDUCED / SERVICE_INCREASED: 対応済み family の (方向, day_type)
  グループで、時間帯ビンごとの本数が増減。evidence はそのビンに属する
  removed / added trip の trips + stop_times 行 (カスケード消費)。
  通勤帯 (events.frequency.major_bands) の減便は severity=major。
- 本数同数でも同ビン内で trip の入れ替えがある場合は「時刻変更」として
  TIMETABLE_SHIFTED (uniform=false) で計上する。
- FIRST_LAST_CHANGED: グループの始発・終発が first_last_threshold_min 分を
  超えて変化 (evidence は該当ビンのイベントが主消費するため secondary)。
- TIMETABLE_SHIFTED (uniform): 同一 trip_id で全停留所の時刻が一様に
  シフト (標準偏差 ≤ uniform_shift_max_std_sec)。
- TRAVEL_TIME_CHANGED: 同一 trip_id で時刻が非一様に変化 (区間別の詳細
  quantification は M5)。

A群が消費済みの trip (廃止/新設路線のカスケード) はプールから除外される。
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from ..timebands import parse_gtfs_time
from ..tripdelta import TripInfo
from .base import RuleContext

NAME = "frequency"


def _group_key(t: TripInfo) -> tuple[str, str, str]:
    return (t.family, t.direction, t.day_type)


def extract(ctx: RuleContext) -> None:
    _band_events(ctx)
    _modified_trip_events(ctx)


# --- 便数 (removed/added プール) ---


def _band_events(ctx: RuleContext) -> None:
    major_bands = set(
        ctx.config.get("events", "frequency", "major_bands", default=[])
    )
    threshold_min = ctx.config.get(
        "events", "frequency", "first_last_threshold_min", default=15
    )

    # A群未消費の removed/added trip をグループ × ビンに集計
    pools: dict[tuple, dict[str, dict[str, list[TripInfo]]]] = defaultdict(
        lambda: defaultdict(lambda: {"removed": [], "added": []})
    )
    for t in ctx.trip_delta.removed:
        if _already_claimed(ctx, t):
            continue
        pools[_group_key(t)][ctx.time_bands.band_of(t.first_departure)]["removed"].append(t)
    for t in ctx.trip_delta.added:
        if _already_claimed(ctx, t):
            continue
        pools[_group_key(t)][ctx.time_bands.band_of(t.first_departure)]["added"].append(t)

    # グループ別総数・(グループ, ビン) 別本数・始発時刻列は1パスで事前集計する。
    # グループ毎に全 trip を再走査すると O(グループ数 × trip数) となり、
    # 大規模フィードでルール段が非線形化する (IN-1)。
    # SD5: 複数世界ラベルは世界 ID 付きでも集計する (キー末尾に world)
    wc = ctx.day_worlds
    group_totals: tuple[Counter, Counter] = (Counter(), Counter())
    band_counts: tuple[Counter, Counter] = (Counter(), Counter())
    deps: tuple[dict[tuple, list[int]], dict[tuple, list[int]]] = (
        defaultdict(list),
        defaultdict(list),
    )
    world_totals: tuple[Counter, Counter] = (Counter(), Counter())
    world_band: tuple[Counter, Counter] = (Counter(), Counter())
    world_deps: tuple[dict[tuple, list[int]], dict[tuple, list[int]]] = (
        defaultdict(list),
        defaultdict(list),
    )

    def _world_of(side: int, t: TripInfo) -> str:
        if wc is None:
            return ""
        return (wc.new if side else wc.old).world_of(t.service_id)

    for side, trips in enumerate((ctx.trip_delta.old_trips, ctx.trip_delta.new_trips)):
        for t in trips.values():
            g = _group_key(t)
            band = ctx.time_bands.band_of(t.first_departure)
            group_totals[side][g] += 1
            band_counts[side][(g, band)] += 1
            sec = parse_gtfs_time(t.first_departure)
            if sec is not None:
                deps[side][g].append(sec)
            if wc is not None and t.day_type in (
                (wc.new if side else wc.old).multi_labels
            ):
                w = _world_of(side, t)
                world_totals[side][(g, w)] += 1
                world_band[side][(g, w, band)] += 1
                if sec is not None:
                    world_deps[side][(g, w)].append(sec)

    def _emit_band_events(group, old_key, new_key,
                          old_total, new_total, removed_pool, added_pool,
                          old_deps_list, new_deps_list):
        """1比較セル分のビン別イベント (従来ロジックをセルに射影)。"""
        family, direction, day_type = group
        for band in ctx.time_bands.labels():
            removed = [t for t in removed_pool
                       if ctx.time_bands.band_of(t.first_departure) == band]
            added = [t for t in added_pool
                     if ctx.time_bands.band_of(t.first_departure) == band]
            if not removed and not added:
                continue
            evidence = ctx.index.trip_cascade_ids(
                [t.trip_id for t in removed]
            ) + ctx.index.trip_cascade_ids([t.trip_id for t in added])
            old_n = old_key(band)
            new_n = new_key(band)
            subject = {
                "route_family": family,
                "direction": direction,
                "day_type": day_type,
            }
            quantification = {
                "time_band": band,
                "old_count": old_n,
                "new_count": new_n,
                "group_old_total": old_total,
                "group_new_total": new_total,
            }
            if new_n < old_n:
                ctx.emit(
                    "SERVICE_REDUCED",
                    subject=subject,
                    evidence=evidence,
                    quantification=quantification,
                    severity="major" if band in major_bands else "minor",
                )
            elif new_n > old_n:
                ctx.emit(
                    "SERVICE_INCREASED",
                    subject=subject,
                    evidence=evidence,
                    quantification=quantification,
                )
            else:
                ctx.emit(
                    "TIMETABLE_SHIFTED",
                    subject=subject,
                    evidence=evidence,
                    quantification={**quantification, "uniform": False,
                                    "trips_changed": len(removed)},
                )
        _first_last_event(ctx, group, threshold_min, old_deps_list, new_deps_list)

    dates_max = ctx.config.get("events", "service_days", "dates_list_max",
                               default=30)

    for group in sorted(pools, key=str):
        family, direction, day_type = group
        multi = wc is not None and (
            day_type in wc.old.multi_labels or day_type in wc.new.multi_labels
        )
        all_removed = [t for band in pools[group].values()
                       for t in band["removed"]]
        all_added = [t for band in pools[group].values() for t in band["added"]]
        if not multi:
            # 1世界ラベル: 従来どおり (完全に同じ計算 = 退化保証)
            _emit_band_events(
                group,
                lambda band, g=group: band_counts[0][(g, band)],
                lambda band, g=group: band_counts[1][(g, band)],
                group_totals[0][group], group_totals[1][group],
                all_removed, all_added,
                deps[0][group], deps[1][group],
            )
            continue

        # SD5: パターン対応に沿ってセル毎に比較する
        old_pats = wc.old_patterns.get(group, [])
        new_pats = wc.new_patterns.get(group, [])
        matches = wc.matches.get(group, [])
        content_cells: dict[int, list[int]] = {}
        other_cells: list[tuple[int | None, int | None]] = []
        for oi, nj, signal in matches:
            if signal == "content":
                content_cells.setdefault(oi, []).append(nj)
            else:
                other_cells.append((oi, nj))

        def _cell_trips(trips_list, side, wids):
            return [t for t in trips_list if _world_of(side, t) in wids]

        for oi in sorted(content_cells):
            # 内容同一パターンの対応 — 日付だけが違えば「運行日の変更」。
            # 見かけの増便/減便 (PRT の 38→76) はここで正しい説明になる
            njs = content_cells[oi]
            op = old_pats[oi]
            o_wids = set(op.world_ids)
            n_wids = {w for j in njs for w in new_pats[j].world_ids}
            dates_new = sorted({d for j in njs for d in new_pats[j].dates})
            removed = _cell_trips(all_removed, 0, o_wids)
            added = _cell_trips(all_added, 1, n_wids)
            if list(op.dates) == dates_new or (not removed and not added):
                continue
            evidence = ctx.index.trip_cascade_ids(
                [t.trip_id for t in removed]
            ) + ctx.index.trip_cascade_ids([t.trip_id for t in added])
            ctx.emit(
                "SERVICE_DAYS_CHANGED",
                subject={"route_family": family, "direction": direction,
                         "day_type": day_type},
                evidence=evidence,
                quantification={
                    "trips_per_day": op.trips_per_day,
                    "dates_old": list(op.dates[:dates_max]),
                    "dates_new": dates_new[:dates_max],
                    "dates_old_total": len(op.dates),
                    "dates_new_total": len(dates_new),
                },
            )

        for oi, nj in other_cells:
            o_wids = set(old_pats[oi].world_ids) if oi is not None else set()
            n_wids = set(new_pats[nj].world_ids) if nj is not None else set()
            o_deps = sorted(
                s for w in o_wids for s in world_deps[0][(group, w)])
            n_deps = sorted(
                s for w in n_wids for s in world_deps[1][(group, w)])
            _emit_band_events(
                group,
                lambda band, g=group, ws=o_wids: sum(
                    world_band[0][(g, w, band)] for w in ws),
                lambda band, g=group, ws=n_wids: sum(
                    world_band[1][(g, w, band)] for w in ws),
                sum(world_totals[0][(group, w)] for w in o_wids),
                sum(world_totals[1][(group, w)] for w in n_wids),
                _cell_trips(all_removed, 0, o_wids),
                _cell_trips(all_added, 1, n_wids),
                o_deps, n_deps,
            )


def _already_claimed(ctx: RuleContext, t: TripInfo) -> bool:
    """A群 (路線廃止/新設) 等が既に主消費した trip か。"""
    ids = ctx.index.ids_for_key("trips.txt", t.trip_id)
    return bool(ids) and all(ctx.ledger.primary_event_of(i) is not None for i in ids)


def _first_last_event(
    ctx: RuleContext,
    group: tuple,
    threshold_min: int,
    old_group_deps: list[int],
    new_group_deps: list[int],
) -> None:
    family, direction, day_type = group
    old_deps = sorted(old_group_deps)
    new_deps = sorted(new_group_deps)
    if not old_deps or not new_deps:
        return
    first_shift = (new_deps[0] - old_deps[0]) / 60
    last_shift = (new_deps[-1] - old_deps[-1]) / 60
    if abs(first_shift) < threshold_min and abs(last_shift) < threshold_min:
        return
    ctx.emit(
        "FIRST_LAST_CHANGED",
        subject={"route_family": family, "direction": direction, "day_type": day_type},
        evidence=[],  # 主消費は該当ビンの SERVICE_* / TIMETABLE イベント
        quantification={
            "first_shift_min": round(first_shift, 1),
            "last_shift_min": round(last_shift, 1),
            "old_first": _fmt(old_deps[0]),
            "new_first": _fmt(new_deps[0]),
            "old_last": _fmt(old_deps[-1]),
            "new_last": _fmt(new_deps[-1]),
        },
    )


def _fmt(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


# --- 時刻修正 (同一 trip_id の modified) ---


def _modified_trip_events(ctx: RuleContext) -> None:
    max_std = ctx.config.get(
        "events", "timetable", "uniform_shift_max_std_sec", default=120
    )
    # (family, direction, day_type, 分類, シフト分) でまとめる
    grouped: dict[tuple, list] = defaultdict(list)
    for old_trip, new_trip in ctx.trip_delta.modified:
        if old_trip.base_seq != new_trip.base_seq:
            continue  # パターン変化は B群が処理済み
        if old_trip.trip_id == new_trip.trip_id:
            time_ids = [
                d.rawdiff_id
                for d in ctx.index.for_key("stop_times.txt", new_trip.trip_id)
                if d.kind == "field_changed"
                and d.column in ("arrival_time", "departure_time")
            ]
        else:
            # trip matching v2 の ID 跨ぎ対応: 差分は旧 ID の row_removed +
            # 新 ID の row_added として現れるため、両 trip の行全体を evidence に
            time_ids = ctx.index.trip_cascade_ids(
                [old_trip.trip_id]
            ) + ctx.index.trip_cascade_ids([new_trip.trip_id])
        if not time_ids:
            continue
        deltas = _time_deltas(old_trip, new_trip)
        if deltas and len(deltas) > 1 and statistics.pstdev(deltas) <= max_std:
            shift_min = round(statistics.mean(deltas) / 60)
            key = (new_trip.family, new_trip.direction, new_trip.day_type,
                   "TIMETABLE_SHIFTED", shift_min)
        elif deltas and len(deltas) == 1:
            key = (new_trip.family, new_trip.direction, new_trip.day_type,
                   "TIMETABLE_SHIFTED", round(deltas[0] / 60))
        else:
            key = (new_trip.family, new_trip.direction, new_trip.day_type,
                   "TRAVEL_TIME_CHANGED", 0)
        grouped[key].append((old_trip, new_trip, time_ids))

    for key in sorted(grouped, key=str):
        family, direction, day_type, type_, shift_min = key
        members = grouped[key]
        evidence = [i for _, _, ids in members for i in ids]
        quantification = {"trip_count": len(members)}
        if type_ == "TIMETABLE_SHIFTED":
            quantification["shift_min"] = shift_min
            quantification["uniform"] = True
        else:
            segments = _segment_stats(members)
            if segments:
                quantification["segments"] = segments
        ctx.emit(
            type_,
            subject={"route_family": family, "direction": direction, "day_type": day_type},
            evidence=evidence,
            quantification=quantification,
        )


def _segment_stats(members: list, top_n: int = 5) -> list[dict]:
    """区間 (連続停留所ペア) 別の所要時間分布変化。|中央値の差| 上位 top_n。

    quantification 形式は ontology C群 TRAVEL_TIME_CHANGED の定義に従う:
    {segment, old_median_sec, new_median_sec, old_p90, new_p90}
    """
    old_runs: dict[str, list[int]] = defaultdict(list)
    new_runs: dict[str, list[int]] = defaultdict(list)
    for old_trip, new_trip, _ in members:
        for trip, runs in ((old_trip, old_runs), (new_trip, new_runs)):
            for i in range(len(trip.base_seq) - 1):
                dep = parse_gtfs_time(trip.times[i][1] or trip.times[i][0])
                arr = parse_gtfs_time(trip.times[i + 1][0] or trip.times[i + 1][1])
                if dep is None or arr is None:
                    continue
                runs[f"{trip.base_seq[i]}→{trip.base_seq[i + 1]}"].append(arr - dep)

    def p90(values: list[int]) -> int:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]

    stats = []
    # sorted: set 交差の反復順は PYTHONHASHSEED 依存 — 同差分値の並びと
    # top_n の選抜が実行ごとに揺れる (再現性の破れ)。決定的に列挙する
    for segment in sorted(old_runs.keys() & new_runs.keys()):
        old_med = int(statistics.median(old_runs[segment]))
        new_med = int(statistics.median(new_runs[segment]))
        if old_med == new_med:
            continue
        stats.append(
            {
                "segment": segment,
                "old_median_sec": old_med,
                "new_median_sec": new_med,
                "old_p90": p90(old_runs[segment]),
                "new_p90": p90(new_runs[segment]),
            }
        )
    stats.sort(key=lambda s: (-abs(s["new_median_sec"] - s["old_median_sec"]),
                              s["segment"]))  # タイブレークも決定的に
    return stats[:top_n]


def _time_deltas(old_trip: TripInfo, new_trip: TripInfo) -> list[int]:
    """対応する停留所ごとの発時刻差 (秒)。長さ不一致なら空。"""
    if len(old_trip.times) != len(new_trip.times):
        return []
    deltas = []
    for (o_arr, o_dep), (n_arr, n_dep) in zip(old_trip.times, new_trip.times):
        o = parse_gtfs_time(o_dep or o_arr)
        n = parse_gtfs_time(n_dep or n_arr)
        if o is None or n is None:
            return []
        deltas.append(n - o)
    return deltas

"""C群: 便数・時刻レベルのイベント (subject: family × 方向 × 運行日種別 × 時間帯)。

trip_id の連続性は仮定しない (trip_delta が内容署名で照合済み)。

検出条件 (docs/design/ontology.md C群):
- SERVICE_REDUCED / SERVICE_INCREASED: 対応済み family の (方向, day_type)
  グループで、時間帯ビンごとの本数が増減。evidence はそのビンに属する
  removed / added trip の trips + stop_times 行 (カスケード消費)。
  通勤帯 (events.frequency.major_bands) の減便は severity=major。
- 本数同数でも同ビン内で trip の入れ替えがある場合は「時刻変更」として
  TIMETABLE_SHIFTED (uniform=false) で会計する。
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
from collections import defaultdict

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

    for group in sorted(pools, key=str):
        family, direction, day_type = group
        # グループ全体の本数 (増減の分母表示用)
        old_total = sum(
            1 for t in ctx.trip_delta.old_trips.values() if _group_key(t) == group
        )
        new_total = sum(
            1 for t in ctx.trip_delta.new_trips.values() if _group_key(t) == group
        )
        for band in ctx.time_bands.labels():
            pool = pools[group].get(band)
            if pool is None:
                continue
            removed, added = pool["removed"], pool["added"]
            if not removed and not added:
                continue
            evidence = ctx.index.trip_cascade_ids(
                [t.trip_id for t in removed]
            ) + ctx.index.trip_cascade_ids([t.trip_id for t in added])
            # 旧世代/新世代のこのビンの本数
            old_n = sum(
                1
                for t in ctx.trip_delta.old_trips.values()
                if _group_key(t) == group
                and ctx.time_bands.band_of(t.first_departure) == band
            )
            new_n = sum(
                1
                for t in ctx.trip_delta.new_trips.values()
                if _group_key(t) == group
                and ctx.time_bands.band_of(t.first_departure) == band
            )
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
                # 本数同数・時刻入れ替え
                ctx.emit(
                    "TIMETABLE_SHIFTED",
                    subject=subject,
                    evidence=evidence,
                    quantification={**quantification, "uniform": False,
                                    "trips_changed": len(removed)},
                )

        _first_last_event(ctx, group, threshold_min)


def _already_claimed(ctx: RuleContext, t: TripInfo) -> bool:
    """A群 (路線廃止/新設) 等が既に主消費した trip か。"""
    ids = ctx.index.ids_for_key("trips.txt", t.trip_id)
    return bool(ids) and all(ctx.ledger.primary_event_of(i) is not None for i in ids)


def _first_last_event(ctx: RuleContext, group: tuple, threshold_min: int) -> None:
    family, direction, day_type = group
    old_deps = sorted(
        s
        for t in ctx.trip_delta.old_trips.values()
        if _group_key(t) == group and (s := parse_gtfs_time(t.first_departure)) is not None
    )
    new_deps = sorted(
        s
        for t in ctx.trip_delta.new_trips.values()
        if _group_key(t) == group and (s := parse_gtfs_time(t.first_departure)) is not None
    )
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
    for segment in old_runs.keys() & new_runs.keys():
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
    stats.sort(key=lambda s: -abs(s["new_median_sec"] - s["old_median_sec"]))
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

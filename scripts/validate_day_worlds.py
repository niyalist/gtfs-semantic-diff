"""SD5 プロトタイプ検証: 運行日世界 (原則A) + 内容ダイジェスト束ね (特定日パターン)。

コアには手を入れず、収集済み事例 (data/daypattern_pairs ほか) に対して:
1. day_type ラベル毎に「実効運行日の重なりで結ぶ service 連結成分 (世界)」を計算
2. 世界の内容ダイジェスト (trip 署名の多重集合の hash) で
   同一世代内の同値類 (特定日1/2…) と世代間対応 (完全一致のみ) を観測
3. 現行挙動との差 = 「ラベル合算の便数 vs 世界毎の便数」の乖離を列挙

使い方:
  .venv.nosync/bin/python scripts/validate_day_worlds.py pair old.zip new.zip
  .venv.nosync/bin/python scripts/validate_day_worlds.py single feed.zip
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.windows import snapshot_window  # noqa: E402
from gtfs_semantic_diff.load import load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.day_types import (  # noqa: E402
    _CALENDAR_DAY_COLUMNS,
    _exception_dates,
    effective_date_list,
)


def effective_dates_all(snap) -> dict[str, list[str]]:
    """全 service の実効運行日 (SD1 と同一定義)。"""
    added_map, removed_map = _exception_dates(snap.table("calendar_dates"))
    window = snapshot_window(snap)
    window_text = window.as_text() if window is not None else None
    result: dict[str, list[str]] = {}
    done: set[str] = set()
    cal = snap.table("calendar")
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            sid = str(row.get("service_id", "")).strip()
            flags = tuple(
                str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS)
            computed = effective_date_list(
                flags, str(row["start_date"]), str(row["end_date"]),
                added_map.get(sid, set()), removed_map.get(sid, set()),
                window_text,
            ) if any(flags) else None
            if computed is not None:
                result[sid] = computed[0]
                done.add(sid)
    all_sids = set(snap.day_types)
    for sid in all_sids - done:
        removed = removed_map.get(sid, set())
        result[sid] = sorted(
            d for d in set(added_map.get(sid, [])) if d not in removed)
    return result


def trip_sigs_by_service(snap) -> dict[str, Counter]:
    """service_id → trip 内容署名 (route, direction, 停車列, 発時刻列) の多重集合。"""
    trips = snap.table("trips")
    st = snap.table("stop_times")
    if trips is None or st is None:
        return {}
    st2 = st[["trip_id", "stop_id", "stop_sequence", "departure_time"]].copy()
    import pandas as pd

    st2["_seq"] = pd.to_numeric(st2["stop_sequence"], errors="coerce")
    st2 = st2.sort_values(["trip_id", "_seq"], kind="stable")
    g = st2.groupby("trip_id", sort=False)
    seqs = g["stop_id"].agg(tuple)
    deps = g["departure_time"].agg(tuple)
    direction = (trips["direction_id"] if "direction_id" in trips.columns
                 else [""] * len(trips))
    out: dict[str, Counter] = defaultdict(Counter)
    for tid, rid, sid, d in zip(trips["trip_id"], trips["route_id"],
                                trips["service_id"], direction):
        tid = str(tid).strip()
        out[str(sid).strip()][(
            str(rid).strip(), str(d).strip(),
            seqs.get(tid, ()), deps.get(tid, ()),
        )] += 1
    return out


def worlds_of(snap):
    """day_type ラベル毎の世界分解。[(label, [world])] を返す。
    world = {services, dates, n_trips, digest}"""
    dates = effective_dates_all(snap)
    sigs = trip_sigs_by_service(snap)
    by_label: dict[str, list[str]] = defaultdict(list)
    for sid, dt in snap.day_types.items():
        by_label[dt].append(sid)
    result = []
    for label, sids in sorted(by_label.items()):
        # 日付→service で連結成分 (union-find 代わりの反復マージ)
        comp: dict[str, int] = {}
        groups: list[set[str]] = []
        date_owner: dict[str, int] = {}
        for sid in sorted(sids):
            my = set()
            for d in dates.get(sid, ()):
                if d in date_owner:
                    my.add(date_owner[d])
            if my:
                root = min(my)
                groups[root].add(sid)
                for gi in my - {root}:
                    groups[root] |= groups[gi]
                    groups[gi] = set()
                merged = groups[root]
            else:
                root = len(groups)
                groups.append({sid})
                merged = groups[root]
            for m in merged:
                comp[m] = root
                for d in dates.get(m, ()):
                    date_owner[d] = root
        worlds = []
        for g in groups:
            if not g:
                continue
            wdates = sorted({d for s in g for d in dates.get(s, ())})
            counter = Counter()
            for s in g:
                counter.update(sigs.get(s, ()))
            digest = hashlib.sha1(
                repr(sorted(counter.items())).encode()).hexdigest()[:12]
            worlds.append({
                "services": sorted(g), "dates": wdates,
                "n_trips": sum(counter.values()), "digest": digest,
            })
        worlds.sort(key=lambda w: (w["dates"][0] if w["dates"] else "",
                                   w["services"]))
        result.append((label, worlds))
    return result


def describe(name: str, snap):
    print(f"--- {name}")
    ws = worlds_of(snap)
    for label, worlds in ws:
        if len(worlds) == 1 and label not in ("irregular", "inactive"):
            continue  # 通常 (1世界のレギュラー型) は省略
        merged_trips = sum(w["n_trips"] for w in worlds)
        head = f"  {label}: {len(worlds)}世界"
        if len(worlds) > 1:
            head += f" (現行はラベル合算 {merged_trips}便に見える)"
        print(head)
        for w in worlds:
            ds = w["dates"]
            span = (f"{ds[0]}..{ds[-1]} ({len(ds)}日)" if len(ds) > 2
                    else "/".join(ds) if ds else "(実効0日)")
            print(f"    [{w['digest']}] {span} {w['n_trips']}便 "
                  f"svc={w['services'][:3]}{'...' if len(w['services']) > 3 else ''}")
        # 同値類 (完全一致束ね)
        classes = defaultdict(list)
        for i, w in enumerate(worlds):
            classes[w["digest"]].append(i)
        merged = [v for v in classes.values() if len(v) > 1]
        if merged:
            print(f"    → 内容同一で束なる世界: {merged}")
    return ws


def main() -> None:
    mode = sys.argv[1]
    config = Config.load()
    if mode == "single":
        snap = load_snapshot(Path(sys.argv[2]), config=config)
        describe(Path(sys.argv[2]).name, snap)
        return
    old = load_snapshot(Path(sys.argv[2]), config=config)
    new = load_snapshot(Path(sys.argv[3]), config=config)
    ws_old = describe("old: " + Path(sys.argv[2]).name, old)
    ws_new = describe("new: " + Path(sys.argv[3]).name, new)
    # 世代間: irregular 世界の完全一致対応
    def irr(ws):
        return {w["digest"]: w for label, worlds in ws
                for w in worlds if label == "irregular"}
    io_, in_ = irr(ws_old), irr(ws_new)
    both = set(io_) & set(in_)
    for d in sorted(both):
        print(f"  ⇔ 特定日パターン一致 [{d}]: "
              f"旧 {'/'.join(io_[d]['dates'][:4])} → 新 {'/'.join(in_[d]['dates'][:4])}"
              f" ({io_[d]['n_trips']}便)")
    for d in sorted(set(io_) - both):
        print(f"  ← 旧のみ [{d}]: {'/'.join(io_[d]['dates'][:4])} ({io_[d]['n_trips']}便)")
    for d in sorted(set(in_) - both):
        print(f"  → 新のみ [{d}]: {'/'.join(in_[d]['dates'][:4])} ({in_[d]['n_trips']}便)")


if __name__ == "__main__":
    main()

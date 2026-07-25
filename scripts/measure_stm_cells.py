"""STM (モントリオール) の世界セル問題の計測 (SD5b 第3弾の前段)。

既知の症状 (presentation.md 2026-07-25 記録): 「四半期×学校日変種」の多重世界
(1ラベル4セル級) で flow 整列 (便対応多数決の1:1) と v1 対応の実配線が食い違い、
④の整合 warning (self_check) が大量に出る。route 18 は世代側の便数も要検証。

このスクリプトは実パイプラインを回して以下を数える:
  1. 世界の構造: ラベル毎の世界数・日付範囲・service 数・mixed
  2. セルの構造: (group, label) 毎のセル数と対応信号の分布
  3. self_check 違反: 件数・グループ別・乖離の大きさ
  4. flow の横断: v1 対応 (modified+exact) が表示セルをどれだけ跨ぐか
     (対角 = 同セル内 / 交差 = セル跨ぎ。交差が④の列数счёт崩れの原因仮説)

使い方: .venv.nosync/bin/python scripts/measure_stm_cells.py [old.zip new.zip]
"""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from itertools import chain
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.day_worlds import build_world_context  # noqa: E402
from gtfs_semantic_diff.events.pipeline import (  # noqa: E402
    compare_snapshots_with_artifacts,
)
from gtfs_semantic_diff.load import load_snapshot  # noqa: E402
from gtfs_semantic_diff.report.presentation import (  # noqa: E402
    _DUP,
    _Builder,
    base_day,
)


def main() -> None:
    old_zip = sys.argv[1] if len(sys.argv) > 2 else "data/intl/stm/old.zip"
    new_zip = sys.argv[2] if len(sys.argv) > 2 else "data/intl/stm/new.zip"
    config = Config.load(None)

    t0 = time.time()
    old = load_snapshot(old_zip, config=config)
    new = load_snapshot(new_zip, config=config)
    print(f"load: {time.time() - t0:.1f}s "
          f"(trips {len(old.table('trips'))} → {len(new.table('trips'))})")

    t0 = time.time()
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    print(f"compare: {time.time() - t0:.1f}s / events {len(event_set.events)} / "
          f"explained {event_set.accounting.explained_ratio:.4f}")

    wc = build_world_context(old, new, trip_delta.old_trips, trip_delta.new_trips)

    # --- 1. 世界の構造 -------------------------------------------------
    print("\n== 1. 世界の構造 (multi ラベルのみ)")
    for side, w in (("old", wc.old), ("new", wc.new)):
        by_label: dict[str, list] = defaultdict(list)
        for world in w.worlds:
            by_label[world.day_type].append(world)
        for label in sorted(w.multi_labels):
            worlds = by_label[label]
            print(f"  [{side}] {label}: {len(worlds)}世界")
            for x in sorted(worlds, key=lambda x: x.world_id):
                span = f"{x.dates[0]}..{x.dates[-1]}" if x.dates else "-"
                print(f"    {x.world_id}: svc={len(x.services)} "
                      f"days={len(x.dates)} {span}"
                      f"{' MIXED shared=' + str(len(x.shared_dates)) if x.mixed else ''}")

    # --- presentation を組んでセルと self_check を観測 -------------------
    builder = _Builder(event_set, identity, trip_delta, config, day_worlds=wc)
    pres = builder.build()

    # --- 2. セルの構造 --------------------------------------------------
    print("\n== 2. セルの構造 (セル数分布と信号)")
    n_cells = Counter()   # セル数 → group·label 件数
    sig_count = Counter()
    worst: list[tuple[int, str]] = []
    for group, gmeta in builder.group_day_cells.items():
        by_label: dict[str, int] = Counter()
        for disp, meta in gmeta.items():
            by_label[base_day(disp)] += 1
            sig_count[meta["signal"]] += 1
        for label, n in by_label.items():
            n_cells[n] += 1
            worst.append((n, f"{group} / {label}"))
    for n in sorted(n_cells):
        print(f"  {n}セル: {n_cells[n]} (group×label)")
    print(f"  信号分布: {dict(sig_count)}")
    worst.sort(reverse=True)
    print("  セル数上位:")
    for n, name in worst[:8]:
        print(f"    {n}セル {name}")

    # --- 3. self_check --------------------------------------------------
    sc = pres["self_check"]
    print(f"\n== 3. self_check 違反: {len(sc)}件")
    by_group = Counter(c["route_group"] for c in sc)
    for g, n in by_group.most_common(10):
        print(f"  {g}: {n}件")
    # 乖離の大きさ (ヘッダ合計 vs ④合計)
    dh = sum(abs(c["header"][0] - c["timetable"][0])
             + abs(c["header"][1] - c["timetable"][1]) for c in sc)
    print(f"  乖離合計 (便·延べ): {dh}")

    # --- 4. flow の横断 (v1 対応 × 表示セル) ----------------------------
    print("\n== 4. v1 対応の表示セル横断 (multi ラベルのみ)")
    diag = cross = drop = 0
    cross_by: Counter = Counter()
    for o, n in chain(trip_delta.modified, trip_delta.exact_pairs):
        lo = base_day(o.day_type)
        ln = base_day(n.day_type)
        if (lo not in wc.old.multi_labels and lo not in wc.new.multi_labels
                and ln not in wc.old.multi_labels
                and ln not in wc.new.multi_labels):
            continue
        do = builder._dlabel("o", o)
        dn = builder._dlabel("n", n)
        if do == _DUP or dn == _DUP:
            drop += 1  # 非代表世界の便 (双子写像で表示から畳まれる)
            continue
        if do == dn:
            diag += 1
        else:
            cross += 1
            g = builder.f2g.get(n.family, n.family)
            cross_by[(g, do, dn)] += 1
    print(f"  同セル内 (対角): {diag} / セル跨ぎ (交差): {cross} / "
          f"非代表世界 (畳み): {drop}")
    print("  交差の上位 (group, 旧セル→新セル):")
    for (g, do, dn), n in cross_by.most_common(12):
        print(f"    {n:4d}  {g}  {do} → {dn}")

    # --- 5. route 18 の実数 ---------------------------------------------
    print("\n== 5. 便数の照合 (self_check 上位グループ)")
    targets = [g for g, _ in by_group.most_common(3)]
    for g in targets:
        page = next((p for p in pres["route_pages"] if p["route_group"] == g), None)
        if not page:
            continue
        raw_o = Counter()
        raw_n = Counter()
        for t in trip_delta.old_trips.values():
            if builder.f2g.get(t.family, t.family) == g:
                raw_o[t.day_type] += 1
        for t in trip_delta.new_trips.values():
            if builder.f2g.get(t.family, t.family) == g:
                raw_n[t.day_type] += 1
        print(f"  {g}")
        print(f"    生カウント old={dict(raw_o)}")
        print(f"    生カウント new={dict(raw_n)}")
        for d in page["day_totals"]:
            print(f"    表示 {d['day_type']}: {d['old']}→{d['new']}"
                  f"{' mixed' if d.get('mixed_old') or d.get('mixed_new') else ''}")


if __name__ == "__main__":
    main()

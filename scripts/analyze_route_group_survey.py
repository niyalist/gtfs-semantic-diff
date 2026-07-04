"""M6: survey_route_groups.py の結果 (data/survey/results.jsonl) を集計する。

出力: 集約率分布、多family語幹の出現率、語幹一致対の Jaccard 分布 (閾値決定用)、
誤結合リスク実例 (低 Jaccard)、分割候補の頻度。
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "data" / "survey" / "results.jsonl"


def main() -> None:
    records = [json.loads(x) for x in RESULTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"# フィード数: {len(records)}")

    # --- 3段階集約率 ---
    multi_feeds = [r for r in records if r["multi_family_stems"] > 0]
    print(f"\n## 多family語幹 (30A/30B型) があるフィード: {len(multi_feeds)} / {len(records)} "
          f"({len(multi_feeds) / len(records):.0%})")
    ratios = []
    for r in records:
        if r["n_families"]:
            ratios.append(r["n_stem_groups"] / r["n_families"])
    print(f"語幹集約率 (stem/family) 中央値 {statistics.median(ratios):.2f} / "
          f"最小 {min(ratios):.2f}")

    top = sorted(records, key=lambda r: r["n_families"] - r["n_stem_groups"], reverse=True)[:12]
    print("\n## family→stem の集約が大きいフィード (上位12)")
    for r in top:
        print(f"  {r['org_id']}/{r['feed_id']} ({r.get('org_name', '')}): "
              f"routes {r['n_routes']} → fam {r['n_families']} → stem {r['n_stem_groups']} "
              f"(多family語幹 {r['multi_family_stems']})")

    # --- Jaccard 分布 ---
    pairs = [p for r in records for p in r["pairs"]]
    values = [p["stop_jaccard"] for p in pairs]
    print(f"\n## 語幹一致 family 対: {len(pairs)} 対")
    if values:
        buckets = Counter()
        for v in values:
            buckets[min(9, int(v * 10))] += 1
        for b in range(10):
            bar = "#" * round(60 * buckets.get(b, 0) / max(1, len(values)))
            print(f"  {b / 10:.1f}-{(b + 1) / 10:.1f}: {buckets.get(b, 0):5d} {bar}")
        print(f"  中央値 {statistics.median(values):.3f} / "
              f"p10 {sorted(values)[int(0.1 * len(values))]:.3f}")
        for th in (0.1, 0.2, 0.3, 0.4, 0.5):
            below = sum(1 for v in values if v < th)
            print(f"  Jaccard < {th}: {below} 対 ({below / len(values):.1%})")

    # --- 低 Jaccard の実例 (誤結合リスク) ---
    low = sorted((p for p in pairs if p["stop_jaccard"] < 0.2),
                 key=lambda p: p["stop_jaccard"])
    print(f"\n## 低 Jaccard (<0.2) の語幹一致対: {len(low)} 対 (誤結合リスク実例, 上位15)")
    feed_of = {}
    for r in records:
        for p in r["pairs"]:
            feed_of[id(p)] = f"{r['org_id']}/{r['feed_id']}"
    shown = 0
    for r in records:
        for p in r["pairs"]:
            if p["stop_jaccard"] < 0.2 and shown < 15:
                print(f"  [{r['org_id']}] {p['a']} ↔ {p['b']} "
                      f"(J={p['stop_jaccard']}, stops {p['a_stops']}/{p['b_stops']})")
                shown += 1

    # --- 分割候補 ---
    splits = [(r, s) for r in records for s in r["split_candidates"]]
    split_feeds = {r["org_id"] for r, _ in splits}
    print(f"\n## 分割候補 (family 内クラスタ対 J<0.1): {len(splits)} 対 / "
          f"{len(split_feeds)} フィード (上位10)")
    for r, s in splits[:10]:
        print(f"  [{r['org_id']}] {s['family']}: {s['a']} vs {s['b']} "
              f"(J={s['jaccard']}, trips {s['a_trips']}/{s['b_trips']})")

    # --- 語幹抽出の副作用チェック: 接頭コードが長い/語幹が極端に短い例 ---
    odd = []
    for r in records:
        for name, sp in r["stems"].items():
            if sp["prefix"] and (len(sp["prefix"]) > 8 or len(sp["stem"]) <= 2):
                odd.append((r["org_id"], name, sp["prefix"], sp["stem"]))
    print(f"\n## 語幹抽出の要注意例 (接頭コード>8文字 or 語幹≤2文字): {len(odd)} 件 (上位15)")
    for org, name, prefix, stem in odd[:15]:
        print(f"  [{org}] {name!r} → prefix={prefix!r} stem={stem!r}")


if __name__ == "__main__":
    main()
    sys.exit(0)

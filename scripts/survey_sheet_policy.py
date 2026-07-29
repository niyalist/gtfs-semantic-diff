"""時刻表の分冊 (sheet) ポリシー実態調査 (2026-07-29、壁打ち用・読み取り専用)。

各フィードペアの presentation を組み立て、④時刻表の全バケット
(page × direction_group × leg × day_type) について:
  - 現行の分冊数 / 便数 / パターン数
  - 1枚に全載せしたときの avg_gap (飛びラン/列)
  - 各分冊の avg_gap
  - 「全分冊が読める (avg_gap <= trigger)」を満たす最少分冊数の近似
    (group_sheets の max_cost を大→小に振って探索)
を記録する。sheet_labels() をスパイして分冊決定の生データを取る
(呼び出し順は route_pages/timetables の出現順と一致するはずで、
枚数列で照合し、ずれたら context=None として出力)。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gtfs_semantic_diff.report.presentation as P
from gtfs_semantic_diff.config import Config
from gtfs_semantic_diff.events.day_worlds import build_world_context
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot

TRIGGER = 1.5  # sheet_split_trigger_gap_per_trip の既定
MERGE = 0.5    # sheet_merge_max_gap_per_trip の既定

LOG: list[dict] = []
_orig_sheet_labels = P.sheet_labels


def _avg(specs) -> float:
    g = P._specs_gap(specs)
    n = P._specs_alignments(specs)
    return g / max(n, 1)


def _min_readable(sheets) -> tuple[int, float]:
    """全分冊 avg_gap <= TRIGGER を満たす最少分冊数の近似。

    R17 改2 以降の group_sheets(…, TRIGGER) はそれ自体がこの近似なので、
    現行枚数との差 (over_split) は自己整合チェックになる (期待値 0)。"""
    allspecs = [s for sp in sheets for s in sp]
    by_pat: dict[tuple, list] = defaultdict(list)
    for st, o, nw in allspecs:
        by_pat[(nw or o).base_seq].append((st, o, nw))
    groups = [by_pat[k] for k in sorted(by_pat)]
    cand = P.group_sheets([list(g) for g in groups], TRIGGER)
    return (len(cand), TRIGGER)


def spy_sheet_labels(sheets):
    allspecs = [s for sp in sheets for s in sp]
    min_n, min_mc = _min_readable(sheets) if len(sheets) > 1 else (1, 0.0)
    labels = _orig_sheet_labels(sheets)
    LOG.append({
        "n_sheets": len(sheets),
        "trips": len(allspecs),
        "patterns": len({(nw or o).base_seq for _, o, nw in allspecs}),
        "avg_all": round(_avg(allspecs), 3),
        "per_sheet_avg": [round(_avg(sp), 2) for sp in sheets],
        "per_sheet_trips": [len(sp) for sp in sheets],
        "min_readable_sheets": min_n,
        "min_readable_cost": min_mc,
        "labels": labels,
    })
    return labels


P.sheet_labels = spy_sheet_labels


def survey(name: str, old_zip: str, new_zip: str, out_path: str) -> None:
    LOG.clear()
    config = Config.load()
    old = load_snapshot(old_zip, config)
    new = load_snapshot(new_zip, config)
    es, raw, identity, td = compare_snapshots_with_artifacts(old, new, config)
    wc = build_world_context(old, new, td.old_trips, td.new_trips)
    pres = P.build_presentation(es, identity, td, config, day_worlds=wc)

    # 出現順でバケットを組み、LOG と突合する
    buckets = []
    for page in pres["route_pages"]:
        pname = page.get("route_group") or ""
        cur = None
        for t in page.get("timetables", []):
            key = (pname, t["direction_group"], t["leg"], t["day_type"])
            if cur is None or cur["key"] != key:
                cur = {"key": key, "label": t["label"],
                       "sheets": 0, "sheet_labels": []}
                buckets.append(cur)
            cur["sheets"] += 1
            cur["sheet_labels"].append(t.get("sheet_label"))

    aligned = len(buckets) == len(LOG) and all(
        b["sheets"] == rec["n_sheets"] for b, rec in zip(buckets, LOG))
    # 出力ページは自然順ソートされるため生成順 (LOG 順) とずれることがある。
    # ずれた場合は分冊>1 の行だけ、分冊ラベル列を署名にして順序照合する
    # (ラベルは識別停留所由来でほぼ一意。同署名が複数あれば出現順に対応付け)
    ctx_of: dict[int, dict] = {}
    if aligned:
        ctx_of = dict(enumerate(buckets))
    else:
        remaining = [b for b in buckets if b["sheets"] > 1]
        for i, rec in enumerate(LOG):
            if rec["n_sheets"] <= 1:
                continue
            sig = (rec["n_sheets"], tuple(rec.get("labels") or []))
            for k, b in enumerate(remaining):
                if (b["sheets"], tuple(b["sheet_labels"])) == sig:
                    ctx_of[i] = remaining.pop(k)
                    break
    rows = []
    for i, rec in enumerate(LOG):
        b = ctx_of.get(i)
        rows.append({
            "feed": name,
            "page": b["key"][0] if b else None,
            "dg": b["key"][1] if b else None,
            "leg": b["key"][2] if b else None,
            "day": b["key"][3] if b else None,
            "label": b["label"] if b else None,
            "sheet_labels": b["sheet_labels"] if b else None,
            **rec,
        })
    Path(out_path).write_text(
        json.dumps({"feed": name, "aligned": aligned, "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    n_split = sum(1 for r in rows if r["n_sheets"] > 1)
    n_over = sum(1 for r in rows if r["n_sheets"] > r["min_readable_sheets"])
    print(f"[{name}] buckets={len(rows)} split={n_split} "
          f"over_split={n_over} aligned={aligned}", flush=True)


if __name__ == "__main__":
    root = Path(__file__).parent.parent
    out_dir = root / "data" / "sheet_survey"
    out_dir.mkdir(exist_ok=True)
    if len(sys.argv) > 1:
        # 使い方: survey_sheet_policy.py name old.zip new.zip [name old new ...]
        argv = sys.argv[1:]
        PAIRS = [tuple(argv[i:i + 3]) for i in range(0, len(argv), 3)]
    else:
        PAIRS = [
            ("kakegawa", "data/kakegawa/prev_2.zip", "data/kakegawa/current.zip"),
            ("hokkaido_chuo", "data/hokkaido/hokkaido_chuo_20251219.zip",
             "data/hokkaido/hokkaido_chuo_20260601.zip"),
            ("abashiri", "data/hokkaido/abashiri_bus_20251219.zip",
             "data/hokkaido/abashiri_bus_20260601.zip"),
            ("engan", "data/hokkaido/engan_bus_20251219.zip",
             "data/hokkaido/engan_bus_20260601.zip"),
            ("shibetsu", "data/hokkaido/shibetsu_kido_20251219.zip",
             "data/hokkaido/shibetsu_kido_20260601.zip"),
            ("kyoto", "data/kyoto/Kyoto_City_Bus_GTFS-20250630.zip",
             "data/kyoto/Kyoto_City_Bus_GTFS_20260630.zip"),
            ("nagoya", "data/nagoya/20250329_bus-gtfs-jp.zip",
             "data/nagoya/20260328_bus-gtfs-jp.zip"),
        ]
    for name, o, n in PAIRS:
        try:
            survey(name, str(root / o), str(root / n),
                   str(out_dir / f"{name}.json"))
        except Exception as e:  # noqa: BLE001 調査スクリプト: 1件の失敗で全体を止めない
            print(f"[{name}] FAILED: {e}", flush=True)

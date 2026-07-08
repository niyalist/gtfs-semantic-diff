"""V1: 実例ギャラリー生成。

diff_patterns.jsonl の分類結果から類型別の代表フィードを選び、
HTML レポートを data/gallery/ に生成して index.html で束ねる。

実行: .venv.nosync/bin/python scripts/build_gallery.py [--per-label 2]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts  # noqa: E402
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import rid_order  # noqa: E402
from gtfs_semantic_diff.report.bundle import build_bundle, render_html  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SURVEY = ROOT / "data" / "survey" / "diff_patterns.jsonl"
GALLERY = ROOT / "data" / "gallery"

LABEL_JA = {
    "large_revision": "大規模改正 (多路線同時)",
    "route_add_drop": "路線の新設・廃止・季節運行",
    "pattern": "停車パターン変化 (延長・短縮・経由変更)",
    "route_renamed": "路線名変更",
    "stops": "停留所の異動 (新設・廃止・改称・乗り場)",
    "service": "便数・時刻の変更のみ",
    "fare": "運賃改定",
    "calendar": "カレンダー・運行日の変更",
    "churn": "ID 張り替えのみ",
    "shape": "経路形状の変更",
    "metadata": "メタデータのみ",
    "no_change": "変更なし",
}


def pick(records: list[dict], per_label: int) -> dict[str, list[dict]]:
    """類型別に代表を選ぶ。読みやすさ優先で中規模 (events 5〜200) を先に。"""
    by_label = defaultdict(list)
    for r in records:
        if r.get("status") == "ok" and r.get("n_events", 0) > 0:
            by_label[r["primary"]].append(r)
    selected = {}
    for label, rs in by_label.items():
        rs.sort(key=lambda r: (0 if 5 <= r["n_events"] <= 200 else 1, -r["n_events"]))
        selected[label] = rs[:per_label]
    return selected


def generate(record: dict, config: Config, repo: GtfsDataRepository) -> Path | None:
    org, feed = record["org_id"], record["feed_id"]
    out = GALLERY / f"{record['primary']}__{org}__{feed}.html"
    if out.exists():
        return out
    files = sorted(repo.get_feed_files(org, feed, max_prev=2), key=lambda f: rid_order(f.rid))
    new_info, old_info = files[0], files[1]
    old = load_snapshot(repo.download(old_info).path, config=config,
                        meta=old_info.snapshot_meta())
    new = load_snapshot(repo.download(new_info).path, config=config,
                        meta=new_info.snapshot_meta())
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    template = (ROOT / "src/gtfs_semantic_diff/report/viewer_template.html").read_text("utf-8")
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    out.write_text(render_html(bundle, template), encoding="utf-8")
    return out


def build_index(entries: list[tuple[str, dict, Path]]) -> None:
    rows = []
    current = None
    for label, r, path in entries:
        if label != current:
            rows.append(f"<h2>{html.escape(LABEL_JA.get(label, label))} <code>{label}</code></h2>")
            current = label
        types = ", ".join(
            f"{t}×{n}" for t, n in list(r["type_counts"].items())[:6]
            if t != "UNEXPLAINED_RESIDUAL"
        )
        rows.append(
            f'<p><a href="{path.name}">{html.escape(r["org_name"] or r["org_id"])}'
            f' / {html.escape(r["feed_id"])}</a>'
            f' <small>({r["old_rid"]}→{r["new_rid"]}, {r["n_events"]} events,'
            f" ratio {r['explained_ratio']:.3f})<br/>{html.escape(types)}</small></p>"
        )
    index = (
        "<!doctype html><meta charset='utf-8'><title>gtfs-semantic-diff 実例ギャラリー (V1)</title>"
        "<style>body{font-family:sans-serif;max-width:860px;margin:2rem auto;"
        "line-height:1.6;padding:0 1rem}h2{border-bottom:2px solid #0b6e4f;"
        "padding-bottom:.2rem}small{color:#666}</style>"
        "<h1>実例ギャラリー (V1: 表示要件収集用)</h1>"
        "<p>各例を開き、docs/design/presentation.md の観点 (路線概要・本数表・詳細の統合・"
        "パターン変化の束ね方) でレビューしてください。</p>" + "".join(rows)
    )
    (GALLERY / "index.html").write_text(index, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-label", type=int, default=2)
    args = parser.parse_args()

    GALLERY.mkdir(parents=True, exist_ok=True)
    records = [json.loads(x) for x in SURVEY.read_text(encoding="utf-8").splitlines()]
    config = Config.load()
    repo = GtfsDataRepository(config=config)

    selected = pick(records, args.per_label)
    entries = []
    for label in sorted(selected, key=lambda x: list(LABEL_JA).index(x) if x in LABEL_JA else 99):
        for r in selected[label]:
            try:
                path = generate(r, config, repo)
                if path:
                    entries.append((label, r, path))
                    print(f"{label}: {r['org_id']}/{r['feed_id']} → {path.name}", flush=True)
            except Exception as e:
                print(f"{label}: {r['org_id']}/{r['feed_id']} SKIP ({e})", flush=True)
    build_index(entries)
    print(f"\nindex: {GALLERY / 'index.html'} ({len(entries)} 例)")


if __name__ == "__main__":
    main()

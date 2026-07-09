"""family 世代間対応 (M9 route identity v2) の横断監視 (読み取り専用)。

lev1_trip_ratio (新設/廃止扱いのページに落ちた便の割合) を煙感知器として
多数フィードで定点観測する (docs/design/route_identity_review.md §3.4)。
路線の改称・再編を取りこぼすとこの値が跳ねる。あわせて family 対応の
内訳 (名称一致 / 内容受理 / 候補どまり / 降格成分) を記録する。

結果: data/survey/route_identity.jsonl (1フィード1行、処理済みスキップ)
実行: .venv.nosync/bin/python scripts/survey_route_identity.py [--limit 50]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from survey_route_groups import select_feeds  # noqa: E402

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.pipeline import (  # noqa: E402
    compare_snapshots_with_artifacts,
)
from gtfs_semantic_diff.identity.route_family import (  # noqa: E402
    METHOD_CANDIDATE,
    METHOD_CONTENT,
    METHOD_NAME,
)
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import rid_order  # noqa: E402
from gtfs_semantic_diff.model.matchgraph import ENTITY_ROUTE_FAMILY  # noqa: E402
from gtfs_semantic_diff.report.presentation import build_presentation  # noqa: E402

logging.basicConfig(level=logging.WARNING)

OUT = Path(__file__).resolve().parents[1] / "data" / "survey" / "route_identity.jsonl"


def survey_feed(repo, config, org_id, feed_id) -> dict:
    files = sorted(
        repo.get_feed_files(org_id, feed_id, max_prev=1), key=lambda f: rid_order(f.rid)
    )
    if len(files) < 2:
        return {"status": "single_generation"}
    old = load_snapshot(repo.download(files[1]).path, config=config,
                        meta=files[1].snapshot_meta())
    new = load_snapshot(repo.download(files[0]).path, config=config,
                        meta=files[0].snapshot_meta())
    event_set, _, identity, delta = compare_snapshots_with_artifacts(old, new, config)

    model = build_presentation(event_set, identity, delta, config)
    lev1 = total = 0
    lev1_pages = []
    for p in model["route_pages"]:
        n = sum(d["old"] + d["new"] for d in p["day_totals"])
        total += n
        if p["summary"]["level1"]:
            lev1 += n
            lev1_pages.append({
                "group": p["route_group"],
                "kind": p["summary"]["level1"]["kind"],
                "trips": n,
                "candidates": p["similar_candidates"],
            })

    methods = {"name": 0, "content": 0, "candidate": 0}
    for e in identity.graph.for_type(ENTITY_ROUTE_FAMILY):
        if e.method == METHOD_NAME:
            methods["name"] += 1
        elif e.method == METHOD_CONTENT:
            methods["content"] += 1
        elif e.method == METHOD_CANDIDATE:
            methods["candidate"] += 1
    return {
        "status": "ok",
        "rids": [files[1].rid, files[0].rid],
        "explained_ratio": event_set.accounting.explained_ratio,
        "lev1_trip_ratio": round(lev1 / total, 4) if total else 0.0,
        "lev1_trips": lev1,
        "total_trips": total,
        "families": [len(identity.old_families), len(identity.new_families)],
        "link_methods": methods,
        "components": [
            {k: c[k] for k in ("old", "new", "shape", "similarity", "demoted")}
            for c in identity.family_components
        ],
        "lev1_pages": sorted(lev1_pages, key=lambda p: -p["trips"])[:10],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    config = Config.load()
    repo = GtfsDataRepository(config=config)
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            done.add((r["org_id"], r["feed_id"]))

    feeds = [(org, feed) for org, feed, _, _ in select_feeds(repo, args.limit)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        for org_id, feed_id in feeds:
            if (org_id, feed_id) in done:
                continue
            t0 = time.time()
            try:
                rec = survey_feed(repo, config, org_id, feed_id)
            except Exception as e:  # noqa: BLE001 - サーベイは続行優先
                rec = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            rec = {"org_id": org_id, "feed_id": feed_id,
                   "elapsed_s": round(time.time() - t0, 1), **rec}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{org_id}/{feed_id}: {rec.get('lev1_trip_ratio', rec['status'])}")


if __name__ == "__main__":
    main()

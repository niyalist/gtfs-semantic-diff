"""V1: diff パターンの横断調査 (読み取り専用)。

gtfs-data.jp のフィードから最新2世代を取得して compare を実行し、
変化の組合せで機械分類する。プレゼンテーションモデルの要件収集
(実例ギャラリー) の素材選定が目的 (docs/design/presentation.md, roadmap V1)。

結果: data/survey/diff_patterns.jsonl (1フィード1行、再実行時は処理済みスキップ)

実行: .venv.nosync/bin/python scripts/survey_diff_patterns.py [--limit 80]
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from survey_route_groups import select_feeds  # noqa: E402 (M6 と同じ層化サンプリング)

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events import compare_snapshots  # noqa: E402
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import rid_order  # noqa: E402

logging.basicConfig(level=logging.WARNING)

OUT = Path(__file__).resolve().parents[1] / "data" / "survey" / "diff_patterns.jsonl"

# イベントタイプ → 大分類
CATEGORY = {
    "route_add_drop": {"ROUTE_ADDED", "ROUTE_DISCONTINUED", "SEASONAL_SERVICE_CHANGED",
                       "ROUTE_SPLIT", "ROUTE_MERGED"},
    "route_renamed": {"ROUTE_RENAMED"},
    "pattern": {"PATTERN_EXTENDED", "PATTERN_TRUNCATED", "STOP_INSERTED_IN_PATTERN",
                "STOP_REMOVED_FROM_PATTERN", "DETOUR_ADDED", "DETOUR_REMOVED"},
    "service": {"SERVICE_REDUCED", "SERVICE_INCREASED", "FIRST_LAST_CHANGED",
                "TIMETABLE_SHIFTED", "TRAVEL_TIME_CHANGED", "TRIPS_TRUNCATED"},
    "stops": {"STOP_ADDED", "STOP_REMOVED", "STOP_RENAMED", "STOP_RELOCATED",
              "PLATFORM_ADDED", "PLATFORM_REMOVED", "PLATFORM_CHANGED"},
    "calendar": {"DAYTYPE_RESTRUCTURED", "HOLIDAY_EXCEPTION_CHANGED"},
    "fare": {"FARE_CHANGED"},
    "shape": {"SHAPE_CHANGED"},
    "metadata": {"FEED_VALIDITY_CHANGED", "AGENCY_INFO_CHANGED", "TRANSLATION_CHANGED",
                 "HEADSIGN_CHANGED", "ACCESSIBILITY_CHANGED", "DEMAND_RESPONSIVE_CHANGE"},
    "churn": {"TECHNICAL_ID_CHURN"},
    "residual": {"UNEXPLAINED_RESIDUAL"},
}

# 主分類の優先順 (上ほど「話題として濃い」)
PRIMARY_ORDER = [
    "large_revision", "route_add_drop", "pattern", "route_renamed", "stops",
    "service", "fare", "calendar", "churn", "shape", "metadata", "no_change",
]


def classify(type_counts: Counter, groups_changed: int) -> tuple[list[str], str]:
    present = {
        label
        for label, types in CATEGORY.items()
        if any(type_counts.get(t, 0) for t in types)
    }
    present.discard("residual")
    substantive = present - {"metadata", "churn", "shape", "calendar"}
    total_events = sum(
        n for t, n in type_counts.items() if t != "UNEXPLAINED_RESIDUAL"
    )
    labels = sorted(present)
    if not substantive and not present:
        primary = "no_change"
    elif total_events >= 80 and groups_changed >= 10:
        primary = "large_revision"
    else:
        primary = next(
            (p for p in PRIMARY_ORDER if p in present), "no_change"
        )
    return labels, primary


def survey(org: str, feed: str, repo: GtfsDataRepository, config: Config) -> dict:
    files = sorted(repo.get_feed_files(org, feed, max_prev=2), key=lambda f: rid_order(f.rid))
    if len(files) < 2:
        return {"org_id": org, "feed_id": feed, "status": "single_generation"}
    new_info, old_info = files[0], files[1]
    old = load_snapshot(repo.download(old_info).path, config=config,
                        meta=old_info.snapshot_meta())
    new = load_snapshot(repo.download(new_info).path, config=config,
                        meta=new_info.snapshot_meta())
    t0 = time.time()
    event_set, rawdiffs = compare_snapshots(old, new, config)
    elapsed = round(time.time() - t0, 2)

    type_counts = Counter(e.type for e in event_set.events)
    changed_groups = {
        e.subject.get("route_group")
        for e in event_set.events
        if e.subject.get("route_group")
    }
    labels, primary = classify(type_counts, len(changed_groups))
    return {
        "org_id": org,
        "feed_id": feed,
        "status": "ok",
        "old_rid": old_info.rid, "new_rid": new_info.rid,
        "old_from": old_info.from_date, "new_from": new_info.from_date,
        "n_trips_old": len(trips) if (trips := old.table("trips")) is not None else 0,
        "rawdiff_total": len(rawdiffs),
        "explained_ratio": event_set.accounting.explained_ratio,
        "n_events": sum(type_counts.values()),
        "groups_changed": len(changed_groups),
        "type_counts": dict(type_counts.most_common()),
        "labels": labels,
        "primary": primary,
        "elapsed_sec": elapsed,
    }


def _worker(org: str, feed: str, queue) -> None:
    """サブプロセスで1フィードを調査する (タイムアウト分離用)。"""
    config = Config.load()
    repo = GtfsDataRepository(config=config)
    try:
        queue.put(survey(org, feed, repo, config))
    except Exception as e:  # noqa: BLE001 (調査なので記録して続行)
        queue.put({"org_id": org, "feed_id": feed, "status": f"error: {e}"})


def survey_with_timeout(org: str, feed: str, timeout_sec: int) -> dict:
    """フィード単位のウォッチドッグ。組合せ爆発する外れ値フィードを記録して先へ進む。

    (実例: kanumacity/ri-bus は25分以上完了せず — 性能課題として記録する)
    """
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(org, feed, queue))
    proc.start()
    proc.join(timeout_sec)
    if proc.is_alive():
        proc.terminate()
        proc.join(10)
        return {"org_id": org, "feed_id": feed, "status": f"timeout({timeout_sec}s)"}
    if not queue.empty():
        return queue.get()
    return {"org_id": org, "feed_id": feed, "status": "error: worker died"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    config = Config.load()
    repo = GtfsDataRepository(config=config)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                # error は再試行する (ok / 世代不足 / タイムアウトのみ確定扱い)
                if r.get("status", "").startswith(("ok", "single_generation", "timeout")):
                    done.add((r["org_id"], r["feed_id"]))
            except json.JSONDecodeError:
                pass

    feeds = select_feeds(repo, args.limit)
    print(f"対象 {len(feeds)} フィード (処理済み {len(done)})", flush=True)
    with open(OUT, "a", encoding="utf-8") as out:
        for n, (org, feed, org_name, pref) in enumerate(feeds, 1):
            if (org, feed) in done:
                continue
            record = survey_with_timeout(org, feed, args.timeout)
            record["org_name"] = org_name
            record["pref"] = pref
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            label = record.get("primary", record["status"])
            print(
                f"[{n}/{len(feeds)}] {org}/{feed} ({org_name}): {label} "
                f"(events {record.get('n_events', '-')}, ratio {record.get('explained_ratio', '-')})",
                flush=True,
            )

    # 集計
    records = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines()]
    ok = [r for r in records if r.get("status") == "ok"]
    print(f"\n=== 集計: {len(ok)} / {len(records)} フィードで比較成功 ===")
    for label, count in Counter(r["primary"] for r in ok).most_common():
        print(f"  {label:16s} {count}")


if __name__ == "__main__":
    main()

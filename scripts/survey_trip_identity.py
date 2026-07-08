"""便の同一性判定 (trip identity) の横断評価 (読み取り専用)。

目的: ②同一 trip_id 規則と ③表示用ペアリング (発時刻差 ≤ 60分・類似ゲートなし)
の「緩さ」を定量評価する。

方法 (docs 参照: ユーザー指示 2026-07-08):
- ID が安定して運用されているフィード (両世代の trip_id 重なりが大きい) を抽出し、
  **trip_id を隠して** ③の規則でペアリング → ID 対応 (同一 trip_id の modified 対)
  を擬似正解として precision / recall を測る
- 閾値グリッド: 発時刻差 {10,15,30,60}分 × 停車列 Jaccard ゲート {なし,0.3,0.5,0.8}
- あわせて ②の同一 trip_id 対の停車列 Jaccard 分布 (ID 使い回しの兆候) を測る
- 統計だけでなく具体例 (誤ペア・大シフト正解ペア・低類似 modified) を記録する

結果: data/survey/trip_identity.jsonl (1フィード1行、再実行時は処理済みスキップ)
実行: .venv.nosync/bin/python scripts/survey_trip_identity.py [--limit 50]
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from survey_route_groups import select_feeds  # noqa: E402

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.pipeline import (  # noqa: E402
    compare_snapshots_with_artifacts,
)
from gtfs_semantic_diff.events.timebands import parse_gtfs_time  # noqa: E402
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import rid_order  # noqa: E402
from gtfs_semantic_diff.report.presentation import _Builder  # noqa: E402

logging.basicConfig(level=logging.WARNING)

OUT = Path(__file__).resolve().parents[1] / "data" / "survey" / "trip_identity.jsonl"

TIME_GRID = [10, 15, 30, 60]
GATE_GRID = [0.0, 0.3, 0.5, 0.8]

# 検証フィード (必ず含める)
EXTRA_FEEDS = [
    ("nagai-unyu", "Nagaibus", "永井運輸", 10),
    ("chitetsu", "chitetsubus", "富山地鉄", 16),
    ("buzencity", "BuzenCityBus", "豊前市", 40),
    ("oshucity", "bus-oshucity-iwate-jp", "奥州市", 3),
    ("ashiyatown", "AshiyaTownBus", "芦屋タウンバス", 40),
    ("hachinohe", "hachinohe-citybus", "八戸市交通部", 2),
    ("tokubus", "tokushimabus", "徳島バス", 36),
]


def jac(a: tuple, b: tuple) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def dep_sec(t) -> int | None:
    return parse_gtfs_time(t.first_departure)


def greedy_pair(olds, news, max_shift_min: float, gate: float):
    """production の _pair_leftovers と同じ貪欲規則 + 任意の Jaccard ゲート。"""
    candidates = []
    for o in olds:
        do = dep_sec(o)
        if do is None:
            continue
        for n in news:
            dn = dep_sec(n)
            if dn is None:
                continue
            diff = abs(dn - do)
            if diff > max_shift_min * 60:
                continue
            if gate and jac(o.base_seq, n.base_seq) < gate:
                continue
            candidates.append((diff, o.first_departure, n.first_departure,
                               o.trip_id, n.trip_id, o, n))
    candidates.sort(key=lambda c: c[:5])
    used_old, used_new, pairs = set(), set(), []
    for _, _, _, o_id, n_id, o, n in candidates:
        if o_id in used_old or n_id in used_new:
            continue
        used_old.add(o_id)
        used_new.add(n_id)
        pairs.append((o, n))
    return pairs


def trip_brief(t) -> dict:
    return {
        "trip_id": t.trip_id,
        "dep": t.first_departure,
        "from": t.base_seq[0] if t.base_seq else "",
        "to": t.base_seq[-1] if t.base_seq else "",
        "n_stops": len(t.base_seq),
    }


def survey(org: str, feed: str, repo: GtfsDataRepository, config: Config) -> dict:
    files = sorted(repo.get_feed_files(org, feed, max_prev=2),
                   key=lambda f: rid_order(f.rid))
    if len(files) < 2:
        return {"status": "single_generation"}
    fo, fn = files[1], files[0]
    old = load_snapshot(repo.download(fo).path, config=config, meta=fo.snapshot_meta())
    new = load_snapshot(repo.download(fn).path, config=config, meta=fn.snapshot_meta())
    es, rd, ident, delta = compare_snapshots_with_artifacts(old, new, config)

    old_ids = set(delta.old_trips)
    new_ids = set(delta.new_trips)
    common = old_ids & new_ids
    id_overlap = len(common) / min(len(old_ids), len(new_ids)) if old_ids and new_ids else 0.0

    # ② 同一 trip_id (modified) 対の停車列類似
    modified_jacs = []
    low_sim_examples = []
    for o, n in delta.modified:
        j = jac(o.base_seq, n.base_seq)
        modified_jacs.append(round(j, 3))
        if j < 0.5 and len(low_sim_examples) < 5:
            low_sim_examples.append({"old": trip_brief(o), "new": trip_brief(n),
                                     "jaccard": round(j, 3)})

    # trip → (route_group, dg, leg, day) の対応 (production と同じバケット)
    b = _Builder(es, ident, delta, config)
    model = b.build()
    sysinfo = {}
    group_of_sys = {}
    for page in model["route_pages"]:
        for g in page["overview"]["direction_groups"]:
            for s in g["systems"]:
                sysinfo[s["system_id"]] = (g["id"], s["leg"])
                group_of_sys[s["system_id"]] = page["route_group"]

    def bucket_of(t, gen: str):
        s2c = b.old_seq2cluster if gen == "old" else b.new_seq2cluster
        cid = s2c.get((t.family, t.direction, t.base_seq))
        sid = cid if cid in sysinfo else f"old:{cid}"
        if sid not in sysinfo:
            return None
        dg, leg = sysinfo[sid]
        return (group_of_sys[sid], dg, leg, t.day_type)

    # 擬似正解 = modified (同一 trip_id) 対。バケット単位に整理
    truth_by_bucket: dict[tuple, list[tuple]] = defaultdict(list)
    cross_bucket_truth = 0
    for o, n in delta.modified:
        bo, bn = bucket_of(o, "old"), bucket_of(n, "new")
        if bo is None or bn is None:
            continue
        if bo == bn:
            truth_by_bucket[bo].append((o, n))
        else:
            cross_bucket_truth += 1
    removed_by_bucket: dict[tuple, list] = defaultdict(list)
    added_by_bucket: dict[tuple, list] = defaultdict(list)
    for t in delta.removed:
        bk = bucket_of(t, "old")
        if bk is not None:
            removed_by_bucket[bk].append(t)
    for t in delta.added:
        bk = bucket_of(t, "new")
        if bk is not None:
            added_by_bucket[bk].append(t)

    # 正解対の分布 (時刻差・Jaccard)
    truth_stats = []
    for pairs in truth_by_bucket.values():
        for o, n in pairs:
            do, dn = dep_sec(o), dep_sec(n)
            if do is None or dn is None:
                continue
            truth_stats.append((abs(dn - do) // 60, round(jac(o.base_seq, n.base_seq), 3)))

    # グリッド評価: ID を隠してペアリング → ID 対応と比較
    grid = {}
    wrong_examples = []
    big_shift_correct = []
    for tmin in TIME_GRID:
        for gate in GATE_GRID:
            correct = wrong = labeled = predicted = truth_total = 0
            for bk in set(truth_by_bucket) | set(removed_by_bucket) | set(added_by_bucket):
                truth = truth_by_bucket.get(bk, [])
                truth_total += len(truth)
                truth_o2n = {o.trip_id: n.trip_id for o, n in truth}
                olds = [o for o, _ in truth] + removed_by_bucket.get(bk, [])
                news = [n for _, n in truth] + added_by_bucket.get(bk, [])
                pairs = greedy_pair(olds, news, tmin, gate)
                predicted += len(pairs)
                for o, n in pairs:
                    is_truth_o = o.trip_id in truth_o2n
                    is_truth_n = n.trip_id in {x.trip_id for _, x in truth}
                    if not (is_truth_o or is_truth_n):
                        continue  # 正解不明 (真の廃止×新設同士)
                    labeled += 1
                    if truth_o2n.get(o.trip_id) == n.trip_id:
                        correct += 1
                        if tmin == 60 and gate == 0.0:
                            do, dn = dep_sec(o), dep_sec(n)
                            if do is not None and dn is not None and abs(dn - do) > 30 * 60 \
                                    and len(big_shift_correct) < 3:
                                big_shift_correct.append({
                                    "bucket": list(bk),
                                    "old": trip_brief(o), "new": trip_brief(n),
                                    "shift_min": abs(dn - do) // 60,
                                })
                    else:
                        wrong += 1
                        if tmin == 60 and gate == 0.0 and len(wrong_examples) < 5:
                            true_n = truth_o2n.get(o.trip_id)
                            wrong_examples.append({
                                "bucket": list(bk),
                                "old": trip_brief(o), "new": trip_brief(n),
                                "jaccard": round(jac(o.base_seq, n.base_seq), 3),
                                "true_partner_of_old": true_n,
                            })
            grid[f"{tmin}_{gate}"] = {
                "predicted": predicted, "labeled": labeled,
                "correct": correct, "wrong": wrong, "truth": truth_total,
            }

    return {
        "status": "ok",
        "n_old": len(old_ids), "n_new": len(new_ids),
        "id_overlap": round(id_overlap, 3),
        "n_exact": len(delta.exact_pairs), "n_churn": len(delta.churn_pairs),
        "n_modified": len(delta.modified),
        "n_removed": len(delta.removed), "n_added": len(delta.added),
        "modified_jaccards": modified_jacs,
        "low_sim_modified_examples": low_sim_examples,
        "cross_bucket_truth": cross_bucket_truth,
        "truth_stats": truth_stats,
        "grid": grid,
        "wrong_examples": wrong_examples,
        "big_shift_correct": big_shift_correct,
    }


def _worker(org: str, feed: str, queue) -> None:
    try:
        config = Config.load()
        repo = GtfsDataRepository(config=config)
        queue.put(survey(org, feed, repo, config))
    except Exception as e:  # noqa: BLE001
        queue.put({"status": f"error: {e}"})


def survey_with_timeout(org: str, feed: str, timeout_sec: int) -> dict:
    queue: multiprocessing.Queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_worker, args=(org, feed, queue))
    proc.start()
    proc.join(timeout_sec)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        return {"status": f"timeout({timeout_sec}s)"}
    return queue.get() if not queue.empty() else {"status": "error: no result"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            if r.get("status", "").startswith(("ok", "single_generation", "timeout")):
                done.add((r["org_id"], r["feed_id"]))

    repo = GtfsDataRepository(config=Config.load())
    feeds = list(EXTRA_FEEDS) + [
        f for f in select_feeds(repo, args.limit)
        if (f[0], f[1]) not in {(e[0], e[1]) for e in EXTRA_FEEDS}
    ]
    with OUT.open("a") as out:
        for n, (org, feed, org_name, pref) in enumerate(feeds, 1):
            if (org, feed) in done:
                continue
            t0 = time.time()
            record = survey_with_timeout(org, feed, args.timeout)
            record.update({"org_id": org, "feed_id": feed, "org_name": org_name,
                           "pref": pref, "elapsed": round(time.time() - t0, 1)})
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{n}/{len(feeds)}] {org}/{feed}: {record['status']} "
                  f"({record['elapsed']}s)")


if __name__ == "__main__":
    main()

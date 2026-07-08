"""M6: route_group シグナルの gtfs-data.jp 横断調査 (読み取り専用)。

各フィードの current (なければ最新) 世代について:
- route_id 数 → 同名 family 数 → 語幹 group 数 の3段階集約率
- 語幹一致で束なる family 対の停留所基底名集合 Jaccard (グループ化の妥当性)
- family 内パターンクラスタ間の停留所重なり (分割候補)

方針 (docs/design/route_group.md):
- GTFS-JP 固有フィールド (routes_jp / jp_parent_route_id 等) は一切使わない。
- 結果は data/survey/results.jsonl に1フィード1行で追記 (再実行時は処理済みをスキップ)。

実行: .venv.nosync/bin/python scripts/survey_route_groups.py [--limit 80]
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.identity import (  # noqa: E402
    extract_route_families,
    normalize_stop_base_name,
)
from gtfs_semantic_diff.identity.pattern_clustering import (  # noqa: E402
    cluster_patterns,
    extract_patterns,
)
from gtfs_semantic_diff.identity.route_family import route_to_family_map  # noqa: E402
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import rid_order  # noqa: E402

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("survey")

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "survey"
RESULTS = OUT_DIR / "results.jsonl"

# --- 語幹抽出 (調査対象の規則そのもの。M7 で config 化する候補) ---
# 先頭の「系統コードらしき並び」= 英数字 (全半角)・空白・ハイフン類・中点・下線・記号少々
_CODE_CHARS = r"0-9A-Za-z０-９Ａ-Ｚａ-ｚ\s　\-‐－_・.．:：/／#＃"
_STEM_RE = re.compile(rf"^[{_CODE_CHARS}]+")
MIN_STEM_LEN = 2


def stem_of(name: str) -> tuple[str, str]:
    """(語幹, 除去した接頭コード)。語幹が短すぎる場合は元名を語幹とする。"""
    normalized = unicodedata.normalize("NFKC", name).strip()
    m = _STEM_RE.match(normalized)
    if not m:
        return normalized, ""
    stem = normalized[m.end():].strip()
    if len(stem) < MIN_STEM_LEN:
        return normalized, ""
    return stem, m.group(0).strip()


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def survey_feed(repo: GtfsDataRepository, config: Config, org: str, feed: str) -> dict:
    files = repo.get_feed_files(org, feed, max_prev=1)
    newest = sorted(files, key=lambda f: rid_order(f.rid))[0]
    fetched = repo.download(newest)
    snap = load_snapshot(fetched.path, config=config, meta=newest.snapshot_meta(fetched.path))

    families = extract_route_families(snap)
    r2f = route_to_family_map(families)
    routes = snap.table("routes")
    n_routes = len(routes) if routes is not None else 0

    # family → 使用停留所の基底名集合
    stops = snap.table("stops")
    stop_base = (
        {sid: normalize_stop_base_name(nm) for sid, nm in zip(stops["stop_id"], stops["stop_name"])}
        if stops is not None
        else {}
    )
    trips = snap.table("trips")
    stop_times = snap.table("stop_times")
    family_stops: dict[str, set[str]] = defaultdict(set)
    if trips is not None and stop_times is not None:
        trip_to_family = {
            t: r2f.get(r, "") for t, r in zip(trips["trip_id"], trips["route_id"])
        }
        for trip_id, stop_id in zip(stop_times["trip_id"], stop_times["stop_id"]):
            fam = trip_to_family.get(trip_id)
            if fam:
                family_stops[fam].add(stop_base.get(stop_id, stop_id))

    # 語幹グループ
    stem_groups: dict[str, list[str]] = defaultdict(list)
    stems = {}
    for name in families:
        stem, prefix = stem_of(name)
        stems[name] = (stem, prefix)
        stem_groups[stem].append(name)

    multi = {s: sorted(fams) for s, fams in stem_groups.items() if len(fams) >= 2}
    pair_records = []
    for stem, fams in sorted(multi.items()):
        for a, b in itertools.combinations(fams, 2):
            pair_records.append(
                {
                    "stem": stem,
                    "a": a,
                    "b": b,
                    "stop_jaccard": round(jaccard(family_stops.get(a, set()),
                                                  family_stops.get(b, set())), 4),
                    "a_stops": len(family_stops.get(a, set())),
                    "b_stops": len(family_stops.get(b, set())),
                }
            )

    # 分割候補: family 内のパターンクラスタ対で停留所重なりが小さいもの
    split_candidates = []
    try:
        patterns = extract_patterns(snap, r2f, stop_base)
        clusters = cluster_patterns(patterns, config)
        by_family: dict[str, list] = defaultdict(list)
        for c in clusters:
            if c.trip_count >= 3:
                by_family[c.family].append(c)
        for fam, cs in by_family.items():
            for x, y in itertools.combinations(cs, 2):
                j = jaccard(set(x.representative.base_names), set(y.representative.base_names))
                if j < 0.1:
                    split_candidates.append(
                        {"family": fam, "jaccard": round(j, 4),
                         "a": x.cluster_id, "b": y.cluster_id,
                         "a_trips": x.trip_count, "b_trips": y.trip_count}
                    )
    except Exception as e:  # 調査なので個別失敗は記録して続行
        log.warning("%s/%s: pattern analysis failed: %s", org, feed, e)

    return {
        "org_id": org,
        "feed_id": feed,
        "rid": newest.rid,
        "from_date": newest.from_date,
        "n_routes": n_routes,
        "n_trips": len(trips) if trips is not None else 0,
        "n_families": len(families),
        "n_stem_groups": len(stem_groups),
        "multi_family_stems": len(multi),
        "families_in_multi": sum(len(f) for f in multi.values()),
        "stems": {name: {"stem": s, "prefix": p} for name, (s, p) in sorted(stems.items())},
        "pairs": pair_records,
        "split_candidates": split_candidates,
    }


def select_feeds(repo: GtfsDataRepository, limit: int) -> list[tuple[str, str, str, int]]:
    """都道府県で層化した決定的サンプリング。(org, feed, org_name, pref) のリスト。"""
    data = repo._get_json(f"{repo.base_url}/feeds")
    body = data.get("body", []) if isinstance(data, dict) else data
    feeds = []
    for fd in body:
        if fd.get("feed_is_discontinued"):
            continue
        feeds.append(
            (
                fd.get("organization_id", ""),
                fd.get("feed_id", ""),
                fd.get("organization_name", ""),
                fd.get("feed_pref_id", 0),
            )
        )
    # 検証フィードを強制包含
    forced = [("nagai-unyu", "Nagaibus"), ("chitetsu", "chitetsubus")]
    by_pref: dict[int, list] = defaultdict(list)
    for f in sorted(feeds, key=lambda x: (x[3], x[0], x[1])):
        by_pref[f[3]].append(f)
    selected = [f for f in feeds if (f[0], f[1]) in forced]
    # 都道府県ラウンドロビンで limit まで
    queues = [list(v) for _, v in sorted(by_pref.items())]
    i = 0
    while len(selected) < limit and any(queues):
        q = queues[i % len(queues)]
        if q:
            cand = q.pop(0)
            if (cand[0], cand[1]) not in {(s[0], s[1]) for s in selected}:
                selected.append(cand)
        i += 1
    return selected[:limit]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    config = Config.load()
    repo = GtfsDataRepository(config=config)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done.add((r["org_id"], r["feed_id"]))
            except json.JSONDecodeError:
                pass

    feeds = select_feeds(repo, args.limit)
    print(f"対象 {len(feeds)} フィード (処理済み {len(done)})")
    with open(RESULTS, "a", encoding="utf-8") as out:
        for n, (org, feed, org_name, pref) in enumerate(feeds, 1):
            if (org, feed) in done:
                continue
            try:
                record = survey_feed(repo, config, org, feed)
                record["org_name"] = org_name
                record["pref"] = pref
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                print(
                    f"[{n}/{len(feeds)}] {org}/{feed} ({org_name}): "
                    f"routes {record['n_routes']} → fam {record['n_families']} "
                    f"→ stem {record['n_stem_groups']} (多family語幹 {record['multi_family_stems']})"
                )
            except Exception as e:
                print(f"[{n}/{len(feeds)}] {org}/{feed}: SKIP ({e})")


if __name__ == "__main__":
    main()

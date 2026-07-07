"""方向グループの取りこぼし調査 (roadmap V2.1 の根拠計測と DoD 検証)。

各 route_group ページ内で、**別々の方向グループに落ちた**系統ペアのうち
「停留所集合 Jaccard >= direction_pair_jaccard かつ 共有停留所の順序整合度が
逆転側閾値以下 (=往復) / 同方向側閾値以上 (=区間便等)」のもの = 現行規則の
取りこぼし候補を数える。R15 改訂後は 0 になるはず (中間域は設計上残る)。

usage: .venv.nosync/bin/python scripts/survey_direction_groups.py
"""

from itertools import combinations
from pathlib import Path

from gtfs_semdiff.config import Config
from gtfs_semdiff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semdiff.load import GtfsDataRepository, load_snapshot
from gtfs_semdiff.load.repository import rid_order
from gtfs_semdiff.report.bundle import build_bundle
from gtfs_semdiff.report.presentation import order_agreement
from gtfs_semdiff.identity.route_group import stop_jaccard

config = Config.load()
repo = GtfsDataRepository(config=config)
PAIR_JACCARD = config.get("presentation", "direction_pair_jaccard", default=0.6)
REV_MAX = config.get("presentation", "direction_reversed_max_agreement", default=0.2)
SAME_MIN = config.get("presentation", "direction_same_min_agreement", default=0.8)
MIN_SHARED = config.get("presentation", "direction_min_shared_stops", default=3)


def analyze(tag, bundle):
    found = []
    kinds = {"bidirectional": 0, "one_way": 0, "loop": 0}
    for page in bundle["presentation"]["route_pages"]:
        dgs = page["overview"]["direction_groups"]
        for g in dgs:
            kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
        sys_dg = [(g, s) for g in dgs for s in g["systems"]]
        for (ga, a), (gb, b) in combinations(sys_dg, 2):
            if ga["id"] == gb["id"]:
                continue
            jac = stop_jaccard(set(a["stops"]), set(b["stops"]))
            if jac < PAIR_JACCARD:
                continue
            agree, n_shared = order_agreement(a["stops"], b["stops"])
            if agree is None or n_shared < MIN_SHARED:
                continue
            if agree <= REV_MAX:
                kind = "REVERSED"
            elif agree >= SAME_MIN:
                kind = "SAME_DIR"
            else:
                continue  # 中間域は設計上束ねない
            found.append((page["route_group"], kind, jac, agree,
                          f"{a['first_stop']}→{a['last_stop']}",
                          f"{b['first_stop']}→{b['last_stop']}"))
    for rg, kind, jac, agree, ea, eb in found:
        print(f"  [{kind}] {rg}: {ea} / {eb} jac={jac:.2f} agree={agree:.2f}")
    n_rev = sum(1 for f in found if f[1] == "REVERSED")
    n_same = sum(1 for f in found if f[1] == "SAME_DIR")
    print(f"== {tag}: pages={len(bundle['presentation']['route_pages'])} "
          f"dg構成={kinds} 取りこぼし: 逆転={n_rev} 同方向={n_same}")
    return n_rev, n_same


def show_routes(bundle, names):
    for page in bundle["presentation"]["route_pages"]:
        if not any(n in page["route_group"] for n in names):
            continue
        print(f"  ▶ {page['route_group']}:")
        for g in page["overview"]["direction_groups"]:
            legs = ", ".join(
                f"{s['leg']}: {s['first_stop']}→{s['last_stop']}"
                for s in g["systems"])
            print(f"     [{g['kind']}] {g['label']} ({legs})")


def api_pair(org, feed, old_rid=None, new_rid=None):
    files = sorted(repo.get_feed_files(org, feed, max_prev=4),
                   key=lambda f: rid_order(f.rid))
    if old_rid:
        fo = next(f for f in files if f.rid == old_rid)
        fn = next(f for f in files if f.rid == new_rid)
    else:
        fo, fn = files[1], files[0]
    o = load_snapshot(repo.download(fo).path, config=config, meta=fo.snapshot_meta())
    n = load_snapshot(repo.download(fn).path, config=config, meta=fn.snapshot_meta())
    es, rd, ident, delta = compare_snapshots_with_artifacts(o, n, config)
    ratio = es.accounting["explained_ratio"] if isinstance(es.accounting, dict) else None
    return build_bundle(o, n, config, es, rd, ident, delta), ratio


# DoD の目視確認対象 (V2.1 実測で取りこぼしを確認した路線)
SPOT_CHECKS = {
    "buzen": ["岩屋線"],
    "chitetsu": ["興人・国立高専線", "大森線", "福沢・国際大学", "池尻線"],
    "ashiya": ["22"],
    "hachinohe": ["多賀台団地線", "工業大学線", "平庭線", "種差線"],
    "nagai": ["前橋玉村線", "荻窪公園線"],
}

totals = [0, 0]
for tag, org, feed, old_rid, new_rid in [
    ("nagai", "nagai-unyu", "Nagaibus", None, None),
    ("chitetsu", "chitetsu", "chitetsubus", "prev_2", "prev_1"),
    ("buzen", "buzencity", "BuzenCityBus", None, None),
    ("oshu", "oshucity", "bus-oshucity-iwate-jp", None, None),
    ("ashiya", "ashiyatown", "AshiyaTownBus", None, None),
    ("hachinohe", "hachinohe", "hachinohe-citybus", None, None),
]:
    try:
        b, ratio = api_pair(org, feed, old_rid, new_rid)
        r = analyze(tag, b)
        if ratio is not None:
            print(f"   explained_ratio={ratio}")
        show_routes(b, SPOT_CHECKS.get(tag, []))
        totals[0] += r[0]
        totals[1] += r[1]
    except Exception as e:  # noqa: BLE001 — 調査スクリプトは続行優先
        print(f"== {tag}: ERROR {e}")

try:
    o = load_snapshot(Path("data/rinko_base.zip"), config=config)
    n = load_snapshot(Path("data/rinko_routes_changed.zip"), config=config)
    es, rd, ident, delta = compare_snapshots_with_artifacts(o, n, config)
    r = analyze("rinko", build_bundle(o, n, config, es, rd, ident, delta))
    totals[0] += r[0]
    totals[1] += r[1]
except Exception as e:  # noqa: BLE001
    print(f"== rinko: ERROR {e}")

print(f"\n合計 取りこぼし: 逆転={totals[0]} 同方向={totals[1]}")

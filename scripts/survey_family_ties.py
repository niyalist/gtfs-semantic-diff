"""G1 の副作用調査: 同点タイの発生箇所と「未使用の新 family 優先」の影響。

現行の2箇所のタイブレーク (段階1間引き・ページ割付) はどちらも
「confidence 同点 → 新 family 名の辞書順」で、新 family の再利用を許す。
このスクリプトは各検証ペアについて:
  1. ページ割付の同点タイ (旧 family の最良 confidence が複数辺で同点) を列挙
  2. 「同点なら未使用の新 family を優先」に変えた場合に割付が変わる旧 family
  3. 変わった結果、孤立が解消する新 family (= 新設扱いが消える候補)
を報告する。非同点の割付 (朝日町の MERGED 等) は定義上変わらない。
"""
import sys
from collections import defaultdict

sys.path.insert(0, "src")
from gtfs_semantic_diff.config import Config
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.identity import build_identity
from gtfs_semantic_diff.identity.route_family import (
    METHOD_CONTENT, METHOD_NAME)
from gtfs_semantic_diff.model.matchgraph import ENTITY_ROUTE_FAMILY

config = Config.load(None)

def survey(name, old_zip, new_zip):
    old = load_snapshot(old_zip, config=config)
    new = load_snapshot(new_zip, config=config)
    ident = build_identity(old, new, config)
    edges = [e for e in ident.graph.for_type(ENTITY_ROUTE_FAMILY)
             if e.method in (METHOD_NAME, METHOD_CONTENT)]
    by_old = defaultdict(list)
    for e in edges:
        by_old[e.old_id].append(e)
    # 現行割付 (辞書順) と 未使用優先割付
    cur_pick = {}
    for f, es in by_old.items():
        mx = max(e.confidence for e in es)
        cands = sorted(e.new_id for e in es if e.confidence == mx)
        cur_pick[f] = (mx, cands)
    # 現行: 各 old が cands[0]
    cur = {f: c[0] for f, (mx, c) in cur_pick.items()}
    # 未使用優先: 旧 family を (confidence 降順) で処理し、同点候補のうち
    # 未使用があればそれ (辞書順)、全部使用済みなら現行どおり先頭
    used = set()
    alt = {}
    for f in sorted(cur_pick, key=lambda f: (-cur_pick[f][0], f)):
        mx, cands = cur_pick[f]
        free = [n for n in cands if n not in used]
        pick = free[0] if free else cands[0]
        alt[f] = pick
        used.add(pick)
    ties = {f for f, (mx, c) in cur_pick.items() if len(c) > 1}
    changed = {f for f in cur if cur[f] != alt[f]}
    new_fams = {e.new_id for e in edges}
    matched_cur = set(cur.values())
    matched_alt = set(alt.values())
    rescued = matched_alt - matched_cur  # 孤立が解消する新 family
    print(f"== {name}: family対応エッジ {len(edges)} / 旧family {len(by_old)}")
    print(f"   同点タイの旧family: {len(ties)} / 割付が変わる: {len(changed)} / "
          f"孤立解消する新family: {len(rescued)}")
    for f in sorted(changed):
        print(f"   変更: {f}: {cur[f]} → {alt[f]} (conf {cur_pick[f][0]:.3f}, "
              f"候補{len(cur_pick[f][1])})")
    for comp in ident.family_components:
        if comp.get("pruned") or comp.get("demoted"):
            print(f"   [間引き成分] old={len(comp['old'])} new={len(comp['new'])} "
                  f"shape={comp['shape']} demoted={comp['demoted']} "
                  f"例={comp['old'][:2]}→{comp['new'][:2]}")

survey("朝日町 (M9基準: 21→9統合)", "data/asahi/old.zip", "data/asahi/new.zip")
survey("京都市バス", "data/kyoto/Kyoto_City_Bus_GTFS-20250630.zip",
       "data/kyoto/Kyoto_City_Bus_GTFS_20260630.zip")
survey("名古屋 (M9基準: 同名改称)", "data/nagoya/20250329_bus-gtfs-jp.zip",
       "data/nagoya/20260328_bus-gtfs-jp.zip")

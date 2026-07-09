"""Route Family 抽出 (旧 route_analyzer.py の Family 抽出部のみを移植)。

Route Family = 利用者が認識する「路線」。route_id は世代間で張り替わるため
(例: "101_1_1" → "101_1_2")、乗客向け名称でグループ化する。

名称の優先順: route_short_name → route_long_name → route_id。
正規化・あいまい一致は行わない (決定的挙動を優先、旧実装の設計判断を踏襲)。

世代間の対応 (linking) は **内容主導** (M9, docs/design/route_identity_review.md):
名称完全一致 (confidence 1.0) に加え、名称不一致の family は
「停留所クラスタの世代間対応で旧停留所名を新側へ翻訳した上での
停留所集合 Jaccard」で対応付ける。名前/ID の一致は同一性の定義ではなく
弱い事前 — 路線改称は停留所改称と同時に起きるのが普通で (施設名変更)、
旧実装のパターン鍵 Jaccard はそこで共倒れしていた (名古屋 鳴.ワイ→鳴.メグ)。
対応は N:M の関係として持ち、連結成分の形 (改称/統合/分割/再編) に分類する。
成分が大きすぎるものは注記に降格する (連鎖併合の破滅回避)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Config
from ..model import GtfsSnapshot, MatchEdge
from ..model.matchgraph import ENTITY_ROUTE_FAMILY

logger = logging.getLogger(__name__)

# エッジ method: 対応の証拠の種類
METHOD_NAME = "name_exact"          # 名称完全一致 (confidence 1.0)
METHOD_CONTENT = "stops_translated"  # 翻訳済み停留所集合 Jaccard (受理済み)
METHOD_CANDIDATE = "stops_candidate"  # 閾値未満・降格の仮説 (注記専用)


@dataclass
class RouteFamily:
    """同一名称の route_id 群。"""

    name: str
    route_ids: list[str] = field(default_factory=list)
    trip_count: int = 0
    # 所属する停車パターンのハッシュ集合 (基底名列ベース、pattern_clustering が設定)
    pattern_keys: set[str] = field(default_factory=set)


def family_name_of(short_name: str, long_name: str, route_id: str) -> str:
    """route の表示名 (family キー) を決める。"""
    short = short_name.strip()
    if short:
        return short
    long_ = long_name.strip()
    if long_:
        return long_
    return route_id.strip()


def extract_route_families(snapshot: GtfsSnapshot) -> dict[str, RouteFamily]:
    """routes.txt から family 名 → RouteFamily を作る。"""
    routes = snapshot.table("routes")
    if routes is None or routes.empty:
        return {}
    short_col = routes["route_short_name"] if "route_short_name" in routes.columns else ""
    long_col = routes["route_long_name"] if "route_long_name" in routes.columns else ""

    families: dict[str, RouteFamily] = {}
    for i, route_id in enumerate(routes["route_id"]):
        short = short_col.iloc[i] if hasattr(short_col, "iloc") else ""
        long_ = long_col.iloc[i] if hasattr(long_col, "iloc") else ""
        name = family_name_of(short, long_, route_id)
        family = families.setdefault(name, RouteFamily(name=name))
        family.route_ids.append(route_id)

    trips = snapshot.table("trips")
    if trips is not None and not trips.empty:
        route_to_family = route_to_family_map(families)
        for route_id in trips["route_id"]:
            name = route_to_family.get(route_id)
            if name:
                families[name].trip_count += 1

    logger.info(
        "%s: routes %d 件 → family %d 件",
        snapshot.meta.label(),
        len(routes),
        len(families),
    )
    return families


def route_to_family_map(families: dict[str, RouteFamily]) -> dict[str, str]:
    """route_id → family 名の逆引き。"""
    return {rid: f.name for f in families.values() for rid in f.route_ids}


def link_route_families(
    old_families: dict[str, RouteFamily],
    new_families: dict[str, RouteFamily],
    config: Config,
    old_family_stops: dict[str, set[str]] | None = None,
    new_family_stops: dict[str, set[str]] | None = None,
    stop_translation: dict[str, str] | None = None,
) -> list[MatchEdge]:
    """family の世代間対応 (M9: 内容主導)。

    - 名称完全一致 → METHOD_NAME (confidence 1.0)
    - 名称不一致の対: 旧停留所集合を stop_translation (停留所クラスタの
      世代間対応から得た旧基底名→新基底名) で翻訳し、新側集合との Jaccard で判定。
      受理 = Jaccard ≥ link_min_similarity。route_id を共有する対は
      閾値を id_bonus だけ緩める (弱い事前 — ID は定義ではない)。
    - 受理未満でも link_floor 以上は METHOD_CANDIDATE として保持 (注記専用。
      レポートの「内容が類似する候補」と閾値調整の材料)
    """
    g = lambda k, d: config.get("identity", "route_family", k, default=d)  # noqa: E731
    link_min = g("link_min_similarity", 0.5)
    id_bonus = g("id_bonus", 0.1)
    link_floor = g("link_floor", 0.3)
    old_family_stops = old_family_stops or {}
    new_family_stops = new_family_stops or {}
    stop_translation = stop_translation or {}
    edges: list[MatchEdge] = []

    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for name in sorted(old_families.keys() & new_families.keys()):
        edges.append(
            MatchEdge(
                entity_type=ENTITY_ROUTE_FAMILY,
                old_id=name,
                new_id=name,
                confidence=1.0,
                method=METHOD_NAME,
            )
        )
        matched_old.add(name)
        matched_new.add(name)

    accepted = 0
    for old_name in sorted(old_families.keys() - matched_old):
        old_stops = {
            stop_translation.get(s, s) for s in old_family_stops.get(old_name, set())
        }
        if not old_stops:
            continue
        old_rids = set(old_families[old_name].route_ids)
        for new_name in sorted(new_families.keys() - matched_new):
            new_stops = new_family_stops.get(new_name, set())
            if not new_stops:
                continue
            jaccard = len(old_stops & new_stops) / len(old_stops | new_stops)
            threshold = link_min
            if old_rids & set(new_families[new_name].route_ids):
                threshold = link_min - id_bonus
            if jaccard >= threshold:
                method = METHOD_CONTENT
                accepted += 1
            elif jaccard >= link_floor:
                method = METHOD_CANDIDATE
            else:
                continue
            edges.append(
                MatchEdge(
                    entity_type=ENTITY_ROUTE_FAMILY,
                    old_id=old_name,
                    new_id=new_name,
                    confidence=round(jaccard, 4),
                    method=method,
                )
            )
    logger.info(
        "route family link: old %d / new %d → 名称一致 %d + 内容受理 %d + 候補 %d",
        len(old_families),
        len(new_families),
        len(matched_old),
        accepted,
        len(edges) - len(matched_old) - accepted,
    )
    return edges


def build_stop_translation(
    old_clusters: dict, new_clusters: dict, stop_edges: list[MatchEdge],
    min_confidence: float,
) -> dict[str, str]:
    """停留所クラスタの世代間対応から旧基底名 → 新基底名の翻訳表を作る。

    各旧クラスタの最良エッジ (confidence 最大、同点は新基底名の辞書順) を採り、
    基底名が変わらない対応は表に含めない。誤翻訳は集合の1要素の摂動に
    とどまるため、家族対応の Jaccard には頑健。
    """
    best: dict[str, tuple[float, str]] = {}
    for e in stop_edges:
        if e.confidence < min_confidence:
            continue
        old_c = old_clusters.get(e.old_id)
        new_c = new_clusters.get(e.new_id)
        if old_c is None or new_c is None:
            continue
        cand = (e.confidence, new_c.base_name)
        cur = best.get(old_c.base_name)
        if cur is None or cand[0] > cur[0] or (cand[0] == cur[0] and cand[1] < cur[1]):
            best[old_c.base_name] = cand
    return {ob: nb for ob, (_, nb) in best.items() if nb != ob}


def _components_of(edge_list: list[MatchEdge]) -> list[dict]:
    """(名称+内容) エッジ列の連結成分。{old, new, content(エッジ列)} の list。"""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edge_list:
        ra, rb = find("o:" + e.old_id), find("n:" + e.new_id)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    members: dict[str, dict] = {}
    for e in edge_list:
        m = members.setdefault(find("o:" + e.old_id),
                               {"old": set(), "new": set(), "content": []})
        m["old"].add(e.old_id)
        m["new"].add(e.new_id)
        if e.method == METHOD_CONTENT:
            m["content"].append(e)
    return [members[k] for k in sorted(members)]


def classify_family_components(
    edges: list[MatchEdge],
    old_f2g: dict[str, str],
    new_f2g: dict[str, str],
    max_groups: int,
) -> tuple[list[dict], list[MatchEdge]]:
    """受理エッジの連結成分を分類し、大きすぎる成分を段階的に降格する。

    戻り値: (成分リスト, 更新済みエッジ列)。成分は内容エッジ (METHOD_CONTENT)
    を1本以上含むものだけを列挙する (純粋な名称一致 1:1 は現状どおり対象外)。

    成分の関与 route_group 数が max_groups を超えたときの降格は2段階
    (破滅回避、route_identity_review.md §3.3.1):
    1. **best-match 骨格への間引き**: 各旧 family の最良内容エッジ
       (confidence 最大、同点は新 family 名の辞書順) だけを残して再分解。
       コリドー共有による連鎖 (実例: 朝日町 宮崎境線↔市振線) を断ち、
       明白な対応 (類似度 1.0 等) を巻き添えにしない
    2. それでも上限を超える部分成分は内容エッジを METHOD_CANDIDATE に全降格
       (ページ統合も RENAMED 系イベントもせず、相互参照の注記だけが残る)
    """

    def group_count(m: dict) -> int:
        groups = {old_f2g.get(f, f) for f in m["old"]} | {
            new_f2g.get(f, f) for f in m["new"]
        }
        return len(groups)

    linked = [e for e in edges if e.method in (METHOD_NAME, METHOD_CONTENT)]
    accepted: list[dict] = []
    demoted_edges: set[tuple[str, str]] = set()
    pruned_flag: dict[str, bool] = {}

    for m in _components_of(linked):
        if not m["content"]:
            continue  # 名称一致のみの成分は従来どおり (イベント対象外)
        if group_count(m) <= max_groups:
            accepted.append(m)
            continue
        # 段階1: best-match 骨格に間引いて再分解
        best: dict[str, MatchEdge] = {}
        for e in sorted(m["content"], key=lambda e: (-e.confidence, e.new_id)):
            best.setdefault(e.old_id, e)
        kept = set((e.old_id, e.new_id) for e in best.values())
        demoted_edges |= {
            (e.old_id, e.new_id) for e in m["content"]
            if (e.old_id, e.new_id) not in kept
        }
        names_in = [e for e in linked
                    if e.method == METHOD_NAME and e.old_id in m["old"]]
        for sub in _components_of(list(best.values()) + names_in):
            if not sub["content"]:
                continue
            if group_count(sub) <= max_groups:
                pruned_flag[",".join(sorted(sub["old"]))] = True
                accepted.append(sub)
            else:
                # 段階2: 全降格 (注記のみ)
                demoted_edges |= {(e.old_id, e.new_id) for e in sub["content"]}
                accepted.append(dict(sub, demoted=True))

    components: list[dict] = []
    for m in accepted:
        n_old, n_new = len(m["old"]), len(m["new"])
        shape = ("renamed" if (n_old, n_new) == (1, 1)
                 else "merged" if n_new == 1
                 else "split" if n_old == 1 else "restructured")
        components.append({
            "old": sorted(m["old"]),
            "new": sorted(m["new"]),
            "shape": shape,
            "similarity": min(e.confidence for e in m["content"]),
            "demoted": bool(m.get("demoted")),
            "pruned": pruned_flag.get(",".join(sorted(m["old"])), False),
        })

    if demoted_edges:
        edges = [
            MatchEdge(e.entity_type, e.old_id, e.new_id, e.confidence,
                      METHOD_CANDIDATE)
            if e.method == METHOD_CONTENT and (e.old_id, e.new_id) in demoted_edges
            else e
            for e in edges
        ]
        logger.info(
            "family 対応: 連鎖成分の間引き/降格 %d エッジ (group 数上限 %d)",
            len(demoted_edges), max_groups,
        )
    return components, edges

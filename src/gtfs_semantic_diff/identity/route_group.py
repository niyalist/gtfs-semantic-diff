"""route_group: family の上の「路線ブランド」集約層。

仕様は docs/design/route_group.md (M6 の 80 フィード横断調査で確定):
- グループ化は **語幹一致のみ**。語幹 = NFKC 正規化した表示名から先頭の
  系統コードらしき連続 (英数字・空白・ハイフン類・中点等) を除去したもの。
- ガード: 語幹が min_stem_len 未満、またはストップワード (「系統」等の一般語)
  に退化した場合はグループ化しない (正規化後の元名を語幹とする)。
- 停留所集合の Jaccard は**ゲートに使わない**。group の凝集度 (median pairwise
  Jaccard) として算出し、レポートが「枝線構造」の注記に使う。
  (枝番系統は同一ブランド下の別コリドーであることが普通: 30A/30B 前橋玉村線の
  共通停留所は1つ。幾何で足切りすると動機のケースを棄却してしまう。)

GTFS-JP 固有フィールド (jp_parent_route_id 等) は使わない (CLAUDE.md 開発ルール)。
"""

from __future__ import annotations

import itertools
import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from ..config import Config

# NFKC 後の「系統コードらしき先頭の連続」。全角英数・記号は NFKC で半角化される。
_CODE_RUN = re.compile(r"^[0-9A-Za-z\s\-‐_・.:/#]+")


@dataclass
class RouteGroup:
    """語幹を共有する family の束 (路線ブランド)。"""

    name: str  # 語幹 (グループ表示名)
    families: list[str] = field(default_factory=list)
    # 構成 family 対の停留所基底名集合 Jaccard の中央値。単独 family は None。
    cohesion: float | None = None


def stem_of(name: str, config: Config) -> str:
    """family 表示名 → グループ化キー (語幹)。ガードに落ちたら正規化済み元名。"""
    min_len = config.get("identity", "route_group", "min_stem_len", default=2)
    stopwords = set(
        config.get("identity", "route_group", "stem_stopwords", default=[])
    )
    normalized = unicodedata.normalize("NFKC", name).strip()
    m = _CODE_RUN.match(normalized)
    stem = normalized[m.end():].strip() if m else normalized
    if len(stem) < min_len or stem in stopwords:
        return normalized
    return stem


def stop_jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def build_route_groups(
    family_stops: dict[str, set[str]],
    config: Config,
) -> tuple[dict[str, str], list[RouteGroup]]:
    """family 名 → group 名の対応と RouteGroup 一覧を返す。

    family_stops: family 名 → その family が停車する停留所基底名の集合
    (凝集度算出用。グループ化判定には使わない)。
    全 family がいずれかの group に所属する (単独 family は自身のみの group)。
    """
    by_stem: dict[str, list[str]] = {}
    for name in sorted(family_stops):
        by_stem.setdefault(stem_of(name, config), []).append(name)

    family_to_group: dict[str, str] = {}
    groups: list[RouteGroup] = []
    for stem in sorted(by_stem):
        members = by_stem[stem]
        cohesion = None
        if len(members) >= 2:
            values = [
                stop_jaccard(family_stops[a], family_stops[b])
                for a, b in itertools.combinations(members, 2)
            ]
            cohesion = round(statistics.median(values), 4)
        groups.append(RouteGroup(name=stem, families=members, cohesion=cohesion))
        for name in members:
            family_to_group[name] = stem
    return family_to_group, groups

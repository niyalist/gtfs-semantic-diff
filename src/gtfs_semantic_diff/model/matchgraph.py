"""MatchGraph: L1 世代間同定の結果 (仮説管理)。

対応付けは (old, new, confidence, method) のエッジとして保持する。
低 confidence の対応も破棄せず、下流ルールの整合で昇格/棄却する
(docs/design/architecture.md「MatchGraph は仮説管理」)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# エッジが結ぶエンティティの種別
ENTITY_STOP_CLUSTER = "stop_cluster"
ENTITY_ROUTE_FAMILY = "route_family"
ENTITY_PATTERN_CLUSTER = "pattern_cluster"
ENTITY_SERVICE = "service"

ENTITY_TYPES = frozenset(
    {ENTITY_STOP_CLUSTER, ENTITY_ROUTE_FAMILY, ENTITY_PATTERN_CLUSTER, ENTITY_SERVICE}
)


@dataclass(frozen=True)
class MatchEdge:
    """旧世代エンティティ ↔ 新世代エンティティの対応仮説1本。

    old_id / new_id の一方が空文字列のエッジは「対応相手なし」
    (新設・廃止候補) を表す。
    """

    entity_type: str
    old_id: str
    new_id: str
    confidence: float  # 0.0–1.0
    method: str  # 例 "name_exact", "proximity", "lcs_similarity"

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type: {self.entity_type!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence out of range: {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "old_id": self.old_id,
            "new_id": self.new_id,
            "confidence": self.confidence,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MatchEdge":
        return cls(
            entity_type=d["entity_type"],
            old_id=d["old_id"],
            new_id=d["new_id"],
            confidence=d["confidence"],
            method=d["method"],
        )


@dataclass
class MatchGraph:
    """L1 の出力。エンティティ種別ごとの対応エッジ集合。

    matches_for_old/new は呼び出し毎の全エッジ走査だとルール段が
    O(照会数 × エッジ数) で非線形化する (IN-1) ため、(種別, ID) 索引を
    遅延構築して引く。add() で索引は無効化される。
    """

    edges: list[MatchEdge] = field(default_factory=list)

    # 注釈を付けない = dataclass フィールドにしない (asdict / 等値比較へ漏らさない)
    _by_old = None
    _by_new = None

    def add(self, edge: MatchEdge) -> None:
        self.edges.append(edge)
        self._by_old = self._by_new = None

    def for_type(self, entity_type: str) -> list[MatchEdge]:
        return [e for e in self.edges if e.entity_type == entity_type]

    def _ensure_index(self) -> None:
        if self._by_old is not None:
            return
        by_old: dict[tuple[str, str], list[MatchEdge]] = {}
        by_new: dict[tuple[str, str], list[MatchEdge]] = {}
        for e in self.edges:
            by_old.setdefault((e.entity_type, e.old_id), []).append(e)
            by_new.setdefault((e.entity_type, e.new_id), []).append(e)
        # 安定ソートなので同 confidence の順序は従来の sorted(全走査結果) と一致
        for bucket in by_old.values():
            bucket.sort(key=lambda e: e.confidence, reverse=True)
        for bucket in by_new.values():
            bucket.sort(key=lambda e: e.confidence, reverse=True)
        self._by_old, self._by_new = by_old, by_new

    def matches_for_old(self, entity_type: str, old_id: str) -> list[MatchEdge]:
        """旧 ID に対する対応候補を confidence 降順で返す。"""
        self._ensure_index()
        return list(self._by_old.get((entity_type, old_id), ()))

    def matches_for_new(self, entity_type: str, new_id: str) -> list[MatchEdge]:
        """新 ID に対する対応候補を confidence 降順で返す。"""
        self._ensure_index()
        return list(self._by_new.get((entity_type, new_id), ()))

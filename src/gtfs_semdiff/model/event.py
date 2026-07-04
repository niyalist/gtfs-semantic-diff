"""ChangeEvent / ChangeEventSet: L2 の出力であり本ツールの正出力 (安定インタフェース)。

JSON スキーマは docs/design/ontology.md「イベントの構造」と
docs/design/architecture.md「ChangeEventSet JSON トップレベル」に準拠する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .event_types import EVENT_TYPES, SEVERITIES

SCHEMA_VERSION = "0.2"


@dataclass
class ChangeEvent:
    """意味的変化イベント1件。

    evidence はこのイベントが「説明」する RawDiff の ID リストで、
    説明会計の台帳になる。1つの RawDiff を複数イベントが参照してよいが、
    主説明イベントは accounting 側で一意に管理する。
    """

    event_id: str  # evt_XXXXXX
    type: str  # EVENT_TYPES のいずれか
    subject: dict[str, Any] = field(default_factory=dict)
    old_ref: dict[str, Any] | None = None
    new_ref: dict[str, Any] | None = None
    quantification: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 1.0
    severity: str = ""  # 未指定ならイベントタイプの既定値を採用
    narrative_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {self.type!r}")
        if not self.severity:
            self.severity = EVENT_TYPES[self.type].default_severity
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence out of range: {self.confidence}")

    @property
    def display_name_ja(self) -> str:
        return EVENT_TYPES[self.type].display_name_ja

    @property
    def display_name_en(self) -> str:
        return EVENT_TYPES[self.type].display_name_en

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "subject": self.subject,
            "old_ref": self.old_ref,
            "new_ref": self.new_ref,
            "quantification": self.quantification,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "severity": self.severity,
            "display_name_ja": self.display_name_ja,
            "display_name_en": self.display_name_en,
            "narrative_hints": self.narrative_hints,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChangeEvent":
        return cls(
            event_id=d["event_id"],
            type=d["type"],
            subject=d.get("subject", {}),
            old_ref=d.get("old_ref"),
            new_ref=d.get("new_ref"),
            quantification=d.get("quantification", {}),
            evidence=list(d.get("evidence", [])),
            confidence=d.get("confidence", 1.0),
            severity=d.get("severity", ""),
            narrative_hints=d.get("narrative_hints", {}),
        )


@dataclass
class Accounting:
    """説明会計のサマリ。explained_ratio は常に計測・表示する (最重要設計原則 1)。"""

    rawdiff_total: int = 0
    explained: int = 0
    residual_breakdown_by_file: dict[str, int] = field(default_factory=dict)

    @property
    def explained_ratio(self) -> float:
        if self.rawdiff_total == 0:
            return 1.0
        return self.explained / self.rawdiff_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "rawdiff_total": self.rawdiff_total,
            "explained": self.explained,
            "explained_ratio": round(self.explained_ratio, 4),
            "residual_breakdown_by_file": self.residual_breakdown_by_file,
        }


@dataclass
class ChangeEventSet:
    """世代ペア1組の比較結果全体。CLI / report / 将来の Web はすべてこの JSON の消費者。

    context はレポート描画等の消費者向け補助データ (時間帯別本数プロファイル等)。
    events / accounting が正であり、context は再計算可能な派生情報に限る。
    """

    feed: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    events: list[ChangeEvent] = field(default_factory=list)
    accounting: Accounting = field(default_factory=Accounting)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "feed": self.feed,
            "generated_at": self.generated_at,
            "config_snapshot": self.config_snapshot,
            "events": [e.to_dict() for e in self.events],
            "accounting": self.accounting.to_dict(),
            "context": self.context,
        }

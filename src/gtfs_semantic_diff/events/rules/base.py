"""Rule プロトコルと RuleContext。

各ルールモジュールは `extract(ctx: RuleContext) -> None` を実装し、
ctx.emit() でイベントを発行する。emit は同時に evidence を台帳へ記録する
(発行と会計を分離しない — evidence の付け忘れを構造的に防ぐ)。
カスケード順序は events/rules/__init__.py の CASCADE が定義する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ...config import Config
from ...identity import IdentityResult
from ...model import ChangeEvent, GtfsSnapshot, RawDiffSet
from ..accounting import EvidenceLedger
from ..evidence import EvidenceIndex
from ..timebands import TimeBands
from ..tripdelta import TripDelta

logger = logging.getLogger(__name__)


@dataclass
class RuleContext:
    old: GtfsSnapshot
    new: GtfsSnapshot
    config: Config
    identity: IdentityResult
    rawdiffs: RawDiffSet
    index: EvidenceIndex
    ledger: EvidenceLedger
    trip_delta: TripDelta
    time_bands: TimeBands
    events: list[ChangeEvent] = field(default_factory=list)
    _next_id: int = 1

    def emit(
        self,
        type_: str,
        subject: dict[str, Any],
        evidence: list[str],
        *,
        quantification: dict[str, Any] | None = None,
        old_ref: dict[str, Any] | None = None,
        new_ref: dict[str, Any] | None = None,
        confidence: float = 1.0,
        severity: str = "",
        primary: bool = True,
    ) -> ChangeEvent:
        """イベントを発行し evidence を台帳に記録する。"""
        event = ChangeEvent(
            event_id=f"evt_{self._next_id:06d}",
            type=type_,
            subject=subject,
            old_ref=old_ref,
            new_ref=new_ref,
            quantification=quantification or {},
            evidence=sorted(set(evidence)),
            confidence=confidence,
            severity=severity,
        )
        self._next_id += 1
        self.ledger.consume(event.event_id, event.evidence, primary=primary)
        self.events.append(event)
        return event

    # --- 共通ヘルパ ---

    @property
    def accept_confidence(self) -> float:
        return self.config.get("events", "accept_confidence", default=0.5)

    def best_match_for_old(self, entity_type: str, old_id: str):
        """accept_confidence 以上の最良エッジ (なければ None)。"""
        matches = self.identity.graph.matches_for_old(entity_type, old_id)
        if matches and matches[0].confidence >= self.accept_confidence:
            return matches[0]
        return None

    def best_match_for_new(self, entity_type: str, new_id: str):
        matches = self.identity.graph.matches_for_new(entity_type, new_id)
        if matches and matches[0].confidence >= self.accept_confidence:
            return matches[0]
        return None

    def unconsumed_ids(self, ids: list[str]) -> list[str]:
        """まだどのイベントの evidence にもなっていない ID のみ返す。"""
        return [i for i in ids if self.ledger.primary_event_of(i) is None]

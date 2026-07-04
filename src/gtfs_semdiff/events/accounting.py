"""説明会計 (explanation accounting): evidence 台帳と explained_ratio 算出。

最重要設計原則 1 (CLAUDE.md): L0 の全 RawDiff は、いずれかの ChangeEvent の
evidence に紐づくか、UNEXPLAINED_RESIDUAL としてレポートされる。
網羅性はこの台帳で構造的に保証する。

- 1つの RawDiff を複数イベントが説明してよい (多対多)。
- ただし主説明イベント (primary) は1つ: 最初に primary=True で消費した
  イベントが保持される。
- UNEXPLAINED_RESIDUAL イベントによる消費は「説明済み」に数えない。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..model import Accounting, ChangeEvent, RawDiff, RawDiffSet

logger = logging.getLogger(__name__)


class UnknownRawDiffError(KeyError):
    """台帳に存在しない rawdiff_id を evidence として消費しようとした。"""


class EvidenceLedger:
    """RawDiff 全件を分母とする evidence 台帳。"""

    def __init__(self, rawdiffs: RawDiffSet):
        self.rawdiffs = rawdiffs
        self._by_id = rawdiffs.by_id()
        self._explained_by: dict[str, list[str]] = {}  # rawdiff_id → event_id 列
        self._primary: dict[str, str] = {}  # rawdiff_id → 主説明 event_id
        self._residual_event_ids: set[str] = set()

    def consume(self, event_id: str, rawdiff_ids: Iterable[str], primary: bool = True) -> None:
        """イベントが RawDiff 群を説明したことを記録する。"""
        for rid in rawdiff_ids:
            if rid not in self._by_id:
                raise UnknownRawDiffError(f"台帳にない rawdiff_id: {rid} (event {event_id})")
            self._explained_by.setdefault(rid, []).append(event_id)
            if primary and rid not in self._primary:
                self._primary[rid] = event_id

    # --- 照会 ---

    def _is_explained(self, rawdiff_id: str) -> bool:
        """UNEXPLAINED_RESIDUAL 以外のイベントに説明されているか。"""
        return any(
            eid not in self._residual_event_ids
            for eid in self._explained_by.get(rawdiff_id, ())
        )

    def explained_count(self) -> int:
        return sum(1 for rid in self._explained_by if self._is_explained(rid))

    def unexplained(self) -> list[RawDiff]:
        """UNEXPLAINED_RESIDUAL 以外に説明されていない RawDiff (ID 順)。会計の残差。"""
        return [d for d in self.rawdiffs.diffs if not self._is_explained(d.rawdiff_id)]

    def unconsumed(self) -> list[RawDiff]:
        """どのイベントの evidence にも入っていない RawDiff。残差イベント生成の入力。"""
        return [d for d in self.rawdiffs.diffs if d.rawdiff_id not in self._explained_by]

    def primary_event_of(self, rawdiff_id: str) -> str | None:
        return self._primary.get(rawdiff_id)

    # --- 出力 ---

    def residual_events(self, event_id_start: int = 1) -> list[ChangeEvent]:
        """未消費分をファイル単位の UNEXPLAINED_RESIDUAL イベントにまとめ、台帳に記録する。"""
        by_file: dict[str, list[str]] = {}
        for d in self.unconsumed():
            by_file.setdefault(d.file, []).append(d.rawdiff_id)

        events = []
        for i, (filename, ids) in enumerate(sorted(by_file.items()), start=event_id_start):
            event = ChangeEvent(
                event_id=f"evt_{i:06d}",
                type="UNEXPLAINED_RESIDUAL",
                subject={"file": filename},
                quantification={"rawdiff_count": len(ids)},
                evidence=ids,
            )
            self._residual_event_ids.add(event.event_id)
            self.consume(event.event_id, ids)
            events.append(event)
        if events:
            total = sum(len(e.evidence) for e in events)
            logger.info("UNEXPLAINED_RESIDUAL: %d 件 (%d ファイル)", total, len(events))
        return events

    def accounting(self) -> Accounting:
        breakdown: dict[str, int] = {}
        for d in self.rawdiffs.diffs:
            if not self._is_explained(d.rawdiff_id):
                breakdown[d.file] = breakdown.get(d.file, 0) + 1
        return Accounting(
            rawdiff_total=len(self.rawdiffs),
            explained=self.explained_count(),
            residual_breakdown_by_file=dict(sorted(breakdown.items())),
        )

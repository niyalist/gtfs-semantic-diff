"""コアパイプライン: GtfsSnapshot 2つ → ChangeEventSet (純粋関数)。

M1 時点ではルールカスケード未実装のため、L0 の RawDiff 全件が
UNEXPLAINED_RESIDUAL になる (explained_ratio = 0)。M2 以降で
identity/ → events/rules/ がこの間に入る。
"""

from __future__ import annotations

import datetime
import logging

from ..config import Config
from ..diff0 import enumerate_rawdiffs
from ..model import ChangeEventSet, GtfsSnapshot, RawDiffSet
from .accounting import EvidenceLedger

logger = logging.getLogger(__name__)


def compare_snapshots(
    old: GtfsSnapshot, new: GtfsSnapshot, config: Config
) -> tuple[ChangeEventSet, RawDiffSet]:
    """世代ペアを比較し、(ChangeEventSet, RawDiff 全件) を返す。"""
    rawdiffs = enumerate_rawdiffs(old, new)
    ledger = EvidenceLedger(rawdiffs)

    # M2 以降: ここで identity/ の MatchGraph 構築と events/rules/ のカスケードが入る

    events = ledger.residual_events(event_id_start=1)
    accounting = ledger.accounting()
    logger.info(
        "explained_ratio = %.4f (%d / %d)",
        accounting.explained_ratio,
        accounting.explained,
        accounting.rawdiff_total,
    )

    event_set = ChangeEventSet(
        feed={
            "org_id": new.meta.org_id or old.meta.org_id,
            "feed_id": new.meta.feed_id or old.meta.feed_id,
            "old_rid": old.meta.rid,
            "new_rid": new.meta.rid,
            "old_source": old.meta.source,
            "new_source": new.meta.source,
        },
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        config_snapshot=config.raw,
        events=events,
        accounting=accounting,
    )
    return event_set, rawdiffs

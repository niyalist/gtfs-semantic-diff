"""データクラス: GtfsSnapshot, RawDiff, MatchGraph, ChangeEvent (docs/design/ontology.md 準拠)."""

from .event import SCHEMA_VERSION, Accounting, ChangeEvent, ChangeEventSet
from .event_types import EVENT_TYPES, EventTypeDef, display_name_ja
from .matchgraph import MatchEdge, MatchGraph
from .rawdiff import RawDiff, RawDiffSet
from .snapshot import GtfsSnapshot, SnapshotMeta

__all__ = [
    "SCHEMA_VERSION",
    "Accounting",
    "ChangeEvent",
    "ChangeEventSet",
    "EVENT_TYPES",
    "EventTypeDef",
    "display_name_ja",
    "MatchEdge",
    "MatchGraph",
    "RawDiff",
    "RawDiffSet",
    "GtfsSnapshot",
    "SnapshotMeta",
]

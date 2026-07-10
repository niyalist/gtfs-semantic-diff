"""RawDiff: L0 網羅diff の1件。説明台帳 (explanation ledger) の最小単位。

diff0/ が全ファイル・全フィールドを列挙して生成し、events/ の各ルールが
evidence として消費する。未消費のものは UNEXPLAINED_RESIDUAL になる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# RawDiff の種別
KIND_FILE_ADDED = "file_added"
KIND_FILE_REMOVED = "file_removed"
KIND_COLUMN_ADDED = "column_added"
KIND_COLUMN_REMOVED = "column_removed"
KIND_ROW_ADDED = "row_added"
KIND_ROW_REMOVED = "row_removed"
KIND_FIELD_CHANGED = "field_changed"

RAWDIFF_KINDS = frozenset(
    {
        KIND_FILE_ADDED,
        KIND_FILE_REMOVED,
        KIND_COLUMN_ADDED,
        KIND_COLUMN_REMOVED,
        KIND_ROW_ADDED,
        KIND_ROW_REMOVED,
        KIND_FIELD_CHANGED,
    }
)


@dataclass(frozen=True)
class RawDiff:
    """L0 で検出した生差分1件。ID は世代ペア内で安定・一意 (rawdiff_XXXXXX)。"""

    rawdiff_id: str
    file: str  # 例 "stop_times.txt"
    kind: str  # RAWDIFF_KINDS のいずれか
    key: tuple[str, ...] = ()  # 行を同定する主キー値列 (row/field 系のみ)
    column: str = ""  # field_changed / column_* のとき対象カラム名
    old_value: str | None = None
    new_value: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in RAWDIFF_KINDS:
            raise ValueError(f"unknown RawDiff kind: {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rawdiff_id": self.rawdiff_id,
            "file": self.file,
            "kind": self.kind,
            "key": list(self.key),
            "column": self.column,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RawDiff":
        return cls(
            rawdiff_id=d["rawdiff_id"],
            file=d["file"],
            kind=d["kind"],
            key=tuple(d.get("key", ())),
            column=d.get("column", ""),
            old_value=d.get("old_value"),
            new_value=d.get("new_value"),
        )


@dataclass
class RawDiffSet:
    """世代ペア1組分の RawDiff 全件。件数集計は説明台帳の分母になる。"""

    diffs: list[RawDiff] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.diffs)

    def by_id(self) -> dict[str, RawDiff]:
        return {d.rawdiff_id: d for d in self.diffs}

    def count_by_file(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.diffs:
            counts[d.file] = counts.get(d.file, 0) + 1
        return dict(sorted(counts.items()))

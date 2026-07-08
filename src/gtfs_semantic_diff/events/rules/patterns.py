"""B群: 運行パターンレベルのイベント (subject: family × 方向 × パターン)。

検出条件 (docs/design/ontology.md B群):
対象は「同一 trip_id のまま停車列が変わった trip」(trip_delta.modified の
うち base_seq が変化したもの)。停車列の新旧を difflib opcodes で分解し、

- 端点への追加   → PATTERN_EXTENDED (運行区間延長)
- 端点からの削除 → PATTERN_TRUNCATED (運行区間短縮)
- 中間への挿入   → 1停留所: STOP_INSERTED_IN_PATTERN / 連続: DETOUR_ADDED
- 中間からの削除 → 1停留所: STOP_REMOVED_FROM_PATTERN / 連続: DETOUR_REMOVED

evidence はその trip の stop_times.txt 差分 (行追加・削除・stop_id 変更)。
trip が丸ごと入れ替わるパターン変化 (removed/added 対) は C群の便数比較と
区別が難しいため M3 では C群 (SERVICE_*) 側で会計する。

TIME_BAND_VARIANT / SHAPE_CHANGED 詳細は M5 (roadmap 参照)。
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

from .base import RuleContext

NAME = "patterns"

# opcode 分類結果 → (イベントタイプ, 説明キー)
_MIDDLE_INSERT_SINGLE = "STOP_INSERTED_IN_PATTERN"
_MIDDLE_INSERT_RUN = "DETOUR_ADDED"
_MIDDLE_DELETE_SINGLE = "STOP_REMOVED_FROM_PATTERN"
_MIDDLE_DELETE_RUN = "DETOUR_REMOVED"


def classify_sequence_changes(
    old_seq: tuple[str, ...], new_seq: tuple[str, ...]
) -> list[tuple[str, dict]]:
    """停車列の変化をイベントタイプ列に分解する (順序保存の編集操作ベース)。"""
    changes: list[tuple[str, dict]] = []
    matcher = SequenceMatcher(None, old_seq, new_seq, autojunk=False)
    opcodes = matcher.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        removed = list(old_seq[i1:i2])
        added = list(new_seq[j1:j2])
        at_start = i1 == 0 and j1 == 0
        at_end = i2 == len(old_seq) and j2 == len(new_seq)
        if added and (at_start or at_end) and not removed:
            changes.append(
                ("PATTERN_EXTENDED", {"stops": added, "end": "start" if at_start else "end"})
            )
        elif removed and (at_start or at_end) and not added:
            changes.append(
                ("PATTERN_TRUNCATED", {"stops": removed, "end": "start" if at_start else "end"})
            )
        else:
            if removed:
                type_ = _MIDDLE_DELETE_SINGLE if len(removed) == 1 else _MIDDLE_DELETE_RUN
                changes.append((type_, {"stops": removed}))
            if added:
                type_ = _MIDDLE_INSERT_SINGLE if len(added) == 1 else _MIDDLE_INSERT_RUN
                changes.append((type_, {"stops": added}))
    return changes


def extract(ctx: RuleContext) -> None:
    # (family, direction, day_type, 変化内容) 単位で trip をまとめて1イベントに
    grouped: dict[tuple, list] = defaultdict(list)
    for old_trip, new_trip in ctx.trip_delta.modified:
        if old_trip.base_seq == new_trip.base_seq:
            continue
        for type_, detail in classify_sequence_changes(old_trip.base_seq, new_trip.base_seq):
            key = (
                new_trip.family,
                new_trip.direction,
                new_trip.day_type,
                type_,
                tuple(detail["stops"]),
                detail.get("end", ""),
            )
            grouped[key].append((old_trip, new_trip, detail))

    for key in sorted(grouped, key=str):
        family, direction, day_type, type_, stops, end = key
        members = grouped[key]
        trip_ids = sorted({n.trip_id for _, n, _ in members})
        # evidence: 当該 trip の stop_times / trips 差分の全体。
        # 経路変更は下流停留所の時刻・headsign の連鎖変更を引き起こすため、
        # trip 単位で丸ごとこのイベントが説明する (最初のイベントが primary)。
        evidence = ctx.index.trip_cascade_ids(trip_ids)
        quantification = {"trip_count": len(trip_ids), "stops": list(stops)}
        if end:
            quantification["end"] = end
        ctx.emit(
            type_,
            subject={
                "route_family": family,
                "direction": direction,
                "day_type": day_type,
            },
            evidence=evidence,
            quantification=quantification,
            old_ref={"pattern": list(members[0][0].base_seq)},
            new_ref={"pattern": list(members[0][1].base_seq)},
        )

"""E群 (M3 は粗い受け皿、正規化比較は roadmap M5):

- FEED_VALIDITY_CHANGED: calendar.txt の start_date / end_date の書き換え
  (ontology F群の定義「feed_info の期限・calendar 末尾の書き換え」に対応)。
- HOLIDAY_EXCEPTION_CHANGED: calendar_dates.txt の例外差分。M3 では
  day_type グループ単位の件数集計のみで、有効期間の重なり正規化は行わない
  (confidence 0.8 で仮説扱い)。
- DAYTYPE_RESTRUCTURED: 世代間で day_type 集合が変化した場合 (例:
  土曜・休日ダイヤの calendar_dates 化)。calendar.txt の行差分と、
  該当 service の calendar_dates 差分を消費する。
"""

from __future__ import annotations

from collections import defaultdict

from .base import RuleContext

NAME = "calendars"


def extract(ctx: RuleContext) -> None:
    _daytype_restructured(ctx)
    _validity(ctx)
    _holiday_exceptions(ctx)


def _daytype_restructured(ctx: RuleContext) -> None:
    old_types = ctx.identity.old_day_types
    new_types = ctx.identity.new_day_types
    if old_types == new_types:
        return
    # calendar.txt の行追加・削除・曜日フラグ変更を消費
    evidence = [
        d.rawdiff_id
        for d in ctx.index.by_file.get("calendar.txt", [])
        if d.kind in ("row_added", "row_removed")
        or (
            d.kind == "field_changed"
            and d.column
            in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        )
    ]
    evidence = ctx.unconsumed_ids(evidence)
    ctx.emit(
        "DAYTYPE_RESTRUCTURED",
        subject={"scope": "feed"},
        evidence=evidence,
        old_ref={"day_types": sorted(old_types)},
        new_ref={"day_types": sorted(new_types)},
        confidence=0.8,
    )


def _validity(ctx: RuleContext) -> None:
    evidence = [
        d.rawdiff_id
        for d in ctx.index.by_file.get("calendar.txt", [])
        if d.kind == "field_changed" and d.column in ("start_date", "end_date")
    ]
    evidence = ctx.unconsumed_ids(evidence)
    if not evidence:
        return
    ctx.emit(
        "FEED_VALIDITY_CHANGED",
        subject={"files": ["calendar.txt"]},
        evidence=evidence,
        quantification={"changed_rows": len(evidence)},
    )


def _holiday_exceptions(ctx: RuleContext) -> None:
    diffs = ctx.index.by_file.get("calendar_dates.txt", [])
    if not diffs:
        return
    # service の day_type (旧→新の順で解決) ごとにまとめる
    grouped: dict[str, list[str]] = defaultdict(list)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in diffs:
        service_id = d.key[0] if d.key else ""
        day_type = ctx.old.day_types.get(service_id) or ctx.new.day_types.get(
            service_id, "irregular"
        )
        grouped[day_type].append(d.rawdiff_id)
        counts[day_type][d.kind] += 1

    for day_type in sorted(grouped):
        evidence = ctx.unconsumed_ids(grouped[day_type])
        if not evidence:
            continue
        ctx.emit(
            "HOLIDAY_EXCEPTION_CHANGED",
            subject={"day_type": day_type},
            evidence=evidence,
            quantification=dict(sorted(counts[day_type].items())),
            confidence=0.8,  # M5 で有効期間正規化するまでは粗い会計
        )

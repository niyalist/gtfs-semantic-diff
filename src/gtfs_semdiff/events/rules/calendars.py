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


def _service_period(snapshot) -> tuple[str, str] | None:
    """スナップショットの運行有効期間 (YYYYMMDD)。API メタ → calendar の順で解決。"""
    meta_from = snapshot.meta.from_date.replace("-", "")
    meta_to = snapshot.meta.to_date.replace("-", "")
    if meta_from and meta_to:
        return meta_from, meta_to
    dates: list[str] = []
    cal = snapshot.table("calendar")
    if cal is not None and {"start_date", "end_date"} <= set(cal.columns):
        dates += [d.strip() for d in cal["start_date"]] + [d.strip() for d in cal["end_date"]]
    cd = snapshot.table("calendar_dates")
    if cd is not None and "date" in getattr(cd, "columns", ()):
        dates += [d.strip() for d in cd["date"]]
    dates = [d for d in dates if d]
    if not dates:
        return None
    return min(dates), max(dates)


def _holiday_exceptions(ctx: RuleContext) -> None:
    """calendar_dates の例外差分。

    M5: 新旧フィードの有効期間の**重なり窓**で正規化する。重なり窓の外の
    日付差分はフィード期間のスライドに伴う機械的な差 (旧期間にしかない日の
    削除等) であり、窓内の差分だけが実質的な運行例外の変更。
    """
    diffs = ctx.index.by_file.get("calendar_dates.txt", [])
    if not diffs:
        return
    old_period = _service_period(ctx.old)
    new_period = _service_period(ctx.new)
    overlap = None
    if old_period and new_period:
        start = max(old_period[0], new_period[0])
        end = min(old_period[1], new_period[1])
        if start <= end:
            overlap = (start, end)

    grouped: dict[str, list[str]] = defaultdict(list)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in diffs:
        service_id = d.key[0] if d.key else ""
        date = d.key[1] if len(d.key) > 1 else ""
        day_type = ctx.old.day_types.get(service_id) or ctx.new.day_types.get(
            service_id, "irregular"
        )
        grouped[day_type].append(d.rawdiff_id)
        if overlap and date:
            bucket = "within_overlap" if overlap[0] <= date <= overlap[1] else "outside_overlap"
        else:
            bucket = "unknown_window"
        counts[day_type][bucket] += 1

    for day_type in sorted(grouped):
        evidence = ctx.unconsumed_ids(grouped[day_type])
        if not evidence:
            continue
        q = dict(sorted(counts[day_type].items()))
        if overlap:
            q["overlap_window"] = [overlap[0], overlap[1]]
        # 窓内の実質変更が1件もなければ期間スライドに伴う機械差のみ
        substantive = counts[day_type].get("within_overlap", 0) > 0
        ctx.emit(
            "HOLIDAY_EXCEPTION_CHANGED",
            subject={"day_type": day_type},
            evidence=evidence,
            quantification={**q, "substantive": substantive},
            confidence=1.0 if overlap else 0.8,
        )

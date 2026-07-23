"""GENERATION_SCOPE: 同梱世代と比較範囲 (SD2、docs/design/service_days.md §2.2)。

窓内区間対比較で比較対象外とした同梱世代 (期限切れ・非 primary 区間の世代) の
行差分を claim する受け皿。カスケード最後尾に置き、他ルールが説明しなかった
構造行 (世代の calendar 行の出現/消滅、窓外世代の trips/stop_times 等) だけを
拾う — 通常フィード (scope=None) では何もしない。
"""

from __future__ import annotations

from .base import RuleContext

NAME = "generations"

_SERVICE_KEYED = ("calendar.txt", "calendar_dates.txt")
_TRIP_KEYED = ("trips.txt", "stop_times.txt", "frequencies.txt")


def extract(ctx: RuleContext) -> None:
    scope = ctx.window_scope
    if scope is None:
        return

    excluded_services = scope.old_excluded_services | scope.new_excluded_services
    excluded_trips = scope.old_excluded_trips | scope.new_excluded_trips

    evidence: list[str] = []
    for fname in _SERVICE_KEYED:
        for d in ctx.index.by_file.get(fname, []):
            if d.key and str(d.key[0]) in excluded_services:
                evidence.append(d.rawdiff_id)
    for fname in _TRIP_KEYED:
        for d in ctx.index.by_file.get(fname, []):
            if d.key and str(d.key[0]) in excluded_trips:
                evidence.append(d.rawdiff_id)
    if scope.multi_generation:
        # 世代構造そのものの行 (primary 世代の calendar 行の出現/消滅) も、
        # ここまでの規則が説明しなかった分は世代交代として回収する
        active = (scope.old_universe or frozenset()) | (
            scope.new_universe or frozenset()
        )
        for fname in _SERVICE_KEYED:
            for d in ctx.index.by_file.get(fname, []):
                if (
                    d.kind in ("row_added", "row_removed")
                    and d.key
                    and str(d.key[0]) in active
                ):
                    evidence.append(d.rawdiff_id)

    evidence = ctx.unconsumed_ids(evidence)
    if not evidence and not scope.multi_generation:
        return

    window_from, window_to = scope.window.as_text()
    ctx.emit(
        "GENERATION_SCOPE",
        subject={"scope": "feed"},
        evidence=evidence,
        quantification={
            "comparison_window": [window_from, window_to],
            "primary_periods": [list(iv.as_text()) for iv in scope.primary_intervals],
            "identical_periods": [
                list(iv.as_text()) for iv in scope.identical_intervals
            ],
            "old_excluded_services": len(scope.old_excluded_services),
            "new_excluded_services": len(scope.new_excluded_services),
            "old_excluded_trips": len(scope.old_excluded_trips),
            "new_excluded_trips": len(scope.new_excluded_trips),
        },
        confidence=1.0,
    )

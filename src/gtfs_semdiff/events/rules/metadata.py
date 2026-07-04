"""F群: 運賃・運用形態・メタデータ層 (網羅性の受け皿)。

- FARE_CHANGED: fare_attributes / fare_rules の差分を1イベントで消費。
  M5 詳細化: 新旧 fare_attributes を突き合わせ、廃止/新設運賃 (fare_id と
  価格)・価格改定を quantification に分解する。
- DEMAND_RESPONSIVE_CHANGE: GTFS で追える範囲でのデマンド化・予約制移行の
  兆候。(1) stop_times の pickup_type / drop_off_type が 2 (要電話) /
  3 (要調整) へ変化、(2) continuous_pickup / continuous_drop_off の変化、
  (3) booking_rules / location_groups 系ファイルの出現、(4) frequencies.txt
  への移行。単独では断定できないため、兆候数に応じた confidence
  (1個 0.5 〜 複数 0.9) を明示する。
- HEADSIGN_CHANGED: trip_headsign / stop_headsign の表記変更のみ
  (経路・時刻変更に伴う分は B/C 群が消費済みのため、未消費分だけが対象)。
- FEED_VALIDITY_CHANGED / AGENCY_INFO_CHANGED / TRANSLATION_CHANGED:
  対象ファイルの全差分を1イベントで消費。
"""

from __future__ import annotations

from collections import defaultdict

from .base import RuleContext

NAME = "metadata"


def extract(ctx: RuleContext) -> None:
    _fare(ctx)
    _demand_responsive(ctx)
    _headsigns(ctx)
    _simple_file(ctx, "FEED_VALIDITY_CHANGED", ["feed_info.txt"])
    _simple_file(ctx, "AGENCY_INFO_CHANGED", ["agency.txt", "agency_jp.txt"])
    _simple_file(ctx, "TRANSLATION_CHANGED", ["translations.txt"])


# --- 運賃 ---


def _fare_prices(snapshot) -> dict[str, str]:
    fa = snapshot.table("fare_attributes")
    if fa is None or "fare_id" not in getattr(fa, "columns", ()):
        return {}
    price_col = fa["price"] if "price" in fa.columns else [""] * len(fa)
    return dict(zip(fa["fare_id"], price_col))


def _fare(ctx: RuleContext) -> None:
    evidence = ctx.unconsumed_ids(
        ctx.index.file_ids("fare_attributes.txt") + ctx.index.file_ids("fare_rules.txt")
    )
    if not evidence:
        return
    old_prices = _fare_prices(ctx.old)
    new_prices = _fare_prices(ctx.new)
    removed = [
        {"fare_id": fid, "price": old_prices[fid]}
        for fid in sorted(set(old_prices) - set(new_prices))
    ]
    added = [
        {"fare_id": fid, "price": new_prices[fid]}
        for fid in sorted(set(new_prices) - set(old_prices))
    ]
    price_changes = [
        {"fare_id": fid, "old_price": old_prices[fid], "new_price": new_prices[fid]}
        for fid in sorted(set(old_prices) & set(new_prices))
        if old_prices[fid] != new_prices[fid]
    ]
    rules_changed = len(ctx.index.by_file.get("fare_rules.txt", []))
    quantification = {"fare_rules_diffs": rules_changed}
    if removed:
        quantification["removed_fares"] = removed[:20]
    if added:
        quantification["added_fares"] = added[:20]
    if price_changes:
        quantification["price_changes"] = price_changes[:20]
    ctx.emit(
        "FARE_CHANGED",
        subject={"scope": "feed"},
        evidence=evidence,
        quantification=quantification,
    )


# --- デマンド化兆候 ---

_DEMAND_VALUES = {"2", "3"}  # 2: 要電話予約, 3: 運転手と要調整


def _demand_responsive(ctx: RuleContext) -> None:
    signals: list[str] = []
    evidence: list[str] = []

    flag_ids = []
    for d in ctx.index.by_file.get("stop_times.txt", []):
        if (
            d.kind == "field_changed"
            and d.column in ("pickup_type", "drop_off_type")
            and ((d.new_value or "").strip() in _DEMAND_VALUES
                 or (d.old_value or "").strip() in _DEMAND_VALUES)
        ):
            flag_ids.append(d.rawdiff_id)
    flag_ids = ctx.unconsumed_ids(flag_ids)
    if flag_ids:
        signals.append(f"pickup/drop_off_type の予約制フラグ変更 {len(flag_ids)} 件")
        evidence += flag_ids

    cont_ids = [
        d.rawdiff_id
        for f in ("stop_times.txt", "routes.txt")
        for d in ctx.index.by_file.get(f, [])
        if d.kind == "field_changed"
        and d.column in ("continuous_pickup", "continuous_drop_off")
    ]
    cont_ids = ctx.unconsumed_ids(cont_ids)
    if cont_ids:
        signals.append(f"continuous_pickup/drop_off の変更 {len(cont_ids)} 件")
        evidence += cont_ids

    for filename in ("booking_rules.txt", "location_groups.txt",
                     "location_group_stops.txt", "frequencies.txt"):
        ids = ctx.unconsumed_ids(ctx.index.file_ids(filename))
        if ids:
            signals.append(f"{filename} の変化")
            evidence += ids

    if not signals:
        return
    confidence = min(0.9, 0.5 + 0.15 * (len(signals) - 1))
    ctx.emit(
        "DEMAND_RESPONSIVE_CHANGE",
        subject={"scope": "feed"},
        evidence=evidence,
        quantification={"signals": signals},
        confidence=confidence,
        severity="major" if len(signals) >= 2 else "minor",
    )


# --- 行先表示 ---


def _headsigns(ctx: RuleContext) -> None:
    trip_family = {}
    for t in list(ctx.trip_delta.old_trips.values()) + list(ctx.trip_delta.new_trips.values()):
        trip_family[t.trip_id] = t.family

    grouped: dict[str, list] = defaultdict(list)  # family → [(rawdiff_id, old, new)]
    for filename, column in (("trips.txt", "trip_headsign"), ("stop_times.txt", "stop_headsign")):
        for d in ctx.index.by_file.get(filename, []):
            if d.kind != "field_changed" or d.column != column:
                continue
            if ctx.ledger.primary_event_of(d.rawdiff_id) is not None:
                continue
            family = trip_family.get(d.key[0] if d.key else "", "")
            grouped[family].append((d.rawdiff_id, d.old_value, d.new_value))

    for family in sorted(grouped):
        members = grouped[family]
        samples = sorted({(o or "", n or "") for _, o, n in members})[:5]
        ctx.emit(
            "HEADSIGN_CHANGED",
            subject={"route_family": family} if family else {"scope": "feed"},
            evidence=[rid for rid, _, _ in members],
            quantification={
                "changed_fields": len(members),
                "samples": [f"{o} → {n}" for o, n in samples],
            },
        )


# --- 単純ファイル ---


def _simple_file(ctx: RuleContext, type_: str, filenames: list[str]) -> None:
    evidence = []
    changed: dict[str, str] = {}
    for filename in filenames:
        for d in ctx.index.by_file.get(filename, []):
            evidence.append(d.rawdiff_id)
            if d.kind == "field_changed":
                changed[d.column] = f"{d.old_value} → {d.new_value}"
    evidence = ctx.unconsumed_ids(evidence)
    if not evidence:
        return
    ctx.emit(
        type_,
        subject={"files": filenames},
        evidence=evidence,
        quantification={"changed_fields": changed} if changed else {},
    )

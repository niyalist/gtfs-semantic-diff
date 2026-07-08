"""TECHNICAL_ID_CHURN (trip): 意味的変化を伴わない trip_id の張り替え。

検出条件: trip_delta.exact_pairs のうち trip_id が異なる組。内容署名
(family, 方向, day_type, 停車列, 全時刻) が完全一致しているため、
「ダイヤは同一で ID だけ変わった」と断定できる (confidence 1.0)。

evidence: 当該 trip 対の trips.txt / stop_times.txt の全行差分。
family × day_type 単位で1イベントにまとめ、データ更新の健全性検証
(レポートのデータ検証章) に使う。route_id 張り替えは A群 routes.py が扱う。
"""

from __future__ import annotations

from collections import defaultdict

from .base import RuleContext

NAME = "technical"


def extract(ctx: RuleContext) -> None:
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for old_trip, new_trip in ctx.trip_delta.churn_pairs:
        grouped[(new_trip.family, new_trip.day_type)].append((old_trip, new_trip))

    for (family, day_type) in sorted(grouped):
        pairs = grouped[(family, day_type)]
        old_ids = sorted(o.trip_id for o, _ in pairs)
        new_ids = sorted(n.trip_id for _, n in pairs)
        evidence = ctx.index.trip_cascade_ids(old_ids) + ctx.index.trip_cascade_ids(new_ids)
        evidence = ctx.unconsumed_ids(evidence)
        if not evidence:
            continue  # 差分ゼロ (ID も同一) や他ルール消費済み
        ctx.emit(
            "TECHNICAL_ID_CHURN",
            subject={"route_family": family, "day_type": day_type, "entity": "trip_id"},
            evidence=evidence,
            quantification={"trip_pairs": len(pairs)},
        )

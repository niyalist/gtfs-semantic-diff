"""SD5: 運行日世界 (層0.5) — service_days.md §9.1。

世界 = day_type ラベル内で実効運行日集合 (SD1 定義) の重なりで結ばれる
service 連結成分。集計 (便数 = 1日あたり)・表示・世代間対応の単位になる。
便対応 v1 のブロッキングはラベル単位のまま (世界は matching を変えない)。

設計判断 (docs/verification/day_pattern_survey.md の検証に基づく):
- 全 day_type に適用する (特定日に限らない — 四半期分割・世代同居・季節分割は
  レギュラー型が複数世界になる)
- 期間重複による世界融合はデータの主張として受容する
- world_id はラベル内の初日順の連番 ("weekday#1" 等) で決定的
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..load.day_types import _exception_dates, effective_date_list
from ..load.day_types import _CALENDAR_DAY_COLUMNS as _DAY_COLUMNS
from .windows import snapshot_window


def effective_dates_by_service(snapshot) -> dict[str, list[str]]:
    """全 service の実効運行日リスト (SD1 と同一定義)。

    フラグ行があり期間が解析できる service は 期間×フラグ − 削除 + 追加、
    それ以外 (calendar 行なし・全フラグ0・期間不明) は 追加 − 削除。
    フィード有効期間でクリップする。"""
    added_map, removed_map = _exception_dates(snapshot.table("calendar_dates"))
    window = snapshot_window(snapshot)
    window_text = window.as_text() if window is not None else None
    result: dict[str, list[str]] = {}
    done: set[str] = set()
    cal = snapshot.table("calendar")
    if cal is not None and not cal.empty and (
        set(_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            sid = str(row.get("service_id", "")).strip()
            flags = tuple(
                str(row[c]).strip() == "1" for c in _DAY_COLUMNS
            )
            computed = effective_date_list(
                flags, str(row["start_date"]), str(row["end_date"]),
                added_map.get(sid, set()), removed_map.get(sid, set()),
                window_text,
            ) if any(flags) else None
            if computed is not None:
                result[sid] = computed[0]
                done.add(sid)
    for sid in set(snapshot.day_types) - done:
        removed = removed_map.get(sid, set())
        result[sid] = sorted(
            d for d in set(added_map.get(sid, [])) if d not in removed
        )
    return result


@dataclass(frozen=True)
class DayWorld:
    """1つの運行日世界。dates は実効日 (昇順)。"""

    day_type: str
    world_id: str  # "weekday#1" 等 (ラベル内初日順の連番、決定的)
    services: tuple[str, ...]
    dates: tuple[str, ...]


@dataclass(frozen=True)
class DayWorlds:
    """スナップショット1つ分の世界分解。"""

    worlds: tuple[DayWorld, ...]
    by_service: dict  # service_id → world_id
    multi_labels: frozenset  # 複数世界を持つ day_type ラベル

    def world_of(self, service_id: str) -> str:
        return self.by_service.get(service_id, "")

    def by_id(self) -> dict:
        return {w.world_id: w for w in self.worlds}


def build_day_worlds(snapshot) -> DayWorlds:
    """day_type ラベル毎に実効日の重なりで service を連結成分に分ける。"""
    dates = effective_dates_by_service(snapshot)
    by_label: dict[str, list[str]] = defaultdict(list)
    for sid, dt in snapshot.day_types.items():
        by_label[dt].append(sid)

    worlds: list[DayWorld] = []
    by_service: dict[str, str] = {}
    multi: set[str] = set()
    for label in sorted(by_label):
        sids = sorted(by_label[label])
        # 反復マージ (日付 → 既出成分) — 決定的
        groups: list[set[str]] = []
        date_owner: dict[str, int] = {}
        for sid in sids:
            hit = {date_owner[d] for d in dates.get(sid, ()) if d in date_owner}
            if hit:
                root = min(hit)
                groups[root].add(sid)
                for gi in hit - {root}:
                    groups[root] |= groups[gi]
                    groups[gi] = set()
            else:
                root = len(groups)
                groups.append({sid})
            for m in groups[root]:
                for d in dates.get(m, ()):
                    date_owner[d] = root
        comps = [g for g in groups if g]
        comps.sort(key=lambda g: (min(
            (dates[s][0] for s in g if dates.get(s)), default="99999999"
        ), sorted(g)))
        if len(comps) > 1:
            multi.add(label)
        for i, g in enumerate(comps, start=1):
            wid = f"{label}#{i}"
            wdates = tuple(sorted({d for s in g for d in dates.get(s, ())}))
            worlds.append(DayWorld(
                day_type=label, world_id=wid,
                services=tuple(sorted(g)), dates=wdates,
            ))
            for s in g:
                by_service[s] = wid
    return DayWorlds(
        worlds=tuple(worlds), by_service=by_service,
        multi_labels=frozenset(multi),
    )

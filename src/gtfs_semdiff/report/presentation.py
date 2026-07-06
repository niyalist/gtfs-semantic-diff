"""プレゼンテーションモデル生成 (docs/design/presentation.md、凍結要件 R1〜R17)。

events + identity + trip_delta から、路線 (route_group) ページのビューモデルを
決定的ルールで合成する。コア (イベント・説明会計) は読み取りのみ (設計原則1)。
スコープは「路線に紐付く変更」— 運賃・メタデータ等は対象外 (検証モード側)。

構成 (1 route_group = 1 ページ):
  overview   ① 路線概要 (方向グループ・運行系統・代表停車列・地図用ポリライン)
  summary    ② 変化サマリー (Lev.1〜5 のカスケード、上位が下位を吸収)
  band_matrix ③ 時間帯別本数 (方向グループ→曜日固定順→系統、集計→内訳)
  timetables  ④ 新旧時刻表 (LCS 併合の停留所軸、trip 対応付き = 差分表示の素材)
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..config import Config
from ..events.timebands import TimeBands
from ..events.tripdelta import TripDelta, TripInfo
from ..identity import IdentityResult
from ..identity.route_group import stop_jaccard
from ..model import ChangeEventSet
from ..model.matchgraph import ENTITY_PATTERN_CLUSTER

logger = logging.getLogger(__name__)

# R16: 曜日の固定順 (閾値ではなく表示仕様の定数)
DAY_ORDER = ["weekday", "saturday", "sunday_holiday", "weekend", "daily", "irregular"]

_PATTERN_EVENT_TYPES = {
    "PATTERN_EXTENDED", "PATTERN_TRUNCATED", "STOP_INSERTED_IN_PATTERN",
    "STOP_REMOVED_FROM_PATTERN", "DETOUR_ADDED", "DETOUR_REMOVED",
}


def day_sort_key(day_type: str) -> int:
    return DAY_ORDER.index(day_type) if day_type in DAY_ORDER else len(DAY_ORDER)


# --- 停留所軸の併合 (R17) ---


def _lcs_table(a: tuple, b: tuple) -> list[list[int]]:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp


def merge_axis(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    """2列の最短共通超列 (LCS ベース)。結果は a・b 双方を部分列として含む。"""
    dp = _lcs_table(a, b)
    out: list[str] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            out.append(a[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            out.append(a[i - 1])
            i -= 1
        else:
            out.append(b[j - 1])
            j -= 1
    out.extend(reversed(a[:i]))
    out.extend(reversed(b[:j]))
    return tuple(reversed(out))


def build_stop_axis(sequences: list[tuple[str, ...]]) -> tuple[str, ...]:
    """全停車列を1本の停留所軸に併合する (全列の超列)。長い列から決定的順序で。"""
    if not sequences:
        return ()
    ordered = sorted(set(sequences), key=lambda s: (-len(s), s))
    axis = ordered[0]
    for seq in ordered[1:]:
        axis = merge_axis(axis, seq)
    return axis


def align_to_axis(seq: tuple[str, ...], axis: tuple[str, ...]) -> list[int]:
    """seq 各位置 → 軸位置 (貪欲 in-order)。軸に無い停留所は -1 (表示対象外)。

    軸は同一バケット内の全停車列 (経路変更 trip の旧列を含む) の超列として
    構築されるため、通常 -1 は出ないが、防御的に扱う。"""
    positions = []
    k = 0
    for stop in seq:
        j = k
        while j < len(axis) and axis[j] != stop:
            j += 1
        if j < len(axis):
            positions.append(j)
            k = j + 1
        else:
            positions.append(-1)
    return positions


# --- 本体 ---


def build_presentation(
    event_set: ChangeEventSet,
    identity: IdentityResult,
    trip_delta: TripDelta,
    config: Config,
) -> dict:
    builder = _Builder(event_set, identity, trip_delta, config)
    return builder.build()


class _Builder:
    def __init__(self, event_set, identity, trip_delta, config):
        self.events = event_set.events
        self.identity = identity
        self.delta = trip_delta
        self.config = config
        self.bands = TimeBands(
            config.get("events", "frequency", "time_bands", default=[])
        )
        self.min_trips = config.get("presentation", "system_min_trips", default=2)
        self.full_coverage = config.get("presentation", "full_coverage", default=0.9)
        self.pair_jaccard = config.get(
            "presentation", "direction_pair_jaccard", default=0.6
        )
        self.accept = config.get("events", "accept_confidence", default=0.5)

        self.f2g = {**identity.old_family_to_group, **identity.new_family_to_group}
        # trip → cluster (base_seq 経由)
        self.old_seq2cluster = self._seq_to_cluster(identity.old_pattern_clusters)
        self.new_seq2cluster = self._seq_to_cluster(identity.new_pattern_clusters)
        # 停留所基底名 → 座標 (新優先)
        self.coords: dict[str, tuple[float, float]] = {}
        for clusters in (identity.old_stop_clusters, identity.new_stop_clusters):
            for c in clusters.values():
                self.coords.setdefault(c.base_name, (c.lat, c.lon))
        # 停留所の世代別存在 (時刻表の軸ステータス用)
        self.old_stop_names = {c.base_name for c in identity.old_stop_clusters.values()}
        self.new_stop_names = {c.base_name for c in identity.new_stop_clusters.values()}

    @staticmethod
    def _seq_to_cluster(clusters) -> dict:
        m = {}
        for c in clusters:
            for p in c.patterns:
                m[(p.family, p.direction, p.base_names)] = c.cluster_id
        return m

    def build(self) -> dict:
        groups = sorted(
            {self.f2g.get(t.family, t.family)
             for t in list(self.delta.old_trips.values()) + list(self.delta.new_trips.values())
             if t.family}
        )
        pages = []
        for group in groups:
            page = self._build_page(group)
            if page:
                pages.append(page)
        # 変化のあるページを先に (Lev.1 > その他の変化 > 変化なし)、次に名前順
        pages.sort(key=lambda p: (0 if p["summary"]["level1"] else
                                  (1 if p["has_changes"] else 2), p["route_group"]))
        return {"day_type_order": DAY_ORDER, "route_pages": pages}

    # --- ページ構築 ---

    def _group_trips(self, trips: dict[str, TripInfo], group: str) -> list[TripInfo]:
        return [t for t in trips.values() if self.f2g.get(t.family) == group]

    def _build_page(self, group: str) -> dict | None:
        old_trips = self._group_trips(self.delta.old_trips, group)
        new_trips = self._group_trips(self.delta.new_trips, group)
        if not old_trips and not new_trips:
            return None

        systems = self._systems(group, old_trips, new_trips)
        dgroups = self._direction_groups(systems)
        band_matrix = self._band_matrix(dgroups, old_trips, new_trips)
        summary = self._summary(group, dgroups, systems, band_matrix,
                                len(old_trips), len(new_trips))
        timetables = self._timetables(dgroups, old_trips, new_trips)

        has_changes = bool(
            summary["level1"] or summary["level2"] or summary["level3"]
            or summary["level4"] or summary["level5"]["retimed_trips"]
            or summary["level5"]["notes"]
        )
        return {
            "route_group": group,
            "families": sorted({t.family for t in old_trips + new_trips}),
            "has_changes": has_changes,
            "overview": {
                "trip_totals": {"old": len(old_trips), "new": len(new_trips)},
                "direction_groups": dgroups,
            },
            "summary": summary,
            "band_matrix": band_matrix,
            "timetables": timetables,
        }

    # --- 運行系統 (新旧クラスタの統合ビュー) ---

    def _systems(self, group, old_trips, new_trips) -> list[dict]:
        old_clusters = {
            c.cluster_id: c for c in self.identity.old_pattern_clusters
            if self.f2g.get(c.family) == group
        }
        new_clusters = {
            c.cluster_id: c for c in self.identity.new_pattern_clusters
            if self.f2g.get(c.family) == group
        }
        link = {}  # old_id → new_id (accept 以上の最良)
        for old_id in old_clusters:
            matches = self.identity.graph.matches_for_old(ENTITY_PATTERN_CLUSTER, old_id)
            if matches and matches[0].confidence >= self.accept \
                    and matches[0].new_id in new_clusters:
                link[old_id] = matches[0].new_id

        def trips_of(trips, cluster, seq2cluster):
            return sum(
                1 for t in trips
                if seq2cluster.get((t.family, t.direction, t.base_seq)) == cluster
            )

        def earliest(cluster_old, cluster_new):
            deps = [
                t.first_departure
                for t in old_trips
                if self.old_seq2cluster.get((t.family, t.direction, t.base_seq)) == cluster_old
            ] + [
                t.first_departure
                for t in new_trips
                if self.new_seq2cluster.get((t.family, t.direction, t.base_seq)) == cluster_new
            ]
            return min((d for d in deps if d), default="99:99:99")

        systems = []
        linked_new = set(link.values())
        for new_id, c in sorted(new_clusters.items()):
            old_id = next((o for o, n in link.items() if n == new_id), None)
            rep = c.representative
            systems.append({
                "system_id": new_id,
                "family": c.family,
                "direction": c.direction,
                "status": "continued" if old_id else "added",
                "stops": list(rep.base_names),
                "first_stop": rep.base_names[0],
                "last_stop": rep.base_names[-1],
                "trips_old": trips_of(old_trips, old_id, self.old_seq2cluster) if old_id else 0,
                "trips_new": trips_of(new_trips, new_id, self.new_seq2cluster),
                "old_system_id": old_id,
                "earliest_departure": earliest(old_id, new_id),
                "polyline": [self.coords[s] for s in rep.base_names if s in self.coords],
            })
        for old_id, c in sorted(old_clusters.items()):
            if old_id in link:
                continue
            rep = c.representative
            systems.append({
                "system_id": f"old:{old_id}",
                "family": c.family,
                "direction": c.direction,
                "status": "removed",
                "stops": list(rep.base_names),
                "first_stop": rep.base_names[0],
                "last_stop": rep.base_names[-1],
                "trips_old": trips_of(old_trips, old_id, self.old_seq2cluster),
                "trips_new": 0,
                "old_system_id": old_id,
                "earliest_departure": earliest(old_id, None),
                "polyline": [self.coords[s] for s in rep.base_names if s in self.coords],
            })
        return systems

    # --- 方向グループ (R15: クラスタ由来、direction_id 非依存) ---

    def _direction_groups(self, systems: list[dict]) -> list[dict]:
        n = len(systems)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = systems[i], systems[j]
                jac = stop_jaccard(set(a["stops"]), set(b["stops"]))
                if jac < self.pair_jaccard:
                    continue
                reversed_pair = (a["first_stop"] == b["last_stop"]
                                 and a["last_stop"] == b["first_stop"])
                same_leg = (a["first_stop"] == b["first_stop"]
                            and a["last_stop"] == b["last_stop"])
                if reversed_pair or same_leg:
                    union(i, j)

        by_root: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            by_root[find(i)].append(i)

        dgroups = []
        for members in by_root.values():
            group_systems = [systems[i] for i in members]
            # 代表 = 便数最多の系統。その向きを forward とする
            canon = min(
                group_systems,
                key=lambda s: (-(s["trips_new"] + s["trips_old"]),
                               s["earliest_departure"], s["system_id"]),
            )
            loop = canon["first_stop"] == canon["last_stop"]
            for s in group_systems:
                if loop:
                    s["leg"] = "forward"
                elif (s["first_stop"] == canon["last_stop"]
                        and s["last_stop"] == canon["first_stop"]):
                    s["leg"] = "reverse"
                else:
                    s["leg"] = "forward"
            if loop:
                kind, label = "loop", f"{canon['first_stop']} 循環"
            elif any(s["leg"] == "reverse" for s in group_systems):
                kind = "bidirectional"
                label = f"{canon['first_stop']} ⇄ {canon['last_stop']}"
            else:
                kind, label = "one_way", f"{canon['first_stop']} → {canon['last_stop']}"
            dgroups.append({
                "id": "",  # 後で採番
                "kind": kind,
                "label": label,
                "leg_labels": {
                    "forward": f"{canon['last_stop']}方面" if not loop else label,
                    "reverse": f"{canon['first_stop']}方面",
                },
                "systems": sorted(group_systems,
                                  key=lambda s: (-s["trips_new"] - s["trips_old"],
                                                 s["system_id"])),
            })
        dgroups.sort(key=lambda g: -sum(s["trips_new"] + s["trips_old"]
                                        for s in g["systems"]))
        for i, g in enumerate(dgroups):
            g["id"] = f"dg{i}"
            for s in g["systems"]:
                s["direction_group"] = g["id"]
        return dgroups

    # --- ③ 本数マトリクス (R3, R14 の土台) ---

    def _band_matrix(self, dgroups, old_trips, new_trips) -> dict:
        sys_by_old_cluster = {}
        sys_by_new_cluster = {}
        for g in dgroups:
            for s in g["systems"]:
                if s["old_system_id"]:
                    sys_by_old_cluster[s["old_system_id"]] = s
                if not s["system_id"].startswith("old:"):
                    sys_by_new_cluster[s["system_id"]] = s

        def system_for(trip: TripInfo, gen: str):
            if gen == "old":
                cid = self.old_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
                return sys_by_old_cluster.get(cid)
            cid = self.new_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
            return sys_by_new_cluster.get(cid)

        # (dg, day, system_id, band) → [old, new]
        cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        days = set()
        for trips, side, gen in ((old_trips, 0, "old"), (new_trips, 1, "new")):
            for t in trips:
                s = system_for(t, gen)
                if s is None:
                    continue
                band = self.bands.band_of(t.first_departure)
                cells[(s["direction_group"], t.day_type, s["system_id"], band)][side] += 1
                days.add(t.day_type)

        band_labels = self.bands.labels()
        rows = []
        for g in dgroups:
            for day in sorted(days, key=day_sort_key):
                sys_rows = []
                agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
                for s in g["systems"]:
                    row_cells = {}
                    for band in band_labels:
                        v = cells.get((g["id"], day, s["system_id"], band))
                        if v:
                            row_cells[band] = v
                            agg[band][0] += v[0]
                            agg[band][1] += v[1]
                    if row_cells:
                        total = [sum(v[0] for v in row_cells.values()),
                                 sum(v[1] for v in row_cells.values())]
                        sys_rows.append({
                            "kind": "system",
                            "direction_group": g["id"],
                            "day_type": day,
                            "system_id": s["system_id"],
                            "label": f"{s['first_stop']}→{s['last_stop']}",
                            "leg": s["leg"],
                            "cells": row_cells,
                            "total": total,
                            "changed": total[0] != total[1]
                            or any(v[0] != v[1] for v in row_cells.values()),
                        })
                if not sys_rows:
                    continue
                agg_total = [sum(v[0] for v in agg.values()),
                             sum(v[1] for v in agg.values())]
                rows.append({
                    "kind": "aggregate",
                    "direction_group": g["id"],
                    "day_type": day,
                    "label": g["label"],
                    "cells": dict(agg),
                    "total": agg_total,
                    "changed": any(v[0] != v[1] for v in agg.values()),
                })
                rows.extend(sys_rows if len(sys_rows) > 1 else
                            [])  # 系統1つなら集計行のみ (内訳は冗長)
        return {"bands": band_labels, "rows": rows}

    # --- ② 変化サマリー (R12 カスケード) ---

    def _summary(self, group, dgroups, systems, band_matrix, n_old, n_new) -> dict:
        # Lev.1
        level1 = None
        if n_old == 0 and n_new > 0:
            level1 = {"kind": "added", "trips": n_new}
        elif n_new == 0 and n_old > 0:
            level1 = {"kind": "removed", "trips": n_old}
        if level1:
            return {"level1": level1, "level2": [], "level3": [],
                    "level4": [], "level5": {"retimed_trips": 0, "notes": []}}

        # Lev.2: 系統の出現・消滅 (min_trips 以上)
        level2 = []
        lev2_system_ids = set()
        for s in systems:
            if s["status"] == "added" and s["trips_new"] >= self.min_trips:
                level2.append({"kind": "system_added", "system_id": s["system_id"],
                               "label": f"{s['first_stop']}→{s['last_stop']}",
                               "trips": s["trips_new"], "family": s["family"]})
                lev2_system_ids.add(s["system_id"])
            elif s["status"] == "removed" and s["trips_old"] >= self.min_trips:
                level2.append({"kind": "system_removed", "system_id": s["system_id"],
                               "label": f"{s['first_stop']}→{s['last_stop']}",
                               "trips": s["trips_old"], "family": s["family"]})
                lev2_system_ids.add(s["system_id"])

        # Lev.3: 経由停変化ユニット (B群イベントを新旧パターン対で束ね、影響率 R13)
        level3 = self._level3_units(group, systems, lev2_system_ids)

        # Lev.4: 増減便 = 集計行のビン別差分の符号別合計 (R14)
        level4 = []
        for row in band_matrix["rows"]:
            if row["kind"] != "aggregate":
                continue
            inc = sum(max(0, v[1] - v[0]) for v in row["cells"].values())
            dec = sum(max(0, v[0] - v[1]) for v in row["cells"].values())
            if inc or dec:
                level4.append({
                    "direction_group": row["direction_group"],
                    "label": row["label"],
                    "day_type": row["day_type"],
                    "net": row["total"][1] - row["total"][0],
                    "increased": inc,
                    "decreased": dec,
                })

        # Lev.5: 時刻の微調整 (同一 trip_id・同一停車列で時刻のみ変化) 等
        retimed = sum(
            1 for o, nw in self.delta.modified
            if self.f2g.get(nw.family) == group and o.base_seq == nw.base_seq
        )
        notes = []
        shape_events = [
            e for e in self.events
            if e.type == "SHAPE_CHANGED" and e.quantification.get("significant")
            and group in {self.f2g.get(f, f) for f in e.subject.get("route_families", [])}
        ]
        if shape_events:
            notes.append({"kind": "shape_changed", "count": len(shape_events)})
        headsign = [
            e for e in self.events
            if e.type == "HEADSIGN_CHANGED"
            and self.f2g.get(e.subject.get("route_family", "")) == group
        ]
        if headsign:
            notes.append({"kind": "headsign_changed",
                          "count": sum(e.quantification.get("changed_fields", 1)
                                       for e in headsign)})
        return {"level1": None, "level2": level2, "level3": level3,
                "level4": level4,
                "level5": {"retimed_trips": retimed, "notes": notes}}

    def _level3_units(self, group, systems, lev2_ids) -> list[dict]:
        """経由停変化ユニット。

        素材は trip_delta.modified (同一 trip_id で停車列が変わった便) を trip 単位で
        直接集計する (B群イベント経由にしない — direction_id の無いフィードでは
        イベントが両方向を1件に束ねるため、系統への帰属が不正確になる)。
        検出の正当性は B群イベント (説明会計) が担保し、ここは表示用の再集計。
        """
        sys_by_key = {}
        for s in systems:
            sys_by_key[(s["family"], s["direction"], tuple(s["stops"]))] = s

        units: dict[tuple, dict] = {}
        for old_t, new_t in self.delta.modified:
            if self.f2g.get(new_t.family) != group or old_t.base_seq == new_t.base_seq:
                continue
            key = (new_t.family, new_t.direction, old_t.base_seq, new_t.base_seq)
            unit = units.setdefault(key, {
                "family": new_t.family,
                "affected": 0,
                "old_pattern": list(old_t.base_seq),
                "new_pattern": list(new_t.base_seq),
            })
            unit["affected"] += 1

        # 第2段階マージ: 人が認識する変化の単位 = (追加停留所集合, 削除停留所集合)。
        # 方向・系統・変形の種類 (延伸/挿入/迂回) の違いは「対象系統の内訳」に降格する
        # (一般ルール。豊前市の実例: 上り下り×複数パターン対が同一の追加/削除集合に束なる)
        merged: dict[tuple, dict] = {}
        for (family, direction, old_p, new_p), unit in sorted(units.items(), key=str):
            system = sys_by_key.get((family, direction, new_p)) \
                or sys_by_key.get((family, direction, old_p))
            affected = unit["affected"]
            total = (system["trips_new"] or system["trips_old"]) if system else affected
            added = set(new_p) - set(old_p)
            removed = set(old_p) - set(new_p)
            key = (tuple(sorted(added)), tuple(sorted(removed)))
            m = merged.setdefault(key, {
                "added_stops": sorted(added),
                "removed_stops": sorted(removed),
                "systems": [],
                "affected_trips": 0,
                "system_trips": 0,
                "_seen_systems": set(),
            })
            m["systems"].append({
                "system_id": system["system_id"] if system else None,
                "label": (f"{system['first_stop']}→{system['last_stop']}"
                          if system else family),
                "family": family,
                "leg": system.get("leg", "") if system else "",
                "affected_trips": affected,
                "system_trips": total,
                "old_pattern": unit["old_pattern"],
                "new_pattern": unit["new_pattern"],
            })
            m["affected_trips"] += affected
            if system and system["system_id"] not in m["_seen_systems"]:
                m["_seen_systems"].add(system["system_id"])
                m["system_trips"] += total
            elif not system:
                m["system_trips"] += total

        result = []
        for key in sorted(merged, key=str):
            m = merged[key]
            seen_systems = m.pop("_seen_systems")
            total = m["system_trips"]
            m["coverage"] = round(m["affected_trips"] / total, 3) if total else None
            m["full_coverage"] = bool(
                total and m["affected_trips"] / total >= self.full_coverage
            )
            m["absorbed_into_level2"] = bool(
                seen_systems and seen_systems <= lev2_ids
            )
            result.append(m)
        return result

    # --- ④ 新旧時刻表 (R17) ---

    def _timetables(self, dgroups, old_trips, new_trips) -> list[dict]:
        sys_by_old = {}
        sys_by_new = {}
        for g in dgroups:
            for s in g["systems"]:
                if s["old_system_id"]:
                    sys_by_old[s["old_system_id"]] = s
                if not s["system_id"].startswith("old:"):
                    sys_by_new[s["system_id"]] = s

        def locate(trip: TripInfo, gen: str):
            if gen == "old":
                cid = self.old_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
                return sys_by_old.get(cid)
            cid = self.new_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
            return sys_by_new.get(cid)

        # trip 対応 (差分表示の素材)
        pair_of_old: dict[str, tuple[str, TripInfo, TripInfo]] = {}
        pair_of_new: dict[str, tuple[str, TripInfo, TripInfo]] = {}
        for o, nw in self.delta.exact_pairs:
            status = "unchanged" if o.trip_id == nw.trip_id else "id_changed"
            pair_of_old[o.trip_id] = (status, o, nw)
            pair_of_new[nw.trip_id] = (status, o, nw)
        for o, nw in self.delta.modified:
            status = "retimed" if o.base_seq == nw.base_seq else "rerouted"
            pair_of_old[o.trip_id] = (status, o, nw)
            pair_of_new[nw.trip_id] = (status, o, nw)

        # (dg, leg, day) → trips
        buckets: dict[tuple, dict] = defaultdict(lambda: {"old": [], "new": []})
        for t in old_trips:
            s = locate(t, "old")
            if s:
                buckets[(s["direction_group"], s["leg"], t.day_type)]["old"].append(t)
        for t in new_trips:
            s = locate(t, "new")
            if s:
                buckets[(s["direction_group"], s["leg"], t.day_type)]["new"].append(t)

        dg_label = {}
        for g in dgroups:
            for leg, label in g["leg_labels"].items():
                dg_label[(g["id"], leg)] = label

        tables = []
        for (dg, leg, day) in sorted(buckets, key=lambda k: (k[0], k[1], day_sort_key(k[2]))):
            bucket = buckets[(dg, leg, day)]
            # 軸は経路変更 trip の旧停車列も含めた超列にする (差分表示で旧時刻も並べるため)
            seqs = [t.base_seq for t in bucket["old"] + bucket["new"]]
            for nw in bucket["new"]:
                pair = pair_of_new.get(nw.trip_id)
                if pair:
                    seqs.append(pair[1].base_seq)
            axis = build_stop_axis(seqs)
            columns = []
            done_old = set()
            for nw in bucket["new"]:
                pair = pair_of_new.get(nw.trip_id)
                if pair:
                    status, o, _ = pair
                    done_old.add(o.trip_id)
                    columns.append(self._column(status, o, nw, axis))
                else:
                    columns.append(self._column("added", None, nw, axis))
            for o in bucket["old"]:
                if o.trip_id in done_old or o.trip_id in pair_of_old:
                    # 対応先が別バケット (経路変更で系統移動) の場合も旧側は出さない
                    continue
                columns.append(self._column("removed", o, None, axis))
            columns.sort(key=lambda c: c["sort_key"])
            for c in columns:
                del c["sort_key"]
            tables.append({
                "direction_group": dg,
                "leg": leg,
                "label": dg_label.get((dg, leg), ""),
                "day_type": day,
                "stop_axis": list(axis),
                # both / old_only (廃止) / new_only (新設) — 行名の表示と ・・ 判定に使う
                "stop_axis_status": [
                    "both" if (stop in self.old_stop_names and stop in self.new_stop_names)
                    else ("old_only" if stop in self.old_stop_names else "new_only")
                    for stop in axis
                ],
                "columns": columns,
            })
        return tables

    @staticmethod
    def _times_on_axis(trip: TripInfo, axis) -> list[str | None]:
        """軸上の時刻列。None = その便の経路外、"" = 経路上だが時刻なし (通過)。"""
        row: list[str | None] = [None] * len(axis)
        for pos, (arr, dep) in zip(align_to_axis(trip.base_seq, axis), trip.times):
            if pos >= 0:
                row[pos] = dep or arr or ""
        return row

    @staticmethod
    def _minute(value: str | None) -> int | None:
        """表示粒度 (分) での時刻。None/空/不正は None。"""
        from ..events.timebands import parse_gtfs_time

        if not value:
            return None
        sec = parse_gtfs_time(value)
        return sec // 60 if sec is not None else None

    def _column(self, status, old: TripInfo | None, new: TripInfo | None, axis) -> dict:
        times_old = self._times_on_axis(old, axis) if old else None
        times_new = self._times_on_axis(new, axis) if new else None
        changed = []
        if times_old and times_new:
            # 表示粒度 (分) で比較する。秒だけの差は表示が変わらないため変更扱いしない
            changed = [
                i for i, (a, b) in enumerate(zip(times_old, times_new))
                if self._minute(a) != self._minute(b)
            ]
        ref = new or old
        return {
            "status": status,  # unchanged / id_changed / retimed / rerouted / added / removed
            "trip_id_old": old.trip_id if old else None,
            "trip_id_new": new.trip_id if new else None,
            "times_old": times_old,
            "times_new": times_new,
            "changed_positions": changed,
            "sort_key": ref.first_departure or "99:99:99",
        }

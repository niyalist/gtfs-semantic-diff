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
    """1つの運行日世界。dates は実効日 (昇順)。

    mixed (SD5c 案C): 構成 service の実効日集合が「同一でも入れ子でもない」
    部分重なり融合 (立川の年末/正月が迷い共有日 2/28 で融合した型)。
    この世界の便数合算は「1日あたり」でなく「のべ」— 表示は断定をやめて
    のべ表記に切り替える。shared_dates は融合の橋になった共有日 (検品情報)。
    入れ子 (平日+学期通学の共走) は従来どおり合算し mixed にしない。"""

    day_type: str
    world_id: str  # "weekday#1" 等 (ラベル内初日順の連番、決定的)
    services: tuple[str, ...]
    dates: tuple[str, ...]
    mixed: bool = False
    shared_dates: tuple[str, ...] = ()


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
            # SD5c 案C: 部分重なり融合の検出 (入れ子=共走 attach は除外)
            date_sets = sorted(
                {frozenset(dates.get(s, ())) for s in g
                 if dates.get(s)}, key=len)
            mixed = (len(date_sets) > 1 and not all(
                a <= b for a, b in zip(date_sets, date_sets[1:])))
            shared: tuple[str, ...] = ()
            if mixed:
                from collections import Counter as _C
                cnt = _C(d for s in g for d in set(dates.get(s, ())))
                shared = tuple(sorted(d for d, n in cnt.items() if n > 1))[:10]
            worlds.append(DayWorld(
                day_type=label, world_id=wid,
                services=tuple(sorted(g)), dates=wdates,
                mixed=mixed, shared_dates=shared,
            ))
            for s in g:
                by_service[s] = wid
    return DayWorlds(
        worlds=tuple(worlds), by_service=by_service,
        multi_labels=frozenset(multi),
    )


# --- パターン束ねと世代間対応 (SD5、(路線×方向) 粒度) ---


@dataclass(frozen=True)
class WorldPattern:
    """(family, direction, day_type) 内で内容が完全一致する世界の束。

    trips_per_day = 1世界あたりの便数 (束内の全世界が同内容なので共通)。
    """

    day_type: str
    digest: str
    world_ids: tuple[str, ...]
    dates: tuple[str, ...]  # 束内全世界の実効日 (昇順)
    trips_per_day: int


def group_patterns(trips, worlds: DayWorlds) -> dict:
    """(family, direction, day_type) → [WorldPattern] (dates[0] 順)。

    trips は TripInfo の iterable。世界毎に内容 (base_seq, times) の多重集合を
    ダイジェスト化し、完全一致する世界を1パターンに束ねる。
    断定は完全一致のみ (service_days.md §9 の方針3原則)。
    """
    import hashlib
    from collections import Counter

    per_world: dict = {}
    for t in trips:
        wid = worlds.world_of(t.service_id)
        key = (t.family, t.direction, t.day_type)
        per_world.setdefault(key, {}).setdefault(wid, Counter())[
            (t.base_seq, t.times)] += 1

    by_id = worlds.by_id()
    out: dict = {}
    for key, wmap in per_world.items():
        classes: dict = {}
        for wid in sorted(wmap):
            digest = hashlib.sha1(
                repr(sorted(wmap[wid].items())).encode()).hexdigest()[:12]
            classes.setdefault(digest, []).append(wid)
        pats = []
        for digest, wids in classes.items():
            dates = tuple(sorted({
                d for w in wids for d in (by_id[w].dates if w in by_id else ())
            }))
            pats.append(WorldPattern(
                day_type=key[2], digest=digest, world_ids=tuple(wids),
                dates=dates,
                trips_per_day=sum(wmap[wids[0]].values()),
            ))
        pats.sort(key=lambda p: (p.dates[0] if p.dates else "99999999",
                                 p.digest))
        out[key] = pats
    return out


def match_patterns(old_pats: list, new_pats: list) -> list:
    """世代間のパターン対応 (完全一致の2信号のみ、**厳密 1:1**)。

    戻り値: (old_index | None, new_index | None, signal) のリスト。
    signal = "content" (内容ダイジェスト一致 — 日付が変わっても同じ時刻表) /
    "dates" (実効日集合一致 — 同じ日々で内容が変化) / None (対応なし)。
    content を優先し、残りに dates を適用。

    1:1 の根拠 (2026-07-25 決定 — M9 route identity との相似で「世代内は
    データに忠実・世代間のみ内容対応」だが、世界パターンには路線名のような
    実体性がないため N:M は張らない): content は group_patterns が同一世代内の
    同 digest 世界を1パターンに束ねるので構造上 1:1。dates も先勝ち 1:1。
    PRT の「旧1日 → 新2日」は新側が1パターンに束なった上での 1:1 対応。
    """
    used_new: set[int] = set()
    result = []
    # 信号1: 内容一致 (digest は各世代で一意 — group_patterns の束ねによる)
    by_digest: dict = {}
    for j, p in enumerate(new_pats):
        by_digest.setdefault(p.digest, j)
    matched_old: set[int] = set()
    for i, p in enumerate(old_pats):
        j = by_digest.get(p.digest)
        if j is not None and j not in used_new:
            used_new.add(j)
            result.append((i, j, "content"))
            matched_old.add(i)
    # 信号2: 日付集合一致
    for i, p in enumerate(old_pats):
        if i in matched_old:
            continue
        for j, q in enumerate(new_pats):
            if j in used_new:
                continue
            if p.dates and p.dates == q.dates:
                used_new.add(j)
                result.append((i, j, "dates"))
                matched_old.add(i)
                break
    for i in range(len(old_pats)):
        if i not in matched_old:
            result.append((i, None, None))
    for j in range(len(new_pats)):
        if j not in used_new:
            result.append((None, j, None))
    result.sort(key=lambda r: (r[0] if r[0] is not None else 10**9,
                               r[1] if r[1] is not None else 10**9))
    return result


@dataclass(frozen=True)
class WorldContext:
    """パイプラインからルール・レポートへ渡す SD5 成果物一式。"""

    old: DayWorlds
    new: DayWorlds
    old_patterns: dict  # (family, direction, day_type) → [WorldPattern]
    new_patterns: dict
    matches: dict  # 同キー → match_patterns の結果


def build_world_context(old_snap, new_snap, old_trips, new_trips) -> WorldContext:
    """世界分解 → パターン束ね → 世代間対応 (2信号) を一括計算する。"""
    old_w = build_day_worlds(old_snap)
    new_w = build_day_worlds(new_snap)
    old_p = group_patterns(old_trips.values(), old_w)
    new_p = group_patterns(new_trips.values(), new_w)
    matches = {}
    for key in sorted(set(old_p) | set(new_p), key=str):
        matches[key] = match_patterns(old_p.get(key, []), new_p.get(key, []))
    return WorldContext(old=old_w, new=new_w, old_patterns=old_p,
                        new_patterns=new_p, matches=matches)


# --- SD6: 切替の整列 (service_days.md §9.2) ---


@dataclass(frozen=True)
class GenerationSwitch:
    """単調な世代交代の検出結果。

    old/new_excluded_services = 持ち越し・先行掲載の世界の service。
    switch_date = 新ダイヤの開始日 (YYYYMMDD)。
    old/new_keep_interval = 比較に残す側の期間 (表示用)。
    """

    old_excluded_services: frozenset
    new_excluded_services: frozenset
    switch_date: str
    old_keep_interval: tuple  # (from, to) YYYYMMDD
    new_keep_interval: tuple


def _label_world_digests(trips, worlds: DayWorlds) -> dict:
    """world_id → フィードレベル内容ダイジェスト (便を持つ世界のみ)。"""
    import hashlib
    from collections import Counter

    per_world: dict = defaultdict(Counter)
    for t in trips.values():
        w = worlds.world_of(t.service_id)
        if w:
            per_world[w][(t.family, t.direction, t.base_seq, t.times)] += 1
    return {w: hashlib.sha1(repr(sorted(c.items())).encode()).hexdigest()[:16]
            for w, c in per_world.items()}


def resolve_generation_switch(old_snap, new_snap, old_trips, new_trips):
    """単調な世代交代 (同居の持ち越し) を検出する。該当なしは None。

    発動条件 (レギュラー型ラベルのうち複数世界を持つ全ラベルで成立):
    - 旧が複数世界: 末尾世界の内容が新に存在し (持ち越し)、
      先頭世界の内容は新に存在しない (再出現なし = 季節でない)
    - 新が複数世界: 先頭世界の内容が旧に存在し (旧世代の先行同梱)、
      末尾世界の内容は旧に存在しない
    発動時は「旧の先頭世界 vs 新の末尾世界」で比較する (§9.2)。
    特定日 (irregular)・inactive は従来どおり比較対象に残す。
    再出現 (季節・振動) は不発 — 世界セル表示 (SD5) が説明する。
    """
    old_w = build_day_worlds(old_snap)
    new_w = build_day_worlds(new_snap)

    def regular(label: str) -> bool:
        return label not in ("irregular", "inactive")

    dig_o = _label_world_digests(old_trips, old_w)
    dig_n = _label_world_digests(new_trips, new_w)

    def label_worlds(w: DayWorlds, digs):
        out: dict = defaultdict(list)
        for world in w.worlds:
            if regular(world.day_type) and world.world_id in digs and world.dates:
                out[world.day_type].append(world)
        for ws in out.values():
            ws.sort(key=lambda x: x.dates[0])
        return out

    lw_o = label_worlds(old_w, dig_o)
    lw_n = label_worlds(new_w, dig_n)
    targets = [lbl for lbl in sorted(set(lw_o) | set(lw_n))
               if len(lw_o.get(lbl, ())) > 1 or len(lw_n.get(lbl, ())) > 1]
    if not targets:
        return None

    excl_o: set = set()
    excl_n: set = set()
    keep_o_dates: list = []
    keep_n_dates: list = []
    switch_dates: list = []
    for lbl in targets:
        ow = lw_o.get(lbl, [])
        nw = lw_n.get(lbl, [])
        if not ow or not nw:
            return None  # 片側にラベルがない — 交代とは言えない
        digs_o_here = {dig_o[w.world_id] for w in ow}
        digs_n_here = {dig_n[w.world_id] for w in nw}
        if len(ow) > 1:
            if dig_o[ow[-1].world_id] not in digs_n_here:
                return None  # 末尾が持ち越しでない
            if dig_o[ow[0].world_id] in digs_n_here:
                return None  # 先頭が再出現 = 季節・振動
            for w in ow[1:]:
                excl_o.update(w.services)
            switch_dates.append(ow[1].dates[0])
        if len(nw) > 1:
            if dig_n[nw[0].world_id] not in digs_o_here:
                return None
            if dig_n[nw[-1].world_id] in digs_o_here:
                return None
            for w in nw[:-1]:
                excl_n.update(w.services)
            switch_dates.append(nw[-1].dates[0])
        keep_o_dates.extend(ow[0].dates)
        keep_n_dates.extend(nw[-1].dates)
    if not (excl_o or excl_n):
        return None
    return GenerationSwitch(
        old_excluded_services=frozenset(excl_o),
        new_excluded_services=frozenset(excl_n),
        switch_date=min(switch_dates),
        old_keep_interval=(min(keep_o_dates), max(keep_o_dates)),
        new_keep_interval=(min(keep_n_dates), max(keep_n_dates)),
    )

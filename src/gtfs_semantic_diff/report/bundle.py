"""HTML ビューア用の結果バンドル生成 (docs/design/web.md)。

ChangeEventSet JSON に加え、ビューアのドリルダウンに必要な素材を JSON 化する:
- geometry: 停留所クラスタの座標 (新旧・異動ステータス付き) と、イベントに
  現れる shape の新旧ポリライン (GeoJSON FeatureCollection)
- timetables: イベントが立った (family, direction, day_type) グループの
  新旧発車時刻一覧 (時刻表 before/after 描画用)
- catalog: イベントタイプの ja/en 表示名 (ビューアの i18n)
- meta: ツール情報

core には依存する (identity / trip_delta の成果物を素材にする) が、
core は bundle を知らない (設計原則 3 の consumer)。
"""

from __future__ import annotations

import datetime
import html as html_lib
import importlib.metadata
import json
from typing import Any

from ..config import Config
from ..identity import IdentityResult
from ..model import EVENT_TYPES, ChangeEventSet, GtfsSnapshot, RawDiffSet
from ..model.matchgraph import ENTITY_STOP_CLUSTER


def build_bundle(
    old: GtfsSnapshot,
    new: GtfsSnapshot,
    config: Config,
    event_set: ChangeEventSet,
    rawdiffs: RawDiffSet,
    identity: IdentityResult,
    trip_delta,
) -> dict[str, Any]:
    """ビューアに埋め込む全データ (JSON 化可能な dict)。"""
    from .presentation import build_presentation

    presentation = build_presentation(event_set, identity, trip_delta, config)
    # 第1部 (フィード全体) と第4部 (その他) はスナップショット・RawDiff を
    # 素材にするためここで付与する (presentation.py は events/identity/delta のみ)
    presentation["feed_overview"] = _feed_overview(
        old, new, event_set, rawdiffs, trip_delta, config
    )
    # SD3 改: 路線ページの「特定日」タブにその場で具体日付を出す
    from ..identity.route_family import route_to_family_map

    special_old = _route_special_dates(
        old, route_to_family_map(identity.old_families), identity.old_family_to_group
    )
    special_new = _route_special_dates(
        new, route_to_family_map(identity.new_families), identity.new_family_to_group
    )
    if special_old or special_new:
        list_max = config.get("report", "special_dates_list_max", default=30)
        for p in presentation["route_pages"]:
            o = special_old.get(p["route_group"], [])
            n = special_new.get(p["route_group"], [])
            if o or n:
                p["special_dates"] = {
                    "old": o[:list_max], "new": n[:list_max],
                    "old_total": len(o), "new_total": len(n),
                }
    # V5: 全イベントの表示先 (レポートのどの部に現れるか) とレポート被覆率
    presentation["coverage"] = _coverage(event_set)
    # M9 (I3): lev1 便数比率 = 新設/廃止扱いのページに落ちた便の割合。
    # family 対応の取りこぼし (改称・再編の見逃し) の煙感知器 —
    # 対応付けが働いていれば継続ページ側に便が乗り、この値は下がる
    lev1 = total = 0
    for p in presentation["route_pages"]:
        n = sum(d["old"] + d["new"] for d in p["day_totals"])
        total += n
        if p["summary"]["level1"]:
            lev1 += n
    presentation["coverage"]["lev1_trip_ratio"] = (
        round(lev1 / total, 4) if total else 0.0
    )

    return {
        "events": event_set.to_dict(),
        "rawdiffs": [d.to_dict() for d in rawdiffs.diffs],
        "presentation": presentation,
        "geometry": _geometry(event_set, identity, old, new, config),
        "timetables": _timetables(event_set, trip_delta),
        "catalog": {
            t.type_id: {"ja": t.display_name_ja, "en": t.display_name_en,
                        "category": t.category}
            for t in EVENT_TYPES.values()
        },
        "meta": {
            "tool": "gtfs-semantic-diff",
            "version": _version(),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "feed": event_set.feed,
            # レポート表題用の事業者名 (GTFS agency.txt 由来。新世代優先)
            "agency_names": _agency_names(new) or _agency_names(old),
        },
    }


# --- 第1部 (フィード全体の変化) と第4部 (その他の変化) の素材 ---

# 第1部で読み下すフィード級イベント (E群 + F群のメタ系)
_PART1_EVENT_TYPES = frozenset({
    "DAYTYPE_RESTRUCTURED", "HOLIDAY_EXCEPTION_CHANGED", "SEASONAL_SERVICE_CHANGED",
    "FEED_VALIDITY_CHANGED", "AGENCY_INFO_CHANGED", "TRANSLATION_CHANGED",
    "FARE_CHANGED", "DEMAND_RESPONSIVE_CHANGE", "GENERATION_SCOPE",
})


def _event_destination(e) -> dict:
    """イベントの表示先 (レポートのどの部が受け持つか) の決定的対応。

    型と subject による粗粒度の対応付け (V5 第1段)。表示単位 (Lev.2 の何行目か等)
    への精密な refs は将来の精緻化とし、まず「全イベントに表示先がある」ことを
    保証する。第4部 = ここで 1〜3部に割り当てられなかった全て (件数のみの提示)。
    """
    t = EVENT_TYPES[e.type]
    if e.type in _PART1_EVENT_TYPES:
        return {"part": 1, "route_group": None}
    if t.category == "D":
        return {"part": 2, "route_group": None}
    if (t.category in ("A", "B", "C") and e.type != "SHAPE_CHANGED") \
            or e.type == "HEADSIGN_CHANGED":
        g = e.subject.get("route_group") or e.subject.get("route_family")
        if g:
            return {"part": 3, "route_group": g}
    return {"part": 4, "route_group": None}


def _coverage(event_set) -> dict:
    """V5: 表示先の台帳とレポート被覆率。

    - destinations: event_id → {part, route_group}
    - report_coverage_ratio: 第1〜3部で個別に説明されるイベントの割合
      (第4部行き = 件数のみの提示、を「個別説明なし」とみなす)
    """
    destinations = {}
    by_part = {1: 0, 2: 0, 3: 0, 4: 0}
    for e in event_set.events:
        d = _event_destination(e)
        destinations[e.event_id] = d
        by_part[d["part"]] += 1
    total = len(event_set.events)
    covered = total - by_part[4]
    return {
        "destinations": destinations,
        "events_total": total,
        "events_by_part": {str(k): v for k, v in by_part.items()},
        "report_coverage_ratio": (covered / total) if total else 1.0,
    }


def _feed_overview(old, new, event_set, rawdiffs, trip_delta, config: Config) -> dict:
    """4部構成レポートの第1部・第4部ビュー。

    - files: txt ファイルごとの新旧対応表 (有無・行数・RawDiff 内訳)
    - day_types: 曜日区分ごとの便数 旧→新
    - meta_events: フィード級イベント (期間・事業者・カレンダー・運賃等)
    - others (第4部): 第1〜3部のどこにも現れないイベントの種類別件数。
      レポート面の取りこぼしを常に可視化する (V5 で presentation_refs による
      機械的な網羅判定に昇格予定)
    """
    from .presentation import day_sort_key

    # ファイル対応表。集約 RawDiff (rows_*_bulk) は保持している行数で計上する
    # (台帳上は1件だが、ファイル表は「何行変わったか」を示すのが役割)
    old_names = {f"{n}.txt" for n in old.tables}
    new_names = {f"{n}.txt" for n in new.tables}
    per_file: dict[str, dict[str, int]] = {}
    for d in rawdiffs.diffs:
        b = per_file.setdefault(d.file, {})
        if d.kind == "rows_removed_bulk":
            b["row_removed"] = b.get("row_removed", 0) + int(d.old_value or 0)
        elif d.kind == "rows_added_bulk":
            b["row_added"] = b.get("row_added", 0) + int(d.new_value or 0)
        elif d.kind == "rows_changed_bulk":
            b["rows_changed"] = b.get("rows_changed", 0) + int(d.old_value or 0)
        else:
            b[d.kind] = b.get(d.kind, 0) + 1
    files = []
    for name in sorted(old_names | new_names | set(per_file)):
        stem = name.removesuffix(".txt")
        t_old = old.tables.get(stem)
        t_new = new.tables.get(stem)
        counts = per_file.get(name, {})
        files.append({
            "name": name,
            "status": ("continued" if name in old_names and name in new_names
                       else "added" if name in new_names else "removed"),
            "rows_old": len(t_old) if t_old is not None else None,
            "rows_new": len(t_new) if t_new is not None else None,
            "row_added": counts.get("row_added", 0),
            "row_removed": counts.get("row_removed", 0),
            "field_changed": counts.get("field_changed", 0)
            + counts.get("rows_changed", 0),
            "column_changes": counts.get("column_added", 0)
            + counts.get("column_removed", 0),
        })

    # 曜日区分ごとの便数 旧→新
    day_counts: dict[str, list[int]] = {}
    for trips, side in ((trip_delta.old_trips, 0), (trip_delta.new_trips, 1)):
        for t in trips.values():
            day_counts.setdefault(t.day_type, [0, 0])[side] += 1
    day_types = [
        {"day_type": d, "old": c[0], "new": c[1]}
        for d, c in sorted(day_counts.items(), key=lambda kv: day_sort_key(kv[0]))
    ]
    # M10: 特定日 (irregular) / 運行日なし (inactive) service の内訳。
    # 「その全日付を他 service が exception_type=2 で運休しているか」で
    # 置き換え型 (年末年始ダイヤ等) と追加型 (臨時便) を見分ける
    special_days = {
        "old": _special_day_services(old, config),
        "new": _special_day_services(new, config),
    }

    # フィード級イベント (第1部) — 表示はビューアが catalog の表示名で行う
    meta_events = [
        {
            "type": e.type,
            "subject": e.subject,
            "quantification": e.quantification,
            "old_ref": e.old_ref,
            "new_ref": e.new_ref,
            "evidence_count": len(e.evidence),
        }
        for e in event_set.events
        if e.type in _PART1_EVENT_TYPES
    ]

    # 第4部: 第1〜3部のどこにも現れないイベントの種類別件数。
    # 表示先の判定は _event_destination に一元化 (V5 の coverage と必ず一致する)。
    # 将来のイベント追加も自動的にここへ落ちる
    others: dict[str, int] = {}
    for e in event_set.events:
        if _event_destination(e)["part"] == 4:
            others[e.type] = others.get(e.type, 0) + 1

    return {
        "files": files,
        "day_types": day_types,
        "special_days": special_days,
        "meta_events": meta_events,
        # SD2: 同梱世代の比較範囲 (単一世代比較では None)。第1部に注記を出す
        "comparison_scope": event_set.context.get("comparison_scope"),
        # SD4: 運行日カレンダービュー (新旧並置)。長期窓は None
        "calendar_view": {
            "old": _calendar_view(old, config),
            "new": _calendar_view(new, config),
        },
        "others": [
            {"type": t, "count": n} for t, n in sorted(others.items())
        ],
    }


def _irregular_service_dates(snapshot) -> dict[str, list[str]]:
    """特定日 (irregular) service → 実効運行日リスト (YYYYMMDD 昇順)。

    SD3 の第1部内訳と路線ページの「特定日の運行日」表示が共用する。
    定義は SD1 と同一 (期間×フラグ − 削除 + 追加、フィード有効期間でクリップ)。
    """
    from ..events.windows import snapshot_window
    from ..load.day_types import (
        _CALENDAR_DAY_COLUMNS,
        _exception_dates,
        effective_date_list,
    )

    targets = {
        sid for sid, dt in snapshot.day_types.items() if dt == "irregular"
    }
    if not targets:
        return {}
    added_map, removed_map = _exception_dates(snapshot.table("calendar_dates"))
    window = snapshot_window(snapshot)
    window_text = window.as_text() if window is not None else None
    result: dict[str, list[str]] = {}
    flag_done: set[str] = set()
    cal = snapshot.table("calendar")
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            sid = str(row.get("service_id", ""))
            if sid not in targets:
                continue
            flags = tuple(
                str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS
            )
            if not any(flags):
                continue
            computed = effective_date_list(
                flags, str(row["start_date"]), str(row["end_date"]),
                added_map.get(sid, set()), removed_map.get(sid, set()),
                window_text,
            )
            if computed is not None:
                result[sid] = computed[0]
                flag_done.add(sid)
    for sid in targets - flag_done:
        removed = removed_map.get(sid, set())
        result[sid] = sorted(
            d for d in set(added_map.get(sid, [])) if d not in removed
        )
    return result


def _route_special_dates(
    snapshot, route_to_family: dict[str, str], family_to_group: dict[str, str]
) -> dict[str, list[str]]:
    """route_group → 特定日 (irregular) 便の実効運行日 (合併・昇順)。

    路線ページの「特定日」タブにその場で具体日付を出すための素材 (SD3 改)。"""
    by_service = _irregular_service_dates(snapshot)
    if not by_service:
        return {}
    trips = snapshot.table("trips")
    if trips is None or trips.empty:
        return {}
    result: dict[str, set[str]] = {}
    for rid, sid in zip(trips["route_id"], trips["service_id"]):
        dates = by_service.get(str(sid))
        if not dates:
            continue
        family = route_to_family.get(str(rid), "")
        group = family_to_group.get(family, family) or str(rid)
        result.setdefault(group, set()).update(dates)
    return {g: sorted(ds) for g, ds in result.items()}


def _special_day_services(snapshot, config: Config) -> list[dict]:
    """特定日 (irregular) / 運行日なし (inactive) service の内訳 (M10 → SD3)。

    SD3: 表示の基礎を「calendar_dates の追加日」から**実効運行日集合**
    (期間×フラグ − 削除 + 追加、フィード有効期間でクリップ) に置き換える —
    SD1 で「フラグ+大量削除」型の特定日 (PRT の祝日専用 service) が
    増えたため。具体日付リスト date_list を `[report]
    special_dates_list_max` 件まで持ち、viewer が「運行日: 7/4」等と表示する。
    replaces_regular: この service の全運行日を、他の service が
    exception_type=2 で運休している (= 通常ダイヤの置き換え。年末年始等)。
    """
    from ..load.day_types import _CALENDAR_DAY_COLUMNS, effective_date_list

    specials = [
        (sid, dt) for sid, dt in sorted(snapshot.day_types.items())
        if dt in ("irregular", "inactive")
    ]
    if not specials:
        return []
    list_max = config.get("report", "special_dates_list_max", default=30)
    trips = snapshot.table("trips")
    trip_counts: dict[str, int] = {}
    if trips is not None:
        for sid in trips["service_id"]:
            trip_counts[sid] = trip_counts.get(sid, 0) + 1

    added_dates: dict[str, list[str]] = {}
    removed_dates: dict[str, set[str]] = {}
    cd = snapshot.table("calendar_dates")
    if cd is not None and not cd.empty and {"service_id", "date",
                                            "exception_type"} <= set(cd.columns):
        for sid, date, et in zip(cd["service_id"], cd["date"], cd["exception_type"]):
            sid, date, et = str(sid), str(date).strip(), str(et).strip()
            if et == "1":
                added_dates.setdefault(sid, []).append(date)
            elif et == "2":
                removed_dates.setdefault(sid, set()).add(date)

    # フラグ+期間を持つ service の実効日 (SD1 と同じ定義。窓は feed_info 等)
    from ..events.windows import snapshot_window

    window = snapshot_window(snapshot)
    window_text = window.as_text() if window is not None else None
    flag_rows: dict[str, tuple[tuple[bool, ...], str, str]] = {}
    cal = snapshot.table("calendar")
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            flags = tuple(
                str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS
            )
            if any(flags):
                flag_rows[str(row.get("service_id", ""))] = (
                    flags, str(row["start_date"]), str(row["end_date"])
                )

    result = []
    for sid, dt in specials:
        if not trip_counts.get(sid):
            continue  # 便が無い定義だけの service は出さない
        if sid in flag_rows:
            flags, start, end = flag_rows[sid]
            computed = effective_date_list(
                flags, start, end,
                set(added_dates.get(sid, [])), removed_dates.get(sid, set()),
                window_text,
            )
            dates = computed[0] if computed is not None else sorted(
                added_dates.get(sid, [])
            )
        else:
            removed = removed_dates.get(sid, set())
            dates = sorted(
                d for d in set(added_dates.get(sid, [])) if d not in removed
            )
        removed_by_others = set().union(
            *(v for k, v in removed_dates.items() if k != sid)
        ) if removed_dates else set()
        result.append({
            "service_id": sid,
            "day_type": dt,
            "trips": trip_counts[sid],
            "dates": len(dates),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "date_list": dates[:list_max],
            "truncated": len(dates) > list_max,
            "replaces_regular": bool(dates) and all(
                d in removed_by_others for d in dates
            ),
        })
    return result


def _calendar_view(snapshot, config: Config) -> dict | None:
    """SD4: 運行日カレンダービューの素材 (1スナップショット分)。

    日付ごとに「その日実際に走る世界」を実効運行日集合から引く:
    - sym: 走っている週次レギュラー型のラベル (曜日集合がその日を含むもの優先)。
      走るものがなければ none
    - swap: 週次型は走っているが、その日の曜日を含まない (= 振替。桑名の
      祝日「平日 service 削除+日曜 service 追加」がここに出る)
    - special: 特定日 (irregular) service がその日運行
    - period: 期間 (calendar 端点で区切った区間) の通し番号 — 世代・季節の
      切れ目を背景とし、記号を第1チャネルに保つ (色弱原則)
    計算はすべて SD1/SD2 と同じ実効日定義 (決定的)。
    """
    from ..events.windows import single_snapshot_intervals
    from ..load.day_types import (
        _CALENDAR_DAY_COLUMNS,
        _exception_dates,
        day_set_of,
        effective_date_list,
    )

    window, intervals = single_snapshot_intervals(snapshot)
    if window is None:
        return None
    max_days = config.get("report", "calendar_view_max_days", default=550)
    if window.days() > max_days:
        return None  # 国家規模の長期窓等は対象外 (表示が成立しない)

    trips = snapshot.table("trips")
    services_with_trips: set[str] = set()
    if trips is not None and not trips.empty:
        services_with_trips = {str(s) for s in trips["service_id"]}

    added_map, removed_map = _exception_dates(snapshot.table("calendar_dates"))
    window_text = window.as_text()

    # service ごとの実効日 → 日付ごとの「アクティブな day_type 集合」
    by_date: dict[str, set[str]] = {}

    def add_dates(sid: str, dates: list[str]) -> None:
        dt = snapshot.day_types.get(sid, "irregular")
        for d in dates:
            by_date.setdefault(d, set()).add(dt)

    cal = snapshot.table("calendar")
    flag_services: set[str] = set()
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) | {"start_date", "end_date"} <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            sid = str(row.get("service_id", ""))
            if sid not in services_with_trips:
                continue
            flags = tuple(
                str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS
            )
            if not any(flags):
                continue
            flag_services.add(sid)
            computed = effective_date_list(
                flags, str(row["start_date"]), str(row["end_date"]),
                added_map.get(sid, set()), removed_map.get(sid, set()),
                window_text,
            )
            if computed is not None:
                add_dates(sid, computed[0])
    for sid, dates in added_map.items():
        if sid in flag_services or sid not in services_with_trips:
            continue
        removed = removed_map.get(sid, set())
        lo, hi = window_text
        add_dates(sid, sorted(
            d for d in dates if d not in removed and lo <= d <= hi
        ))

    # 日付セルの決定
    days = []
    d = window.start
    one = datetime.timedelta(days=1)
    period_starts = {iv.start: i for i, iv in enumerate(intervals)}
    period = 0
    while d <= window.end:
        text = d.strftime("%Y%m%d")
        period = period_starts.get(d, period)
        active = by_date.get(text, set())
        regular = [t for t in active if t not in ("irregular", "inactive")]
        matching = [
            t for t in regular
            if (day_set_of(t) or set()) and d.weekday() in day_set_of(t)
        ]
        if matching:
            # 広い区分 (曜日集合が大きいもの) を代表にする (平日 > dow_*)
            sym = max(matching, key=lambda t: len(day_set_of(t) or ()))
            swap = False
        elif regular:
            sym = max(regular, key=lambda t: len(day_set_of(t) or ()))
            swap = True  # 曜日と異なるダイヤで運行 (振替)
        else:
            sym = None
            swap = False
        days.append({
            "date": text,
            "sym": sym,
            "swap": swap,
            "special": "irregular" in active,
            "period": period,
        })
        d += one

    return {
        "window": list(window_text),
        "periods": [list(iv.as_text()) for iv in intervals],
        "days": days,
    }


def _agency_names(snapshot) -> list[str]:
    agency = snapshot.table("agency")
    if agency is None or "agency_name" not in getattr(agency, "columns", ()):
        return []
    seen: list[str] = []
    for name in agency["agency_name"]:
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def _version() -> str:
    try:
        return importlib.metadata.version("gtfs-semantic-diff")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# --- 幾何 ---


def _geometry(
    event_set: ChangeEventSet,
    identity: IdentityResult,
    old: GtfsSnapshot,
    new: GtfsSnapshot,
    config: Config,
) -> dict:
    """停留所クラスタ点 (異動ステータス付き) + イベント関連 shape 線 (GeoJSON)。"""
    features: list[dict] = []

    accept = config.get("events", "accept_confidence", default=0.5)
    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for e in identity.graph.for_type(ENTITY_STOP_CLUSTER):
        if e.confidence >= accept:
            matched_old.add(e.old_id)
            matched_new.add(e.new_id)

    for cid, c in sorted(identity.new_stop_clusters.items()):
        status = "matched" if cid in matched_new else "added"
        features.append(_point(c, "new", status))
    for cid, c in sorted(identity.old_stop_clusters.items()):
        if cid not in matched_old:
            features.append(_point(c, "old", "removed"))

    # イベントに現れる shape の新旧ポリライン
    wanted: dict[str, set[str]] = {"old": set(), "new": set()}
    for e in event_set.events:
        if e.type not in ("SHAPE_CHANGED", "TECHNICAL_ID_CHURN"):
            continue
        subject_shape = e.subject.get("shape_id", "")
        wanted["old"].add(e.quantification.get("old_shape", subject_shape))
        wanted["new"].add(e.quantification.get("new_shape", subject_shape))

    if wanted["old"] or wanted["new"]:
        from ..events.rules.shapes import _polylines

        max_points = config.get("events", "shape", "max_polyline_points", default=200)
        for snapshot, gen in ((old, "old"), (new, "new")):
            lines = _polylines(snapshot, max_points)
            for shape_id in sorted(wanted[gen]):
                pts = lines.get(shape_id)
                if not pts:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[lon, lat] for lat, lon in pts],
                        },
                        "properties": {
                            "shape_id": shape_id,
                            "generation": gen,
                            "kind": "shape",
                        },
                    }
                )
    return {"type": "FeatureCollection", "features": features}


def _point(cluster, gen: str, status: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [cluster.lon, cluster.lat]},
        "properties": {
            "name": cluster.name,
            "base_name": cluster.base_name,
            "cluster_id": cluster.cluster_id,
            "generation": gen,
            "status": status,  # matched / added / removed
            "platforms": len(cluster.platform_ids),
        },
    }


# --- 時刻表 ---


def _timetables(event_set: ChangeEventSet, trip_delta) -> list[dict]:
    """イベントが立ったグループの新旧発車時刻一覧。"""
    groups: set[tuple[str, str, str]] = set()
    for e in event_set.events:
        family = e.subject.get("route_family")
        if family and "day_type" in e.subject:
            groups.add(
                (family, e.subject.get("direction", ""), e.subject["day_type"])
            )

    def trips_of(trips: dict, key: tuple) -> list[dict]:
        rows = [
            {
                "trip_id": t.trip_id,
                "departure": t.first_departure,
                "from": t.base_seq[0] if t.base_seq else "",
                "to": t.base_seq[-1] if t.base_seq else "",
                "stops": len(t.base_seq),
            }
            for t in trips.values()
            if (t.family, t.direction, t.day_type) == key
        ]
        return sorted(rows, key=lambda r: r["departure"])

    result = []
    for key in sorted(groups):
        family, direction, day_type = key
        result.append(
            {
                "route_family": family,
                "direction": direction,
                "day_type": day_type,
                "old": trips_of(trip_delta.old_trips, key),
                "new": trips_of(trip_delta.new_trips, key),
            }
        )
    return result


def render_html(bundle: dict[str, Any], template_html: str) -> str:
    """ビルド済みビューアテンプレートにバンドル JSON を埋め込む。

    タイトル・説明 (OGP) も静的に注入する — SNS のクローラは JS を実行しない
    ため、共有時のプレビューはここで焼き込んだ値が使われる。"""
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # </script> でパースが壊れないようエスケープ
    payload = payload.replace("</", "<\\/")
    title, desc = _page_meta(bundle)
    return (template_html
            .replace("__GTFS_SEMDIFF_DATA__", payload)
            .replace("__GTFS_SEMDIFF_TITLE__", html_lib.escape(title, quote=True))
            .replace("__GTFS_SEMDIFF_DESC__", html_lib.escape(desc, quote=True)))


def _page_meta(bundle: dict[str, Any]) -> tuple[str, str]:
    """レポートの題名と説明文 (OGP 用)。欠損時は一般名にフォールバック。"""
    meta = bundle.get("meta", {})
    feed = meta.get("feed", {}) or {}
    names = meta.get("agency_names") or []
    subject = "・".join(names) or "/".join(
        v for v in (feed.get("org_id"), feed.get("feed_id")) if v)
    old_from = (feed.get("old_period") or ["", ""])[0]
    new_from = (feed.get("new_period") or ["", ""])[0]
    period = f" ({old_from} → {new_from})" if old_from or new_from else ""
    if subject:
        title = f"{subject} のダイヤ改正 意味的差分レポート{period}"
    else:
        title = f"GTFS 比較レポート{period}"
    desc = ("GTFS 2世代の変化を路線・便数・時刻・停留所の観点で"
            "自動で読み解いたレポートです。diff.gtfs.jp")
    return title, desc

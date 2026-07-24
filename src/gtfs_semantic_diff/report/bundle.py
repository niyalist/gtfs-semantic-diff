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
    core: bool = False,
) -> dict[str, Any]:
    """ビューアに埋め込む全データ (JSON 化可能な dict)。

    core=True で Web 配信用の軽量バンドル (RD1a、report_delivery.md §3):
    rawdiffs の行レベル全量を落とし、evidence は件数+サンプル行、
    検証モードは (file, kind) 別の件数+サンプル行 (説明イベント焼き込み) に。
    """
    from .presentation import build_presentation

    presentation = build_presentation(event_set, identity, trip_delta, config)
    # 第1部 (フィード全体) と第4部 (その他) はスナップショット・RawDiff を
    # 素材にするためここで付与する (presentation.py は events/identity/delta のみ)
    presentation["feed_overview"] = _feed_overview(
        old, new, event_set, rawdiffs, trip_delta, config, identity
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

    bundle = {
        "events": event_set.to_dict(),
        # RawDiffSet のまま持つ (遅延直列化)。数百万件を dict リストに実体化すると
        # それだけで GB 級になり Lambda を落とす (IN-3)。直列化は
        # _payload_chunks が1件ずつ行い、埋め込み後の JSON は従来と同一
        "rawdiffs": rawdiffs,
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
    if core:
        return _core_bundle(bundle, rawdiffs, config)
    return bundle


def _core_bundle(bundle: dict[str, Any], rawdiffs: RawDiffSet, config: Config) -> dict[str, Any]:
    """Web 配信用の軽量バンドル (RD1a)。

    - events: evidence を空にし、evidence_total (件数) と evidence_sample
      (先頭 evidence_sample_max 行の RawDiff dict) を付与
    - file_diffs: (file → kind → {count, sample}) — サンプル行には説明イベント
      (最初に evidence として主張したイベント = 現ビューアの先勝ち規則と同一)
      の event_id を explainer として焼き込む
    - rawdiffs キーは持たない (ビューアはこの欠如で core モードを検出)

    網羅性の信頼は数値 (accounting = explained_ratio・ファイル別残差件数) が
    担い、それは events 側に不変で残る。行レベルの完全監査は全量同梱の
    CLI --html か生データ DL (RD2) で行う。
    """
    ev_max = config.get("report", "evidence_sample_max", default=50)
    fd_max = config.get("report", "file_diff_sample_max", default=100)
    by_id = rawdiffs.by_id()
    events = bundle["events"]["events"]

    explainer: dict[str, str] = {}
    for e in events:
        for rid in e.get("evidence", ()):
            explainer.setdefault(rid, e["event_id"])

    slim_events = []
    for e in events:
        ids = e.get("evidence", [])
        e2 = dict(e)
        e2["evidence"] = []
        e2["evidence_total"] = len(ids)
        e2["evidence_sample"] = [by_id[i].to_dict() for i in ids[:ev_max]]
        slim_events.append(e2)
    events_dict = dict(bundle["events"])
    events_dict["events"] = slim_events

    file_diffs: dict[str, dict[str, dict[str, Any]]] = {}
    for d in rawdiffs.diffs:
        slot = file_diffs.setdefault(d.file, {}).setdefault(
            d.kind, {"count": 0, "sample": []}
        )
        slot["count"] += 1
        if len(slot["sample"]) < fd_max:
            row = d.to_dict()
            row["explainer"] = explainer.get(d.rawdiff_id)
            slot["sample"].append(row)

    out = {k: v for k, v in bundle.items() if k != "rawdiffs"}
    out["events"] = events_dict
    out["file_diffs"] = file_diffs
    return out


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


def _feed_overview(
    old, new, event_set, rawdiffs, trip_delta, config: Config, identity=None
) -> dict:
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
        # 「比較の概要」①データ段: feed_version / feed_info 期間 / 実データ窓。
        # scope の有無に依らず常時 (feed_info は任意ファイルなので None 許容)
        "data_briefs": {
            "old": _data_brief(old),
            "new": _data_brief(new),
        },
        # SD2: 同梱世代の比較範囲 (単一世代比較では None)。第1部に注記を出す
        "comparison_scope": event_set.context.get("comparison_scope"),
        # SD4 (改): 運行日の要点 (文字要約。カレンダー表示は 2026-07-24 に廃止)
        "service_days_note": _service_days_note(
            old, new, config, identity, trip_delta,
            scope_active=event_set.context.get("comparison_scope") is not None,
        ),
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

    SD3: 集計の基礎を「calendar_dates の追加日」から**実効運行日集合**
    (期間×フラグ − 削除 + 追加、フィード有効期間でクリップ) に置き換える —
    SD1 で「フラグ+大量削除」型の特定日 (PRT の祝日専用 service) が
    増えたため。第1部は日数+期間のみ (日付列挙は 2026-07-24 に撤去。
    具体日付は路線ページの special_dates が受け持つ)。
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
            # 日付列挙 (date_list) は第1部から撤去 (2026-07-24 決定 — 読み取れない)。
            # 具体日付は路線ページの special_dates (その場解説) が受け持つ
            "replaces_regular": bool(dates) and all(
                d in removed_by_others for d in dates
            ),
        })
    return result


def _data_brief(snapshot) -> dict:
    """「比較の概要」①データ段: feed_info の要約 + 実データの窓。

    feed_info (任意ファイル) が無い/列欠損は None のまま viewer が
    「なし」「記載なし」を出す。window は feed_info → 世代メタ → calendar
    全期間の順で解決した実効窓 (feed_info の期間と食い違うことがある —
    三重交通中勢は feed_info 12/31 まで・calendar は 10/23 で切れる)。"""
    from ..events.windows import feed_info_brief, snapshot_window

    brief = feed_info_brief(snapshot) or {}
    window = snapshot_window(snapshot)
    return {
        "feed_version": brief.get("feed_version"),
        "feed_start_date": brief.get("feed_start_date"),
        "feed_end_date": brief.get("feed_end_date"),
        "has_feed_info": bool(brief),
        "window": list(window.as_text()) if window is not None else None,
    }


def _per_date_worlds(snapshot, config: Config) -> dict | None:
    """日付ごとの「その日実際に走る世界」(SD4 改: 文字要約の素材)。

    {date: {"svcs": frozenset, "swap": bool, "special": bool}} と窓を返す。
    swap = 週次型は走るがその日の曜日を含まない (祝日等)、special = 特定日
    service が運行、日付が無い = その日は運行なし。定義は SD1/SD2 と同一。
    窓が config `[report] calendar_view_max_days` (550) を超える場合は None
    (国家規模の長期窓は文字要約も省略)。
    """
    from ..events.windows import snapshot_window
    from ..load.day_types import (
        _CALENDAR_DAY_COLUMNS,
        _exception_dates,
        day_set_of,
        effective_date_list,
    )

    window = snapshot_window(snapshot)
    if window is None:
        return None
    max_days = config.get("report", "calendar_view_max_days", default=550)
    if window.days() > max_days:
        return None

    trips = snapshot.table("trips")
    services_with_trips: set[str] = set()
    if trips is not None and not trips.empty:
        services_with_trips = {str(s) for s in trips["service_id"]}

    added_map, removed_map = _exception_dates(snapshot.table("calendar_dates"))
    window_text = window.as_text()

    by_date: dict[str, dict] = {}

    def add_dates(sid: str, dates: list[str]) -> None:
        dt = snapshot.day_types.get(sid, "irregular")
        for d in dates:
            e = by_date.setdefault(d, {"labels": set(), "_s": set()})
            e["labels"].add(dt)
            e["_s"].add(sid)

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

    import datetime as _dt

    days: dict[str, dict] = {}
    for text, e in by_date.items():
        wd = _dt.datetime.strptime(text, "%Y%m%d").date().weekday()
        regular = [t for t in e["labels"] if t not in ("irregular", "inactive")]
        matching = [
            t for t in regular
            if (day_set_of(t) or set()) and wd in day_set_of(t)
        ]
        days[text] = {
            "svcs": frozenset(e["_s"]),
            "swap": bool(regular) and not matching,
            "special": "irregular" in e["labels"],
        }
    return {"window": window, "days": days}


def _date_runs(dates: list[str], runs_max: int) -> tuple[list[list[str]], int]:
    """昇順日付列 → 連続ラン [[start, end], ...] (runs_max 件まで) と超過ラン数。"""
    import datetime as _dt

    runs: list[list[str]] = []
    prev = None
    for text in sorted(dates):
        d = _dt.datetime.strptime(text, "%Y%m%d").date()
        if prev is not None and (d - prev).days == 1:
            runs[-1][1] = text
        else:
            runs.append([text, text])
        prev = d
    return runs[:runs_max], max(0, len(runs) - runs_max)


def _service_days_note(
    old, new, config: Config, identity, trip_delta, scope_active: bool
) -> dict | None:
    """SD4 (改): 運行日の要点の文字要約 (カレンダー表示の代替。方針決定 2026-07-24)。

    - 掲載範囲 (旧/新の窓) と「両方が重なる期間」
    - 重なりの中で運行内容が変わる日 (日付単位の内容比較 — 便の内容署名の
      多重集合が異なる日。ID 非依存)
    - 曜日と異なるダイヤで走る日 (祝日等)・運行のない日 (各世代)
    期間が重ならない2時点では日付単位の比較を行わない (被覆の明示のみ) —
    「任意の2時点で動く」前提の縮退。
    """
    from collections import Counter

    from ..events.tripdelta import collect_trips
    from ..identity.route_family import route_to_family_map

    old_w = _per_date_worlds(old, config)
    new_w = _per_date_worlds(new, config)
    if old_w is None or new_w is None:
        return None
    runs_max = config.get("report", "note_runs_max", default=8)

    def side_summary(w):
        swap = [d for d, e in w["days"].items() if e["swap"]]
        window = w["window"]
        import datetime as _dt

        none_days = []
        d = window.start
        one = _dt.timedelta(days=1)
        while d <= window.end:
            if d.strftime("%Y%m%d") not in w["days"]:
                none_days.append(d.strftime("%Y%m%d"))
            d += one
        return swap, none_days

    old_swap, old_none = side_summary(old_w)
    new_swap, new_none = side_summary(new_w)

    lo = max(old_w["window"].start, new_w["window"].start)
    hi = min(old_w["window"].end, new_w["window"].end)
    overlap = lo <= hi

    changed: list[str] = []
    if overlap:
        # 便世界: 通常は trip_delta の全便 (scope なし = 全便そのもの)。
        # 同梱世代でフィルタ済み (scope あり) のときだけ全便を再収集する
        if scope_active:
            old_stop_to_base = {
                pid: c.base_name
                for c in identity.old_stop_clusters.values()
                for pid in c.platform_ids
            }
            new_stop_to_base = {
                pid: c.base_name
                for c in identity.new_stop_clusters.values()
                for pid in c.platform_ids
            }
            old_trips = collect_trips(
                old, route_to_family_map(identity.old_families), old_stop_to_base
            )
            new_trips = collect_trips(
                new, route_to_family_map(identity.new_families), new_stop_to_base
            )
        else:
            old_trips, new_trips = trip_delta.old_trips, trip_delta.new_trips

        def content_by_service(snapshot, trip_infos):
            trips = snapshot.table("trips")
            result: dict[str, Counter] = {}
            if trips is None or trips.empty:
                return result
            for tid, sid in zip(trips["trip_id"], trips["service_id"]):
                info = trip_infos.get(str(tid))
                if info is None:
                    continue
                # family/day_type は世代間で振れるため内容キーから除外
                key = hash((info.direction, info.base_seq, info.times))
                result.setdefault(str(sid), Counter())[key] += 1
            return result

        old_content = content_by_service(old, old_trips)
        new_content = content_by_service(new, new_trips)
        memo: dict[tuple, bool] = {}

        def differs(so: frozenset, sn: frozenset) -> bool:
            key = (so, sn)
            if key not in memo:
                co: Counter = Counter()
                cn: Counter = Counter()
                for s in so:
                    co.update(old_content.get(s, {}))
                for s in sn:
                    cn.update(new_content.get(s, {}))
                memo[key] = co != cn
            return memo[key]

        import datetime as _dt

        d = lo
        one = _dt.timedelta(days=1)
        empty: frozenset = frozenset()
        while d <= hi:
            t = d.strftime("%Y%m%d")
            so = old_w["days"].get(t, {}).get("svcs", empty)
            sn = new_w["days"].get(t, {}).get("svcs", empty)
            if differs(so, sn):
                changed.append(t)
            d += one

    def pack(dates):
        runs, extra = _date_runs(dates, runs_max)
        return {"count": len(dates), "runs": runs, "more_runs": extra}

    return {
        "old_window": list(old_w["window"].as_text()),
        "new_window": list(new_w["window"].as_text()),
        "overlap": [lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")] if overlap else None,
        "changed": pack(changed) if overlap else None,
        "swap": {"old": pack(old_swap), "new": pack(new_swap)},
        "no_service": {"old": pack(old_none), "new": pack(new_none)},
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


_RAWDIFF_CHUNK = 10_000  # 直列化のまとめ単位 (yield 回数と中間文字列の釣り合い)


def _payload_chunks(bundle: dict[str, Any]):
    """バンドル JSON (エスケープ済み) を文字列チャンクで逐次生成する。

    連結結果は「RawDiffSet 値を dict リスト化した bundle の json.dumps +
    "</"→"<\\/" エスケープ」と byte 同一。rawdiffs (数百万件) の dict リスト・
    一枚岩のペイロード文字列・replace の全量コピーを作らないための分割 (IN-3)。
    チャンク境界は構造文字 (',' '[' ']' '{' '}' '"') に接するため、"</" が
    境界を跨ぐことはなくエスケープは分割安全。
    """
    def esc(s: str) -> str:
        return s.replace("</", "<\\/")

    def dumps(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    yield "{"
    for i, (key, value) in enumerate(bundle.items()):
        prefix = ("," if i else "") + dumps(key) + ":"
        if isinstance(value, RawDiffSet):
            yield esc(prefix) + "["
            buf: list[str] = []
            for j, d in enumerate(value.diffs):
                buf.append("," if j else "")
                buf.append(esc(dumps(d.to_dict())))
                if len(buf) >= _RAWDIFF_CHUNK * 2:
                    yield "".join(buf)
                    buf.clear()
            if buf:
                yield "".join(buf)
            yield "]"
        else:
            yield esc(prefix + dumps(value))
    yield "}"


def _split_template(bundle: dict[str, Any], template_html: str) -> tuple[str, str]:
    """タイトル・説明を注入したテンプレートをデータ挿入点で二分する。

    タイトル・説明 (OGP) は静的に焼き込む — SNS のクローラは JS を実行しない
    ため、共有時のプレビューはここで焼き込んだ値が使われる。"""
    title, desc = _page_meta(bundle)
    prepared = (template_html
                .replace("__GTFS_SEMDIFF_TITLE__", html_lib.escape(title, quote=True))
                .replace("__GTFS_SEMDIFF_DESC__", html_lib.escape(desc, quote=True)))
    head, _, tail = prepared.partition("__GTFS_SEMDIFF_DATA__")
    return head, tail


def render_html(bundle: dict[str, Any], template_html: str) -> str:
    """ビルド済みビューアテンプレートにバンドル JSON を埋め込む。

    大規模フィードでは write_html (ファイル直書き) を使う —
    こちらは全体を1つの str に持つため RawDiff 数百万件級ではメモリを食う。"""
    head, tail = _split_template(bundle, template_html)
    return "".join([head, *_payload_chunks(bundle), tail])


def write_html(bundle: dict[str, Any], template_html: str, path) -> None:
    """render_html と同一内容の HTML をファイルへ逐次書き出す (IN-3)。

    ペイロード全体の文字列を一度も組み立てない — ピークメモリは
    イベント生成時点 + チャンク分に抑えられる。"""
    with open(path, "w", encoding="utf-8") as f:
        head, tail = _split_template(bundle, template_html)
        f.write(head)
        for chunk in _payload_chunks(bundle):
            f.write(chunk)
        f.write(tail)


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

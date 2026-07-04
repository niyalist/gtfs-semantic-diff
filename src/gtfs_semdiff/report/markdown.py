"""Markdown レポート生成 (京都市交通局別紙風・路線ごと章立て)。

ChangeEventSet の **JSON dict** を入力とする純粋な消費者。コアのオブジェクトには
依存しない (docs/design/architecture.md 設計原則 3)。

構成:
1. 表紙 (フィード名・比較世代・有効期間)
2. 全体サマリ (新設/廃止路線、停留所異動、運賃改定、major イベント一覧)
3. 路線別詳細 (route family 単位: イベント、停車パターン変化、時間帯別本数表)
4. 停留所の変更 (一覧表)
5. データ検証 (explained_ratio、ID churn、有効期間、未説明残差の全件)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# 章立てから除外して別章にまとめるイベント
_STOP_TYPES = {
    "STOP_ADDED", "STOP_REMOVED", "STOP_RENAMED", "STOP_RELOCATED",
    "PLATFORM_ADDED", "PLATFORM_REMOVED", "PLATFORM_CHANGED",
    "ACCESSIBILITY_CHANGED",
}
_VALIDATION_TYPES = {"TECHNICAL_ID_CHURN", "UNEXPLAINED_RESIDUAL", "FEED_VALIDITY_CHANGED"}
_FEEDWIDE_TYPES = {
    "FARE_CHANGED", "AGENCY_INFO_CHANGED", "TRANSLATION_CHANGED",
    "DAYTYPE_RESTRUCTURED", "HOLIDAY_EXCEPTION_CHANGED", "SEASONAL_SERVICE_CHANGED",
}

_SEVERITY_MARK = {"major": "🔴", "minor": "🟡", "info": "⚪"}


def render_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    events = data.get("events", [])
    feed = data.get("feed", {})

    _cover(lines, data, feed)
    _summary(lines, events)
    _route_chapters(lines, events, data.get("context", {}))
    _stop_chapter(lines, events)
    _validation_chapter(lines, events, data.get("accounting", {}))
    return "\n".join(lines) + "\n"


# --- 1. 表紙 ---


def _cover(lines: list[str], data: dict, feed: dict) -> None:
    title = f"{feed.get('org_id', '')} / {feed.get('feed_id', '')}".strip(" /")
    lines.append(f"# ダイヤ改正 意味的差分レポート: {title or 'GTFS 比較'}")
    lines.append("")
    old_p = feed.get("old_period") or ["", ""]
    new_p = feed.get("new_period") or ["", ""]
    lines.append(f"- 旧世代: `{feed.get('old_rid') or feed.get('old_source', '')}`"
                 + (f" (有効期間 {old_p[0]} 〜 {old_p[1]})" if old_p[0] else ""))
    lines.append(f"- 新世代: `{feed.get('new_rid') or feed.get('new_source', '')}`"
                 + (f" (有効期間 {new_p[0]} 〜 {new_p[1]})" if new_p[0] else ""))
    lines.append(f"- 生成日時: {data.get('generated_at', '')}")
    lines.append(f"- スキーマ: {data.get('schema_version', '')}")
    lines.append("")


# --- 2. 全体サマリ ---


def _summary(lines: list[str], events: list[dict]) -> None:
    lines.append("## 1. 全体サマリ")
    lines.append("")

    def names(type_: str, key: str) -> list[str]:
        return sorted(
            str(e["subject"].get(key, "")) for e in events if e["type"] == type_
        )

    added_routes = names("ROUTE_ADDED", "route_family")
    removed_routes = names("ROUTE_DISCONTINUED", "route_family")
    renamed_routes = [
        f"{e.get('old_ref', {}).get('name', '?')} → {e.get('new_ref', {}).get('name', '?')}"
        for e in events
        if e["type"] == "ROUTE_RENAMED" and e.get("old_ref")
    ]
    if added_routes:
        lines.append(f"- **路線新設**: {', '.join(added_routes)}")
    if removed_routes:
        lines.append(f"- **路線廃止**: {', '.join(removed_routes)}")
    if renamed_routes:
        lines.append(f"- **路線名変更**: {', '.join(renamed_routes)}")
    stop_added = names("STOP_ADDED", "stop_cluster")
    stop_removed = names("STOP_REMOVED", "stop_cluster")
    if stop_added:
        lines.append(f"- **停留所新設**: {', '.join(stop_added)}")
    if stop_removed:
        lines.append(f"- **停留所廃止**: {', '.join(stop_removed)}")
    renames = [
        f"{e.get('old_ref', {}).get('name', '?')} → {e.get('new_ref', {}).get('name', '?')}"
        for e in events
        if e["type"] == "STOP_RENAMED"
    ]
    if renames:
        lines.append(f"- **停留所改称**: {', '.join(renames)}")
    if any(e["type"] == "FARE_CHANGED" for e in events):
        lines.append("- **運賃改定あり** (詳細はデータ検証章の evidence 参照)")

    counts: dict[str, int] = defaultdict(int)
    for e in events:
        counts[e["display_name_ja"]] += 1
    lines.append("")
    lines.append("| イベント | 件数 |")
    lines.append("|---|--:|")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {count} |")
    lines.append("")

    majors = [e for e in events if e["severity"] == "major"]
    if majors:
        lines.append("### 主要変更 (major)")
        lines.append("")
        lines.append("| 種別 | 対象 | 内容 |")
        lines.append("|---|---|---|")
        for e in majors:
            lines.append(
                f"| {e['display_name_ja']} | {_subject_label(e)} | {_event_line(e)} |"
            )
        lines.append("")


# --- 3. 路線別詳細 ---


def _route_chapters(lines: list[str], events: list[dict], context: dict) -> None:
    by_family: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        family = e["subject"].get("route_family")
        if family and e["type"] not in _STOP_TYPES | _VALIDATION_TYPES:
            by_family[family].append(e)
    if not by_family:
        return

    profiles = context.get("band_profiles", [])
    prof_by_family: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        prof_by_family[p["route_family"]].append(p)

    lines.append("## 2. 路線別詳細")
    lines.append("")
    # major を含む family を先に
    order = sorted(
        by_family,
        key=lambda f: (
            0 if any(e["severity"] == "major" for e in by_family[f]) else 1,
            f,
        ),
    )
    for i, family in enumerate(order, 1):
        lines.append(f"### 2.{i} {family}")
        lines.append("")
        for e in sorted(by_family[family], key=lambda e: e["event_id"]):
            mark = _SEVERITY_MARK.get(e["severity"], "")
            lines.append(f"- {mark} **{e['display_name_ja']}**: {_event_line(e)}")
        lines.append("")

        pattern_changes = [
            e for e in by_family[family]
            if e.get("old_ref", {}) and "pattern" in (e.get("old_ref") or {})
        ]
        for e in pattern_changes[:1]:  # 代表1件の系統図
            lines.append("停車パターン変化 (代表便):")
            lines.append("")
            lines.append(f"- 旧: {_pattern_text(e['old_ref']['pattern'])}")
            lines.append(f"- 新: {_pattern_text(e['new_ref']['pattern'])}")
            lines.append("")

        changed_groups = {
            (e["subject"].get("direction", ""), e["subject"].get("day_type", ""))
            for e in by_family[family]
        }
        table = _band_table(prof_by_family.get(family, []), changed_groups)
        if table:
            lines.append("時間帯別本数 (旧→新):")
            lines.append("")
            lines.extend(table)
            lines.append("")


def _band_table(profiles: list[dict], changed_groups: set) -> list[str]:
    rows = [
        p for p in profiles
        if (p["direction"], p["day_type"]) in changed_groups or not changed_groups
    ] or profiles
    if not rows:
        return []
    bands = sorted({b for p in rows for b in p["bands"]})
    out = ["| 方向 | 曜日 | " + " | ".join(bands) + " | 計 |",
           "|---|---|" + "--:|" * (len(bands) + 1)]
    for p in rows:
        cells = []
        total_old = total_new = 0
        for b in bands:
            old_n, new_n = p["bands"].get(b, [0, 0])
            total_old += old_n
            total_new += new_n
            cells.append(f"{old_n}→{new_n}" if old_n != new_n else str(new_n))
        total = f"{total_old}→{total_new}" if total_old != total_new else str(total_new)
        direction = {"0": "往路", "1": "復路", "": "-"}.get(p["direction"], p["direction"])
        out.append(
            f"| {direction} | {_day_ja(p['day_type'])} | " + " | ".join(cells) + f" | {total} |"
        )
    return out


# --- 4. 停留所の章 ---


def _stop_chapter(lines: list[str], events: list[dict]) -> None:
    stop_events = [e for e in events if e["type"] in _STOP_TYPES]
    if not stop_events:
        return
    lines.append("## 3. 停留所の変更")
    lines.append("")
    lines.append("| 種別 | 停留所 | 内容 |")
    lines.append("|---|---|---|")
    for e in sorted(stop_events, key=lambda e: (e["type"], str(e["subject"]))):
        lines.append(
            f"| {e['display_name_ja']} | {e['subject'].get('stop_cluster', '')} | {_event_line(e)} |"
        )
    lines.append("")


# --- 5. データ検証章 ---


def _validation_chapter(lines: list[str], events: list[dict], accounting: dict) -> None:
    lines.append("## 4. データ検証")
    lines.append("")
    ratio = accounting.get("explained_ratio", 0)
    lines.append(
        f"- 説明被覆率 (explained_ratio): **{ratio:.4f}** "
        f"({accounting.get('explained', 0)} / {accounting.get('rawdiff_total', 0)} RawDiff)"
    )

    churn = [e for e in events if e["type"] == "TECHNICAL_ID_CHURN"]
    if churn:
        lines.append(f"- ID 張り替え (意味変化なし): {len(churn)} 件")
        for e in churn:
            lines.append(f"  - {_subject_label(e)}: {_event_line(e)}")
    validity = [e for e in events if e["type"] == "FEED_VALIDITY_CHANGED"]
    for e in validity:
        lines.append(f"- フィード有効期間更新: {_event_line(e)}")

    residuals = [e for e in events if e["type"] == "UNEXPLAINED_RESIDUAL"]
    lines.append("")
    if residuals:
        lines.append("### 未説明の残差 (UNEXPLAINED_RESIDUAL) 全件")
        lines.append("")
        lines.append("| ファイル | 件数 | rawdiff ID |")
        lines.append("|---|--:|---|")
        for e in residuals:
            ids = e.get("evidence", [])
            shown = ", ".join(ids[:10]) + (" …" if len(ids) > 10 else "")
            lines.append(f"| {e['subject'].get('file', '')} | {len(ids)} | {shown} |")
    else:
        lines.append("未説明の残差はない (全 RawDiff がいずれかのイベントで説明済み)。")
    lines.append("")


# --- 整形ヘルパ ---


def _day_ja(day_type: str) -> str:
    return {
        "weekday": "平日",
        "saturday": "土曜",
        "sunday_holiday": "日祝",
        "weekend": "土日",
        "daily": "毎日",
        "irregular": "特定日",
    }.get(day_type, day_type)


def _subject_label(e: dict) -> str:
    s = e.get("subject", {})
    parts = []
    if s.get("route_family"):
        parts.append(str(s["route_family"]))
        if s.get("day_type"):
            parts.append(_day_ja(s["day_type"]))
    elif s.get("stop_cluster"):
        parts.append(str(s["stop_cluster"]))
    elif s.get("file"):
        parts.append(str(s["file"]))
    elif s.get("shape_id"):
        parts.append(f"shape {s['shape_id']}")
    else:
        parts.append(str(s.get("scope", "")))
    return " ".join(p for p in parts if p)


def _pattern_text(pattern: list[str]) -> str:
    if len(pattern) <= 12:
        return " → ".join(pattern)
    return " → ".join(pattern[:5]) + f" → …({len(pattern) - 10}停留所)… → " + " → ".join(
        pattern[-5:]
    )


def _event_line(e: dict) -> str:
    """イベント1件の日本語一行要約。事実・数値は quantification から。"""
    q = e.get("quantification", {})
    t = e["type"]
    if t in ("SERVICE_REDUCED", "SERVICE_INCREASED"):
        return (
            f"{q.get('time_band', '')} 帯 {q.get('old_count', '?')}本 → "
            f"{q.get('new_count', '?')}本"
        )
    if t == "TIMETABLE_SHIFTED":
        if q.get("uniform"):
            return f"{q.get('trip_count', '?')}便を一様に {q.get('shift_min', '?')} 分シフト"
        return f"{q.get('time_band', '')} 帯で {q.get('trips_changed', '?')}便の時刻変更"
    if t == "FIRST_LAST_CHANGED":
        parts = []
        if abs(q.get("first_shift_min", 0)) >= 1:
            parts.append(f"始発 {q.get('old_first')} → {q.get('new_first')}")
        if abs(q.get("last_shift_min", 0)) >= 1:
            parts.append(f"終発 {q.get('old_last')} → {q.get('new_last')}")
        return "、".join(parts)
    if t in ("PATTERN_EXTENDED", "PATTERN_TRUNCATED", "STOP_INSERTED_IN_PATTERN",
             "STOP_REMOVED_FROM_PATTERN", "DETOUR_ADDED", "DETOUR_REMOVED"):
        stops = "、".join(q.get("stops", []))
        return f"{stops} ({q.get('trip_count', '?')}便)"
    if t in ("ROUTE_ADDED", "ROUTE_DISCONTINUED"):
        return f"{q.get('trip_count', '?')}便"
    if t == "ROUTE_RENAMED" and e.get("old_ref"):
        return f"{e['old_ref'].get('name', '?')} → {e['new_ref'].get('name', '?')}"
    if t == "STOP_RENAMED" and e.get("old_ref"):
        return f"{e['old_ref'].get('name', '?')} → {e['new_ref'].get('name', '?')}"
    if t in ("STOP_ADDED", "STOP_REMOVED"):
        return f"乗り場 {q.get('platform_count', '?')} 箇所"
    if t == "STOP_RELOCATED":
        return f"{q.get('moved_m', '?')} m 移動"
    if t == "PLATFORM_CHANGED":
        if "stop_time_rows" in q:
            return f"停車 {q['stop_time_rows']} 便分の乗り場付け替え"
        return f"{q.get('moved_m', '?')} m"
    if t in ("PLATFORM_ADDED", "PLATFORM_REMOVED"):
        return "、".join(q.get("platform_ids", []))
    if t == "TECHNICAL_ID_CHURN":
        if "trip_pairs" in q:
            return f"trip_id 張り替え {q['trip_pairs']} 組 (ダイヤ同一)"
        return (
            f"route_id 張り替え: {', '.join(q.get('removed_route_ids', []))} → "
            f"{', '.join(q.get('added_route_ids', []))}"
        )
    if t == "FARE_CHANGED":
        total = sum(v for v in q.values() if isinstance(v, int))
        return f"運賃データ {total} 行の変更"
    if t == "SHAPE_CHANGED":
        fams = "、".join(e["subject"].get("route_families", []) or [])
        return f"経路形状データの変更{f' ({fams})' if fams else ''}"
    if t == "HOLIDAY_EXCEPTION_CHANGED":
        return " / ".join(f"{k} {v}件" for k, v in q.items())
    if t == "DAYTYPE_RESTRUCTURED":
        return (
            f"{'、'.join(_day_ja(d) for d in (e.get('old_ref') or {}).get('day_types', []))} → "
            f"{'、'.join(_day_ja(d) for d in (e.get('new_ref') or {}).get('day_types', []))}"
        )
    if t == "FEED_VALIDITY_CHANGED":
        changed = q.get("changed_fields", {})
        if changed:
            return "; ".join(f"{k}: {v}" for k, v in changed.items())
        return f"{q.get('changed_rows', len(e.get('evidence', [])))} 箇所"
    if t == "TRAVEL_TIME_CHANGED":
        return f"{q.get('trip_count', '?')}便の所要時間・時刻修正"
    # 既定: quantification をそのまま
    return "; ".join(f"{k}={v}" for k, v in q.items()) if q else ""

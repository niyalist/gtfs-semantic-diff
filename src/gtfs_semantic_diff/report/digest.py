"""AI 向け digest (RD4a、docs/design/ai_interface.md)。

bundle (build_bundle の出力) を素材に、事実だけの要約層を JSON / Markdown の
2形式で生成する。**もう一つのレンダラ**であり再集計はしない — 便数・件数は
presentation / accounting の値をそのまま使う (数値一致不変条件)。

- L0 (build_digest): 全体要約。ID なし、名前と数値のみ。
- L1 (build_route_digest): 1路線の詳細。変化便の全レコード (trip_id 旧新付き)、
  無変化・ID のみ変更は件数に畳む。
- 省略は明示する: 上限で切ったら件数と全量の所在 (JSON / events.json) を記す。
"""
from __future__ import annotations

from typing import Any

# page digest の kind → 日本語の一言 (presentation._digest の語彙と対)
_KIND_JA = {
    "route_added": "路線新設",
    "route_removed": "路線廃止",
    "systems": "運行系統の増減",
    "reroute": "経由・区間の変更",
    "trips": "便数の増減",
    "retime": "時刻変更",
    "retime_minor": "ダイヤ微調整",
    "notes_only": "経路形状・行先表示のみの変化",
}

_DAY_JA = {
    "weekday": "平日", "saturday": "土曜", "sunday_holiday": "日祝",
    "weekend": "土日祝", "daily": "毎日", "irregular": "特定日",
    "inactive": "運行日なし",
}


def _day_ja(day_type: str) -> str:
    if day_type.startswith("dow_"):
        bits = day_type[4:]
        names = "月火水木金土日"
        days = "".join(n for n, b in zip(names, bits) if b == "1")
        return f"{days}曜" if days else day_type
    base, _, idx = day_type.partition("@")
    label = _DAY_JA.get(base, base)
    return f"{label}({idx})" if idx else label


# --- L0: 全体 digest ---


def build_digest(bundle: dict, config=None) -> dict[str, Any]:
    """L0 digest (JSON 構造)。ID を含めない (名前・数値のみ)。"""
    pres = bundle["presentation"]
    fo = pres["feed_overview"]
    events = bundle["events"]
    catalog = bundle["catalog"]

    by_type: dict[str, int] = {}
    for e in events["events"]:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1

    pages = pres["route_pages"]
    changed = [p for p in pages if p.get("has_changes")]
    routes = []
    for p in changed:
        entry: dict[str, Any] = {
            "name": p["route_group"],
            "day_totals": [
                {"day_type": d["day_type"], "old": d["old"], "new": d["new"],
                 **({"mixed": True} if d.get("mixed_old") or d.get("mixed_new")
                    else {})}
                for d in p["day_totals"]
            ],
            "changes": p["digest"],  # 構造化事実 (kind 語彙は presentation と共通)
        }
        if p.get("former_names"):
            entry["former_names"] = p["former_names"]
        if p.get("related_names"):
            entry["related_names"] = p["related_names"]
        routes.append(entry)

    sc = pres.get("stop_changes", {})

    def _stop_names(items):
        out = []
        for grp in items:
            for s in grp.get("stops", [grp]):
                name = s.get("name")
                if name:
                    out.append({"name": name,
                                "routes": s.get("groups") or grp.get("groups") or []})
        return out

    return {
        "digest_schema": 1,
        "scope": "feed",
        "meta": dict(bundle["meta"]),
        "data": {
            "old": fo.get("data_briefs", {}).get("old"),
            "new": fo.get("data_briefs", {}).get("new"),
            "comparison_scope": fo.get("comparison_scope"),
            "service_days_note": fo.get("service_days_note"),
        },
        "totals": {
            "trips_by_day": fo.get("day_types", []),
            "pages": len(pages),
            "pages_changed": len(changed),
            "accounting": events["accounting"],
            "lev1_trip_ratio": pres.get("coverage", {}).get("lev1_trip_ratio"),
        },
        "events_by_type": [
            {"type": t, "name_ja": catalog.get(t, {}).get("ja", t),
             "category": catalog.get(t, {}).get("category", ""), "count": n}
            for t, n in sorted(by_type.items())
        ],
        "stop_changes": {
            "renamed": [{"old": r.get("old_name"), "new": r.get("new_name"),
                         "routes": r.get("groups", [])}
                        for r in sc.get("renamed", [])],
            "added": _stop_names(sc.get("added", [])),
            "removed": _stop_names(sc.get("removed", [])),
            "relocated": _stop_names(sc.get("relocated", [])),
        },
        "routes": routes,
        "routes_unchanged": len(pages) - len(changed),
        "non_route": {
            "meta_events": fo.get("meta_events", []),
            "others": fo.get("others", []),
        },
        "verification": {
            **events["accounting"],
            "technical_id_churn": by_type.get("TECHNICAL_ID_CHURN", 0),
            "unexplained_residual": by_type.get("UNEXPLAINED_RESIDUAL", 0),
            "self_check": pres.get("self_check", []),
        },
    }


def _fmt_trips(day_totals: list[dict]) -> str:
    parts = []
    for d in day_totals:
        arrow = f"{d['old']}→{d['new']}" if d["old"] != d["new"] else f"{d['new']}"
        mixed = "(のべ)" if d.get("mixed") else ""
        parts.append(f"{_day_ja(d['day_type'])} {arrow}便{mixed}")
    return "、".join(parts)


def _fmt_change(c: dict) -> str:
    k = c.get("kind", "")
    label = _KIND_JA.get(k, k)
    if k in ("route_added", "route_removed"):
        return f"{label} ({c.get('trips', '?')}便)"
    if k == "systems":
        bits = []
        if c.get("added"):
            bits.append(f"新設{c['added']}")
        if c.get("removed"):
            bits.append(f"消滅{c['removed']}")
        return f"{label} ({'・'.join(bits)})"
    if k == "reroute":
        return f"{label} {c.get('trips', '?')}便"
    if k == "trips":
        days = "、".join(
            f"{_day_ja(d['day_type'])} {d['old']}→{d['new']}便"
            for d in c.get("days", []))
        return f"{label}: {days}"
    if k == "retime":
        return f"{label} {c.get('trips', '?')}便 (±{c.get('minor_max_min', '?')}分超)"
    if k == "retime_minor":
        return f"{label} {c.get('trips', '?')}便"
    if k == "notes_only":
        bits = []
        if c.get("shape"):
            bits.append(f"経路形状 {c['shape']}件")
        if c.get("headsign"):
            bits.append(f"行先表示 {c['headsign']}件")
        return f"{label} ({'・'.join(bits) or '—'})"
    return label


def _fmt_quant(q) -> str:
    """quantification の compact な文章化。dict をそのまま出さない。"""
    if not q:
        return ""
    if not isinstance(q, dict):
        return str(q)
    cf = q.get("changed_fields")
    if isinstance(cf, dict):
        return "、".join(f"{k}: {v}" for k, v in cf.items())
    return "、".join(f"{k} {v}" for k, v in q.items())


def render_digest_md(d: dict, routes_max: int = 200,
                     stops_max: int = 50) -> str:
    """L0 digest の Markdown。見出し構造は固定 (スキーマの一部)。

    routes_max / stops_max は Markdown 版の上限 (超過は件数を明示して
    JSON 版へ誘導 — 省略は必ず明示する)。JSON 版は常に全量。"""
    meta = d["meta"]
    feed = meta.get("feed", {})
    agency = "・".join(meta.get("agency_names") or []) or \
        f"{feed.get('org_id', '')}/{feed.get('feed_id', '')}".strip("/")
    lines: list[str] = []
    a = lines.append

    a(f"# 差分ダイジェスト: {agency or '(不明)'}")
    a("")
    a(f"生成: {meta.get('tool')} {meta.get('version')} / {meta.get('generated_at')}"
      f" / digest_schema {d['digest_schema']}")
    a("")
    a("## 1. 比較の概要")
    a("")
    for side, label in (("old", "旧"), ("new", "新")):
        b = d["data"].get(side) or {}
        src = feed.get(f"{side}_uid") or feed.get(f"{side}_source") or ""
        period = b.get("feed_info") or b.get("window") or None
        span = f" {period[0]}〜{period[1]}" if isinstance(period, (list, tuple)) \
            and len(period) == 2 else ""
        a(f"- {label}: {src}{span}")
    if d["data"].get("comparison_scope"):
        a("- 注: 同梱世代の比較範囲 (comparison_scope) が適用されている")
    note = d["data"].get("service_days_note")
    if isinstance(note, str) and note:
        a(f"- 運行日の要点: {note}")
    elif isinstance(note, dict) and note.get("overlap") is None and \
            note.get("old_window") and note.get("new_window"):
        # 構造化 note の詳細 (swap/no_service) は L0 では出さない — JSON に全量
        a("- 注: 新旧の有効期間に重なりがない (期間の離れた世代の比較)")
    a("")
    a("## 2. 全体集計")
    a("")
    a(f"- 便数 (1日あたり・曜日別): {_fmt_trips([{**t, 'mixed': t.get('mixed_old') or t.get('mixed_new')} for t in d['totals']['trips_by_day']])}")
    a(f"- 路線ページ: {d['totals']['pages']} (変化あり {d['totals']['pages_changed']})")
    acc = d["totals"]["accounting"]
    a(f"- 説明台帳: 生差分 {acc['rawdiff_total']} 件中 {acc['explained']} 件を"
      f"説明 (explained_ratio {acc['explained_ratio']:.4f})")
    a("")
    a("## 3. イベント種別")
    a("")
    if d["events_by_type"]:
        a("| type | 表示名 | 件数 |")
        a("|---|---|---|")
        for row in d["events_by_type"]:
            a(f"| {row['type']} | {row['name_ja']} | {row['count']} |")
    else:
        a("(イベントなし)")
    a("")
    a("## 4. 停留所の変化")
    a("")
    sc = d["stop_changes"]
    any_stop = False
    for key, label in (("renamed", "改称"), ("added", "新設"),
                       ("removed", "廃止"), ("relocated", "移設")):
        items = sc.get(key, [])
        for s in items[:stops_max]:
            any_stop = True
            routes = "、".join(s.get("routes", []))
            where = f" (路線: {routes})" if routes else ""
            if key == "renamed":
                a(f"- 改称: {s['old']} → {s['new']}{where}")
            else:
                a(f"- {label}: {s['name']}{where}")
        if len(items) > stops_max:
            a(f"- ({label}はほか {len(items) - stops_max} 件 — 全量は"
              f" JSON 版の stop_changes に。省略なし)")
    if not any_stop:
        a("(なし)")
    a("")
    a("## 5. 路線別の変化")
    a("")
    routes = d["routes"]
    for p in routes[:routes_max]:
        a(f"### {p['name']}")
        a("")
        if p.get("former_names"):
            a(f"- 旧名称: {'、'.join(p['former_names'])}")
        a(f"- 便数: {_fmt_trips(p['day_totals'])}")
        for c in p["changes"]:
            a(f"- {_fmt_change(c)}")
        a("")
    if len(routes) > routes_max:
        a(f"(ほか {len(routes) - routes_max} 路線に変化あり — 全量は JSON 版の"
          f" routes に。省略なし)")
        a("")
    a(f"変化のない路線: {d['routes_unchanged']} ページ")
    a("")
    a("## 6. 路線に紐付かない変化")
    a("")
    nr = d["non_route"]
    names = {r["type"]: r["name_ja"] for r in d["events_by_type"]}
    if nr["meta_events"] or nr["others"]:
        for e in nr["meta_events"]:
            a(f"- {names.get(e['type'], e['type'])}: "
              f"{_fmt_quant(e.get('quantification'))}")
        for o in nr["others"]:
            a(f"- {names.get(o['type'], o['type'])} ({o['type']}): "
              f"{o['count']} 件")
    else:
        a("(なし)")
    a("")
    a("## 7. 検証 (説明台帳)")
    a("")
    v = d["verification"]
    a(f"- explained_ratio: {v['explained_ratio']:.4f}"
      f" ({v['explained']} / {v['rawdiff_total']})")
    resid = v.get("residual_breakdown_by_file") or {}
    if resid:
        a("- 残差の所在: " + "、".join(f"{f} {n}件" for f, n in resid.items()))
    a(f"- TECHNICAL_ID_CHURN (ID 張り替え): {v['technical_id_churn']} 件"
      f" / UNEXPLAINED_RESIDUAL: {v['unexplained_residual']} 件")
    a(f"- self_check: {len(v.get('self_check') or [])} 件")
    a("")
    a("詳細 (証拠・行レベル) は events.json / rawdiffs.json"
      " (docs/api/reference.md)。")
    return "\n".join(lines) + "\n"


# --- L1: 路線詳細 ---


def _first_time(times) -> str | None:
    for t in times or []:
        if t:
            return t[:5] if len(t) >= 5 else t
    return None


def build_route_digest(bundle: dict, route_name: str) -> dict[str, Any]:
    """L1: 1路線の詳細。変化便は全レコード、無変化・ID のみ変更は件数。"""
    pres = bundle["presentation"]
    page = next((p for p in pres["route_pages"]
                 if p["route_group"] == route_name), None)
    if page is None:
        names = [p["route_group"] for p in pres["route_pages"]]
        raise KeyError(f"route not found: {route_name!r}. available: {names}")

    buckets = []
    for t in page.get("timetables", []):
        changed = []
        n_unchanged = n_id = 0
        for c in t["columns"]:
            st = c["status"]
            if st == "unchanged":
                n_unchanged += 1
                continue
            if st == "id_changed":
                n_id += 1
                continue
            rec: dict[str, Any] = {
                "status": st,
                "departure_old": _first_time(c.get("times_old")),
                "departure_new": _first_time(c.get("times_new")),
                "trip_id_old": c.get("trip_id_old"),
                "trip_id_new": c.get("trip_id_new"),
            }
            if st in ("retimed", "rerouted"):
                rec["changed_stops"] = len(c.get("changed_positions") or [])
            if st == "rerouted":
                po = {i for i, v in enumerate(c.get("times_old") or []) if v}
                pn = {i for i, v in enumerate(c.get("times_new") or []) if v}
                rec["stops_removed"] = len(po - pn)
                rec["stops_added"] = len(pn - po)
            changed.append(rec)
        buckets.append({
            "direction": t["label"],
            "day_type": t["day_type"],
            "sheet_label": t.get("sheet_label"),
            "changed": changed,
            "unchanged": n_unchanged,
            "id_changed": n_id,
        })

    lv3 = page.get("summary", {}).get("level3") or []
    return {
        "digest_schema": 1,
        "scope": "route",
        "route_group": route_name,
        "meta": dict(bundle["meta"]),
        "former_names": page.get("former_names") or [],
        "day_totals": page["day_totals"],
        "changes": page["digest"],
        "timetable": buckets,
        "stop_pattern_changes": [
            {"added_stops": u.get("added_stops", []),
             "removed_stops": u.get("removed_stops", []),
             "systems": [{"label": s.get("label"),
                          "affected_trips": s.get("affected_trips"),
                          "system_trips": s.get("system_trips")}
                         for s in u.get("systems", [])]}
            for u in lv3
        ],
    }


_STATUS_JA = {
    "added": "新設", "removed": "廃止", "retimed": "時刻変更",
    "rerouted": "経由変更",
}


def render_route_digest_md(d: dict) -> str:
    lines: list[str] = []
    a = lines.append
    a(f"# 路線ダイジェスト: {d['route_group']}")
    a("")
    meta = d["meta"]
    a(f"生成: {meta.get('tool')} {meta.get('version')} / {meta.get('generated_at')}")
    a("")
    if d["former_names"]:
        a(f"旧名称: {'、'.join(d['former_names'])}")
        a("")
    a(f"便数: {_fmt_trips(d['day_totals'])}")
    for c in d["changes"]:
        a(f"- {_fmt_change(c)}")
    a("")
    a("## 便の変化")
    a("")
    for b in d["timetable"]:
        sheet = f" ({b['sheet_label']})" if b.get("sheet_label") else ""
        a(f"### {b['direction']}{sheet} [{_day_ja(b['day_type'])}]")
        a("")
        for r in b["changed"]:
            dep = r.get("departure_new") or r.get("departure_old") or "?"
            label = _STATUS_JA.get(r["status"], r["status"])
            bits = [f"{dep}発 [{label}]"]
            if r["status"] == "retimed":
                bits.append(f"{r.get('changed_stops', 0)}停留所で時刻変更")
            if r["status"] == "rerouted":
                ba = []
                if r.get("stops_added"):
                    ba.append(f"停車追加{r['stops_added']}")
                if r.get("stops_removed"):
                    ba.append(f"停車削除{r['stops_removed']}")
                if ba:
                    bits.append("・".join(ba))
                if r.get("departure_old") and r.get("departure_new") and \
                        r["departure_old"] != r["departure_new"]:
                    bits.append(f"旧 {r['departure_old']}発")
            tid = (f"trip {r.get('trip_id_old') or '—'}"
                   f"→{r.get('trip_id_new') or '—'}")
            a(f"- {' / '.join(bits)} ({tid})")
        rest = []
        if b["unchanged"]:
            rest.append(f"無変化 {b['unchanged']}便")
        if b["id_changed"]:
            rest.append(f"ID のみ変更 {b['id_changed']}便")
        if rest:
            a(f"- ほか {'、'.join(rest)}")
        if not b["changed"] and not rest:
            a("(便なし)")
        a("")
    sp = d["stop_pattern_changes"]
    if sp:
        a("## 停車パターンの変化")
        a("")
        for u in sp:
            if u["added_stops"]:
                a(f"- 停車追加: {'、'.join(u['added_stops'])}")
            if u["removed_stops"]:
                a(f"- 停車取りやめ: {'、'.join(u['removed_stops'])}")
            for s in u["systems"]:
                a(f"  - {s['label']}: {s['affected_trips']}/{s['system_trips']}便")
        a("")
    return "\n".join(lines) + "\n"

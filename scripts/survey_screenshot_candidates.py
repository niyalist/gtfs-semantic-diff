"""論文スクショ候補の走査 (2026-07-30、読み取り専用)。

④時刻表の各シートについて列ステータスの構成を集計し、
  A) 基本のダイヤ改正: added / removed / retimed / unchanged が1枚に同居
  B) 構造的改正: rerouted (経由変更) を含む。途中打ち切り/延伸
     (新旧の停車位置集合が包含関係) はフラグ付け
の候補を列挙する。1画面に収まる規模 (列数・軸長) も記録する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gtfs_semantic_diff.config import Config
from gtfs_semantic_diff.events.day_worlds import build_world_context
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.report.presentation import build_presentation


def scan(name: str, old_zip: str, new_zip: str) -> list[dict]:
    config = Config.load()
    old = load_snapshot(old_zip, config)
    new = load_snapshot(new_zip, config)
    es, raw, identity, td = compare_snapshots_with_artifacts(old, new, config)
    wc = build_world_context(old, new, td.old_trips, td.new_trips)
    pres = build_presentation(es, identity, td, config, day_worlds=wc)

    rows = []
    for page in pres["route_pages"]:
        pname = page.get("route_group") or ""
        for t in page.get("timetables", []):
            cols = t["columns"]
            st = {}
            trunc = ext = 0
            for c in cols:
                st[c["status"]] = st.get(c["status"], 0) + 1
                if c["status"] == "rerouted":
                    po = {i for i, v in enumerate(c["times_old"] or []) if v}
                    pn = {i for i, v in enumerate(c["times_new"] or []) if v}
                    if pn < po:
                        trunc += 1  # 新が旧の真部分集合 = 打ち切り/区間短縮
                    elif po < pn:
                        ext += 1    # 旧が新の真部分集合 = 延伸
            rows.append({
                "feed": name, "page": pname, "label": t["label"],
                "day": t["day_type"], "sheet_label": t.get("sheet_label"),
                "n_cols": len(cols), "axis_len": len(t["stop_axis"]),
                "status": st, "truncated": trunc, "extended": ext,
            })
    return rows


if __name__ == "__main__":
    root = Path(__file__).parent.parent
    PAIRS = [
        ("nagai", "data/nagai/old.zip", "data/nagai/new.zip"),
        ("chitetsu", "data/chitetsu/old.zip", "data/chitetsu/new.zip"),
        ("kakegawa", "data/kakegawa/prev_2.zip", "data/kakegawa/current.zip"),
        ("tokushima", "data/tokushima/old.zip", "data/tokushima/new.zip"),
        ("hokusetsu", "data/aichi/hokusetsu_old.zip", "data/aichi/hokusetsu_new.zip"),
        ("toyota_chiiki", "data/aichi/chiikibus_old.zip", "data/aichi/chiikibus_new.zip"),
        ("toyota_oiden", "data/aichi/kikanbus_old.zip", "data/aichi/kikanbus_new.zip"),
        ("hokkaido_chuo", "data/hokkaido/hokkaido_chuo_20251219.zip",
         "data/hokkaido/hokkaido_chuo_20260601.zip"),
        ("engan", "data/hokkaido/engan_bus_20251219.zip",
         "data/hokkaido/engan_bus_20260601.zip"),
        ("kyoto", "data/kyoto/Kyoto_City_Bus_GTFS-20250630.zip",
         "data/kyoto/Kyoto_City_Bus_GTFS_20260630.zip"),
        ("nagoya", "data/nagoya/20250329_bus-gtfs-jp.zip",
         "data/nagoya/20260328_bus-gtfs-jp.zip"),
    ]
    out = []
    for name, o, n in PAIRS:
        try:
            out.extend(scan(name, str(root / o), str(root / n)))
            print(f"[{name}] ok", flush=True)
        except Exception as e:  # noqa: BLE001 調査スクリプト
            print(f"[{name}] FAILED: {e}", flush=True)
    Path(root / "data" / "screenshot_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total sheets: {len(out)}")

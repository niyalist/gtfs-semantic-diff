"""I3 (i18n.md §6): en DOM 監査用フィクスチャの生成。

停留所・路線名がすべて英語の合成 GTFS ペアから core bundle を作り、
viewer/tests/fixtures/en_bundle.json に書き出す。viewer 側の en 監査テスト
(en_audit.test.js) が App 全体を en で描画し、DOM に CJK が現れないことを
検査する — データが英語なので、CJK の検出 = 当方の焼き込み、が成立する。

日本語ラベル生成の主要経路を1ペアで踏む:
- 循環の両回り (loop / loop_dir「先回り」ラベル)
- 同一停留所集合・順序違いの分冊 (「先回り」sheet)、識別停留所の分冊 (「経由」)
- 便の新設・廃止・時刻変更、停留所の改称、irregular (特定日) service、
  未知ファイルの残差、feed_info 変更 (OGP 題名)

再生成: .venv.nosync/bin/python scripts/gen_i18n_en_fixture.py
(決定的 — meta.generated_at は固定値に正規化する)
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.events.pipeline import (  # noqa: E402
    compare_snapshots_with_artifacts,
)
from gtfs_semantic_diff.load import load_snapshot  # noqa: E402
from gtfs_semantic_diff.report.bundle import build_bundle  # noqa: E402

N = 12  # 循環の停留所数 (小さすぎる輪はパターン類似で束なる)
LOOP_STOPS = ["Station", "Maple", "Oak", "Cedar", "Pine", "Birch",
              "Elm", "Willow", "Aspen", "Laurel", "Hazel", "Rowan"]
# 末尾が1文字 ("Stop A" 等) だと乗り場記号剥がし (G6、I4 で検証予定) で
# 同名に潰れるため、接尾字のない名前にする


def loop_files(renamed: bool, extra_trip: bool) -> dict[str, str]:
    stops = list(LOOP_STOPS)
    if renamed:
        stops[3] = "Cedar North"  # Cedar の改称 (STOP_RENAMED 経路)
    files = {
        "agency.txt": ("agency_id,agency_name,agency_url,agency_timezone\n"
                       "A1,Sample Transit,https://example.com,Asia/Tokyo\n"),
        "feed_info.txt": (
            "feed_publisher_name,feed_publisher_url,feed_lang,feed_version\n"
            + ("Sample Transit,https://example.com,en,v2\n" if renamed else
               "Sample Transit,https://example.com,en,v1\n")),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,"
            "sunday,start_date,end_date\n"
            "WD,1,1,1,1,1,0,0,20250401,20260331\n"),
        # irregular (特定日): calendar_dates のみの service
        "calendar_dates.txt": ("service_id,date,exception_type\n"
                               "SP,20250815,1\nSP,20250816,1\n"),
        "routes.txt": ("route_id,route_short_name,route_long_name,route_type\n"
                       "R1,10,Downtown Loop,3\n"
                       "R2,20,Hillside Line,3\n"),
    }
    files["stops.txt"] = (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        + "".join(f"S{i + 1},{name},36.{i:02d}00,139.{i:02d}00\n"
                  for i, name in enumerate(stops))
        # R2 用の識別停留所 (「経由」分冊)
        + "H1,Hill Gate,36.2000,139.2000\n"
        + "H2,Ridge Park,36.2100,139.2100\n"
        + "H3,Valley View,36.2200,139.2200\n"
    )
    trips = ["R1,WD,LOOP_CW", "R1,WD,LOOP_CCW",
             "R2,WD,HILL_A1", "R2,WD,HILL_A2", "R2,WD,HILL_B1",
             "R1,SP,SPECIAL1"]
    if extra_trip:
        trips.append("R1,WD,LOOP_CW2")  # 新設便 (added)
    files["trips.txt"] = "route_id,service_id,trip_id\n" + "".join(
        t + "\n" for t in trips)

    fwd = [1] + list(range(2, N + 1)) + [1]
    rev = [1] + list(range(N, 1, -1)) + [1]

    def st(trip: str, hour: int, seq: list[int], minute0: int = 0) -> str:
        return "".join(
            f"{trip},{hour:02d}:{minute0 + i:02d}:00,"
            f"{hour:02d}:{minute0 + i:02d}:00,S{s},{i + 1}\n"
            for i, s in enumerate(seq))

    body = st("LOOP_CW", 8, fwd) + st("LOOP_CCW", 9, rev)
    # 特定日便は時刻変更で世代間差を作る (retimed)
    body += st("SPECIAL1", 10, fwd, minute0=(5 if renamed else 0))
    if extra_trip:
        body += st("LOOP_CW2", 11, fwd)
    # R2: 同一端点で中間が違う2系統 (経由分冊) — A系×2便 + B系1便
    hill_a = "H1,S1,H2"
    hill_b = "H1,S1,H3"
    for trip, hour, seq in (("HILL_A1", 7, hill_a), ("HILL_A2", 8, hill_a),
                            ("HILL_B1", 9, hill_b)):
        for i, sid in enumerate(seq.split(",")):
            body += (f"{trip},{hour:02d}:{i * 20:02d}:00,"
                     f"{hour:02d}:{i * 20:02d}:00,{sid},{i + 1}\n")
    files["stop_times.txt"] = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + body)
    if not renamed:
        # 旧世代だけの未知ファイル → 残差 (検証モードの表示経路)
        files["notes.txt"] = "note_id,text\n1,legacy note\n"
    return files


def write_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


def main() -> None:
    out_dir = ROOT / "viewer" / "tests" / "fixtures"
    out_dir.mkdir(exist_ok=True)
    tmp = ROOT / "data"
    tmp.mkdir(exist_ok=True)
    old_zip = write_zip(tmp / "i18n_en_old.zip", loop_files(False, False))
    new_zip = write_zip(tmp / "i18n_en_new.zip", loop_files(True, True))
    config = Config.load()
    old = load_snapshot(old_zip, config=config)
    new = load_snapshot(new_zip, config=config)
    ev, raw, ident, delta = compare_snapshots_with_artifacts(old, new, config)
    bundle = build_bundle(old, new, config, ev, raw, ident, delta, core=True)
    bundle["meta"]["generated_at"] = "2026-01-01T00:00:00+00:00"  # 決定性
    bundle["meta"]["version"] = "fixture"
    out = out_dir / "en_bundle.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True),
                   "utf-8")
    pres = bundle["presentation"]
    kinds = set()
    for page in pres["route_pages"]:
        for g in page["overview"]["direction_groups"]:
            if g.get("label_parts"):
                kinds.add(g["label_parts"]["kind"])
            for lg in g["legs"]:
                if lg.get("label_parts"):
                    kinds.add(lg["label_parts"]["kind"])
        for tb in page["timetables"]:
            if tb.get("sheet_label_parts"):
                kinds.add(tb["sheet_label_parts"]["kind"])
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("label_parts kinds:", sorted(kinds))
    print("pages:", [p["route_group"] for p in pres["route_pages"]],
          "self_check:", pres["self_check"])


if __name__ == "__main__":
    main()

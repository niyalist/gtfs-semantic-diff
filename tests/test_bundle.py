"""report/bundle.py と CLI --html の単体テスト。"""

import json

from click.testing import CliRunner

from gtfs_semantic_diff.cli import main
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.report.bundle import (
    build_bundle,
    render_html,
    write_events_json_gz,
    write_html,
    write_html_split,
    write_rawdiffs_json_gz,
)

from .conftest import MINIMAL_FEED, make_gtfs_zip
from .test_diff0 import NEW_FILES


def _bundle(tmp_path, config, core=False):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    return build_bundle(
        old, new, config, event_set, rawdiffs, identity, trip_delta, core=core
    )


def test_bundle_structure(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    assert set(bundle) == {
        "schema_version", "events", "rawdiffs", "presentation", "geometry",
        "timetables", "catalog", "meta",
    }
    assert bundle["schema_version"] == 1
    # 埋め込みペイロードは「rawdiffs を dict リスト化した bundle の JSON」と等価
    # (rawdiffs は RawDiffSet のまま遅延直列化する — IN-3。render_html が正)
    html = render_html(bundle, "<x>__GTFS_SEMDIFF_DATA__</x>")
    payload = html[len("<x>"):-len("</x>")]
    assert "表町一丁目" in payload
    data = json.loads(payload.replace("<\\/", "</"))
    assert data["rawdiffs"] == [d.to_dict() for d in bundle["rawdiffs"].diffs]

    # 全イベントの evidence が rawdiffs で解決できる (クリック→生値の構造保証)
    ids = {d["rawdiff_id"] for d in data["rawdiffs"]}
    for e in bundle["events"]["events"]:
        assert set(e["evidence"]) <= ids
        assert e["display_name_ja"] and e["display_name_en"]

    # write_html (ファイル逐次書き出し) は render_html と byte 同一
    out = tmp_path / "bundle.html"
    write_html(bundle, "<x>__GTFS_SEMDIFF_DATA__</x>", out)
    assert out.read_text(encoding="utf-8") == html

    # カタログは全44タイプ ja/en (v0.2.4: SERVICE_DAYS_CHANGED 追加)
    assert len(bundle["catalog"]) == 44
    assert bundle["catalog"]["SERVICE_REDUCED"]["en"] == "Service reduced"

    # レポート表題用の事業者名 (agency.txt 由来)
    assert bundle["meta"]["agency_names"] == ["テストバス"]


def test_core_bundle(tmp_path, config):
    """RD1a: core バンドル — rawdiffs キーなし、evidence は件数+サンプル、
    file_diffs は (file, kind) 別の件数+説明イベント焼き込みサンプル。"""
    full = _bundle(tmp_path, config)
    core = _bundle(tmp_path, config, core=True)
    assert "rawdiffs" not in core
    assert set(core) == {
        "schema_version", "events", "presentation", "geometry", "timetables",
        "catalog", "meta", "file_diffs",
    }
    # そのまま JSON 直列化できる (RawDiffSet を含まない)
    json.dumps(core, ensure_ascii=False)

    full_events = {e["event_id"]: e for e in full["events"]["events"]}
    ev_max = config.get("report", "evidence_sample_max", default=50)
    for e in core["events"]["events"]:
        orig = full_events[e["event_id"]]
        assert e["evidence"] == []
        assert e["evidence_total"] == len(orig["evidence"])
        expect = orig["evidence"][:ev_max]
        assert [d["rawdiff_id"] for d in e["evidence_sample"]] == expect

    # file_diffs の件数合計 = RawDiff 総数 (網羅性は件数で保証)
    total = sum(
        slot["count"] for kinds in core["file_diffs"].values() for slot in kinds.values()
    )
    assert total == len(full["rawdiffs"].diffs)
    # サンプル行の explainer は「最初に claim したイベント」(先勝ち規則)
    first_claim = {}
    for ev in full["events"]["events"]:
        for rid in ev["evidence"]:
            first_claim.setdefault(rid, ev["event_id"])
    for kinds in core["file_diffs"].values():
        for slot in kinds.values():
            assert len(slot["sample"]) <= config.get(
                "report", "file_diff_sample_max", default=100
            )
            for row in slot["sample"]:
                assert row["explainer"] == first_claim.get(row["rawdiff_id"])

    # accounting (網羅性の数値) は full と同一
    assert core["events"]["accounting"] == full["events"]["accounting"]


def test_write_html_split(tmp_path, config):
    """RD1b: アプリ HTML には {"$data_url"} のみ、データは別 JSON (gzip 可)。"""
    import gzip

    bundle = _bundle(tmp_path, config, core=True)
    template = "<x>__GTFS_SEMDIFF_DATA__</x>"
    html_p = tmp_path / "app.html"
    data_p = tmp_path / "data.json"
    write_html_split(bundle, template, html_p, data_p,
                     "/r/pair/v/1.json", gzip_data=False)
    marker = json.loads(html_p.read_text(encoding="utf-8")[len("<x>"):-len("</x>")])
    assert marker == {"$data_url": "/r/pair/v/1.json"}
    data = json.loads(data_p.read_text(encoding="utf-8"))
    assert "file_diffs" in data and "rawdiffs" not in data
    assert data["events"]["accounting"] == bundle["events"]["accounting"]

    gz_p = tmp_path / "data.json.gz"
    write_html_split(bundle, template, html_p, gz_p, "/r/pair/v/1.json")
    with gzip.open(gz_p, "rt", encoding="utf-8") as f:
        assert json.load(f) == data


def test_raw_json_exports(tmp_path, config):
    """RD2: 生データ DL 用 gzip 書き出しは CLI 出力と同形式・同内容。"""
    import gzip

    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"),
                        config=config)
    event_set, rawdiffs, _, _ = compare_snapshots_with_artifacts(old, new, config)

    ev_p = tmp_path / "events.json.gz"
    rd_p = tmp_path / "rawdiffs.json.gz"
    ev_bytes = write_events_json_gz(event_set.to_dict(), ev_p)
    rd_bytes = write_rawdiffs_json_gz(rawdiffs, rd_p)

    with gzip.open(ev_p, "rt", encoding="utf-8") as f:
        text = f.read()
    assert len(text.encode("utf-8")) == ev_bytes  # 戻り値 = 非圧縮バイト数
    assert json.loads(text) == event_set.to_dict()

    with gzip.open(rd_p, "rt", encoding="utf-8") as f:
        text = f.read()
    assert len(text.encode("utf-8")) == rd_bytes
    assert json.loads(text) == {"rawdiffs": [d.to_dict() for d in rawdiffs.diffs]}


def test_feed_overview_structure(tmp_path, config):
    # 第1部 (ファイル対応表・曜日別便数) と第4部 (その他の集計) の素材
    overview = _bundle(tmp_path, config)["presentation"]["feed_overview"]
    files = {f["name"]: f for f in overview["files"]}
    assert "stops.txt" in files and "trips.txt" in files
    st = files["stops.txt"]
    assert st["status"] == "continued"
    assert st["rows_old"] is not None and st["rows_new"] is not None
    # RawDiff 内訳がファイル別に集計されている (NEW_FILES は stops を改変する)
    assert st["row_added"] + st["row_removed"] + st["field_changed"] > 0
    # 曜日区分ごとの便数は固定順
    days = [d["day_type"] for d in overview["day_types"]]
    assert days == sorted(days, key=lambda d: ["weekday", "saturday", "sunday_holiday",
                                               "weekend", "daily", "irregular"].index(d))
    # 第4部: 第1〜3部で説明しないイベントのみが落ちる (route/stop/part1 は含まない)
    part4_types = {o["type"] for o in overview["others"]}
    assert not part4_types & {"STOP_RENAMED", "SERVICE_REDUCED", "ROUTE_ADDED",
                              "FEED_VALIDITY_CHANGED"}


def test_coverage_destinations(tmp_path, config):
    # V5: 全イベントに表示先 (part 1〜4) が付き、第4部の件数が feed_overview
    # の others と一致する (同一の対応関数を共有)
    bundle = _bundle(tmp_path, config)
    cov = bundle["presentation"]["coverage"]
    events = bundle["events"]["events"]
    assert set(cov["destinations"]) == {e["event_id"] for e in events}
    assert cov["events_total"] == len(events)
    by_part = cov["events_by_part"]
    assert sum(by_part.values()) == cov["events_total"]
    n4 = sum(o["count"] for o in bundle["presentation"]["feed_overview"]["others"])
    assert by_part["4"] == n4
    # 表示先の型対応: 停留所イベント→第2部、路線イベント→第3部 (route_group 付き)
    for e in events:
        d = cov["destinations"][e["event_id"]]
        if e["type"] == "STOP_RENAMED":
            assert d["part"] == 2
        if e["type"] in ("SERVICE_REDUCED", "SERVICE_INCREASED"):
            assert d["part"] == 3 and d["route_group"]
    assert 0.0 <= cov["report_coverage_ratio"] <= 1.0


def test_bundle_geometry_statuses(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    points = [f for f in bundle["geometry"]["features"] if f["geometry"]["type"] == "Point"]
    statuses = {f["properties"]["status"] for f in points}
    assert "added" in statuses  # 新設団地 (S4)
    names = {f["properties"]["base_name"] for f in points}
    assert "新設団地" in names


def test_bundle_timetables_cover_service_events(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    keys = {
        (t["route_family"], t["direction"], t["day_type"]) for t in bundle["timetables"]
    }
    for e in bundle["events"]["events"]:
        s = e["subject"]
        if e["type"] in ("SERVICE_REDUCED", "SERVICE_INCREASED") and s.get("route_family"):
            assert (s["route_family"], s.get("direction", ""), s["day_type"]) in keys


def test_render_html_injects_page_meta():
    """W3-2 追補: SNS プレビュー用の題名・説明の静的注入 (クローラは JS 非実行)。"""
    template = ('<title>__GTFS_SEMDIFF_TITLE__</title>'
                '<meta content="__GTFS_SEMDIFF_DESC__">'
                '<s>__GTFS_SEMDIFF_DATA__</s>')
    bundle = {"meta": {
        "agency_names": ["永井バス"],
        "feed": {"org_id": "nagai-unyu", "feed_id": "Nagaibus",
                 "old_period": ["2025-04-01", "2025-09-30"],
                 "new_period": ["2025-10-01", "2026-03-31"]},
    }}
    html = render_html(bundle, template)
    assert "<title>永井バス のダイヤ改正 意味的差分レポート (2025-04-01 → 2025-10-01)</title>" in html
    assert "__GTFS_SEMDIFF_DESC__" not in html
    # 欠損時のフォールバック (アップロード等でメタが無い場合)
    html2 = render_html({"meta": {}}, template)
    assert "<title>GTFS 比較レポート</title>" in html2


def test_render_html_embeds_data():
    template = '<html><script id="d" type="application/json">__GTFS_SEMDIFF_DATA__</script></html>'
    html = render_html({"a": "</script>攻撃", "b": 1}, template)
    assert "__GTFS_SEMDIFF_DATA__" not in html
    assert "<\\/script>" in html  # script 終了タグのエスケープ


def test_cli_html_output(tmp_path):
    old_zip = make_gtfs_zip(tmp_path, name="old.zip")
    new_zip = make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip")
    out = tmp_path / "report.html"
    result = CliRunner().invoke(
        main, ["compare", str(old_zip), str(new_zip), "--html", str(out)]
    )
    assert result.exit_code == 0, result.output
    html = out.read_text(encoding="utf-8")
    assert "__GTFS_SEMDIFF_DATA__" not in html
    assert '"rawdiff_total": 9' in html or '"rawdiff_total":9' in html
    assert "<script" in html  # ビューア JS 同梱
    _ = MINIMAL_FEED


def test_special_day_services(tmp_path, config):
    # M10: 年末年始型 (置き換え) と運行日ゼロ (inactive) の内訳が第1部に出る
    files = dict(MINIMAL_FEED)
    files["calendar.txt"] = (
        MINIMAL_FEED["calendar.txt"]
        + "NY,0,0,0,0,0,0,0,20260401,20270331\n"
        + "DORMANT,0,0,0,0,0,0,0,20260401,20270331\n"
    )
    files["calendar_dates.txt"] = (
        "service_id,date,exception_type\n"
        "NY,20261230,1\nNY,20261231,1\nNY,20270102,1\n"
        "WD,20261230,2\nWD,20261231,2\nWD,20270102,2\n"
    )
    files["trips.txt"] = MINIMAL_FEED["trips.txt"] + "R1,NY,T5\nR1,DORMANT,T6\n"
    files["stop_times.txt"] = MINIMAL_FEED["stop_times.txt"] + (
        "T5,10:00:00,10:00:00,S1,1\nT5,10:05:00,10:05:00,S2,2\nT5,10:10:00,10:10:00,S3,3\n"
        "T6,11:00:00,11:00:00,S1,1\nT6,11:05:00,11:05:00,S2,2\nT6,11:10:00,11:10:00,S3,3\n"
    )
    old = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    specials = bundle["presentation"]["feed_overview"]["special_days"]["new"]
    by_id = {s["service_id"]: s for s in specials}
    assert by_id["NY"]["day_type"] == "irregular"
    assert by_id["NY"]["dates"] == 3
    assert (by_id["NY"]["first_date"], by_id["NY"]["last_date"]) == ("20261230", "20270102")
    assert by_id["NY"]["replaces_regular"] is True  # WD が同日を運休 → 置き換え型
    assert by_id["DORMANT"]["day_type"] == "inactive"
    assert by_id["DORMANT"]["replaces_regular"] is False


def test_bundle_special_days_flag_based_holiday_service(tmp_path, config):
    """SD3: フラグ+大量削除型の特定日 (PRT 型) は実効日集合で日付が出る。"""
    files = {}
    files["calendar.txt"] = MINIMAL_FEED["calendar.txt"] + (
        "HOL,0,0,0,0,0,1,0,20260628,20261024\n"
    )
    # 通常土曜16回を削除し 7/4 だけ運行 (独立記念日型)
    sats = ["20260711", "20260718", "20260725", "20260801", "20260808",
            "20260815", "20260822", "20260829", "20260905", "20260912",
            "20260919", "20260926", "20261003", "20261010", "20261017", "20261024"]
    files["calendar_dates.txt"] = (
        "service_id,date,exception_type\n"
        + "".join(f"HOL,{d},2\n" for d in sats)
        + "HOL,20260704,1\n"
    )
    files["trips.txt"] = MINIMAL_FEED["trips.txt"] + "R1,HOL,T7\n"
    files["stop_times.txt"] = MINIMAL_FEED["stop_times.txt"] + (
        "T7,12:00:00,12:00:00,S1,1\nT7,12:05:00,12:05:00,S2,2\nT7,12:10:00,12:10:00,S3,3\n"
    )
    old = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    specials = bundle["presentation"]["feed_overview"]["special_days"]["new"]
    by_id = {s["service_id"]: s for s in specials}
    assert by_id["HOL"]["day_type"] == "irregular"  # SD1 の密度判定
    # SD3 (改): 第1部は日数+期間のみ (日付列挙は撤去)。実効日ベースで 7/4 の1日
    assert by_id["HOL"]["dates"] == 1
    assert by_id["HOL"]["first_date"] == "20260704"
    # 単一世代比較なので比較スコープは付かない
    assert bundle["presentation"]["feed_overview"]["comparison_scope"] is None
    # SD4 (改): 運行日の要点 (文字要約)。同一フィード同士なので変わる日ゼロ
    note = bundle["presentation"]["feed_overview"]["service_days_note"]
    assert note["overlap"] is not None
    assert note["changed"]["count"] == 0
    # このフィクスチャは平日 (WD) + HOL (7/4 のみ) しか無いので、
    # 土日 (窓内 104日) のうち HOL が走る 7/4 を除く 103 日が「運行のない日」
    assert note["no_service"]["new"]["count"] == 103


def test_feed_day_types_match_route_pages(tmp_path, config):
    """PI-1: 第1部の曜日区分別便数 = 第3部曜日タブの基底ラベル別合計。

    双子世界 (同内容・別日付の2 service) では生カウント (のべ) と表示便数が
    乖離する (PRT の 38→76 問題 — ui_quality.md A1)。第1部は表示便数を使う。"""
    from gtfs_semantic_diff.report.presentation import base_day

    files = {}
    files["calendar.txt"] = MINIMAL_FEED["calendar.txt"] + (
        "SP1,0,0,0,0,0,0,0,20260401,20270331\n"
        "SP2,0,0,0,0,0,0,0,20260401,20270331\n"
    )
    files["calendar_dates.txt"] = (
        "service_id,date,exception_type\n"
        "SP1,20260704,1\nSP2,20260907,1\n"
    )
    # SP1/SP2 は同内容 (双子世界 → 1パターンに束なる)
    files["trips.txt"] = MINIMAL_FEED["trips.txt"] + "R1,SP1,T7\nR1,SP2,T8\n"
    files["stop_times.txt"] = MINIMAL_FEED["stop_times.txt"] + (
        "T7,12:00:00,12:00:00,S1,1\nT7,12:05:00,12:05:00,S2,2\nT7,12:10:00,12:10:00,S3,3\n"
        "T8,12:00:00,12:00:00,S1,1\nT8,12:05:00,12:05:00,S2,2\nT8,12:10:00,12:10:00,S3,3\n"
    )
    old = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    day_types = bundle["presentation"]["feed_overview"]["day_types"]
    by_day = {d["day_type"]: d for d in day_types}
    # 特定日はのべ2便 (T7+T8) だが表示便数は1日あたり1便
    assert by_day["irregular"]["old"] == by_day["irregular"]["new"] == 1
    # 不変条件: 第1部 = 第3部の基底ラベル別合計 (全区分)
    sums: dict[str, list[int]] = {}
    for p in bundle["presentation"]["route_pages"]:
        for d in p["day_totals"]:
            b = sums.setdefault(base_day(d["day_type"]), [0, 0])
            b[0] += d["old"]
            b[1] += d["new"]
    assert {d["day_type"]: [d["old"], d["new"]] for d in day_types} == sums
    # 表示整合セルフチェック (S3): 違反ゼロ
    assert bundle["presentation"]["self_check"] == []


def test_special_dates_runs_server_side(tmp_path, config):
    """PI-3 (A4): special_dates はサーバー側で全日付からラン圧縮する。

    30日 cap 後にクライアントで圧縮すると「3/1〜3/30 ほか(全245日)」型の
    誤誘導になる (しんぐうの実例)。runs は cap 前の全日付を代表する。"""
    files = {}
    files["calendar.txt"] = MINIMAL_FEED["calendar.txt"] + (
        "SP,0,0,0,0,0,0,0,20260401,20270331\n"
    )
    # 3週間運行 / 3週間休止 × 4 = 84日 (cap 30 超・4ラン)。連続70日にしないのは
    # dow 検出 (day_types.md §4) で daily になり特定日でなくなるため —
    # 曜日被覆 0.5 のブロック運行は特定日のまま
    import datetime

    dates = [
        (datetime.date(2026, 4, 1) + datetime.timedelta(days=b * 42 + i)
         ).strftime("%Y%m%d")
        for b in range(4)
        for i in range(21)
    ]
    files["calendar_dates.txt"] = (
        "service_id,date,exception_type\n"
        + "".join(f"SP,{d},1\n" for d in dates)
    )
    files["trips.txt"] = MINIMAL_FEED["trips.txt"] + "R1,SP,T7\n"
    files["stop_times.txt"] = MINIMAL_FEED["stop_times.txt"] + (
        "T7,12:00:00,12:00:00,S1,1\nT7,12:05:00,12:05:00,S2,2\nT7,12:10:00,12:10:00,S3,3\n"
    )
    old = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="o.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=files, name="n.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    page = next(
        p for p in bundle["presentation"]["route_pages"] if "special_dates" in p
    )
    sd = page["special_dates"]
    assert sd["new_total"] == 84
    assert len(sd["new"]) == 30  # 互換のための cap 済みリスト
    # runs は cap 前の全84日を4本のランで代表する (cap 後圧縮なら 30 日で切れる)
    assert sd["runs_new"] == [
        ["20260401", "20260421"], ["20260513", "20260602"],
        ["20260624", "20260714"], ["20260805", "20260825"],
    ]
    assert sd["runs_new_more"] == 0


def test_date_runs_year_split():
    """PI-3: 連続日は月を跨いで繋げ、年境 (12/31|1/1) のみ分割する。"""
    from gtfs_semantic_diff.report.presentation import date_runs_year_split

    runs, more = date_runs_year_split(
        ["20261229", "20261230", "20261231", "20270101", "20270102"], 8
    )
    assert runs == [["20261229", "20261231"], ["20270101", "20270102"]]
    assert more == 0
    # 月跨ぎは繋げる
    runs, more = date_runs_year_split(["20260331", "20260401"], 8)
    assert runs == [["20260331", "20260401"]]

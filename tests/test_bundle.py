"""report/bundle.py と CLI --html の単体テスト。"""

import json

from click.testing import CliRunner

from gtfs_semantic_diff.cli import main
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.report.bundle import build_bundle, render_html

from .conftest import MINIMAL_FEED, make_gtfs_zip
from .test_diff0 import NEW_FILES


def _bundle(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    return build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)


def test_bundle_structure(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    assert set(bundle) == {
        "events", "rawdiffs", "presentation", "geometry", "timetables", "catalog", "meta",
    }
    # JSON 直列化可能
    payload = json.dumps(bundle, ensure_ascii=False)
    assert "表町一丁目" in payload

    # 全イベントの evidence が rawdiffs で解決できる (クリック→生値の構造保証)
    ids = {d["rawdiff_id"] for d in bundle["rawdiffs"]}
    for e in bundle["events"]["events"]:
        assert set(e["evidence"]) <= ids
        assert e["display_name_ja"] and e["display_name_en"]

    # カタログは全41タイプ ja/en
    assert len(bundle["catalog"]) == 41
    assert bundle["catalog"]["SERVICE_REDUCED"]["en"] == "Service reduced"

    # レポート表題用の事業者名 (agency.txt 由来)
    assert bundle["meta"]["agency_names"] == ["テストバス"]


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

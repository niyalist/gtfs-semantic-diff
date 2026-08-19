"""AI 向け digest (RD4a) のテスト。

数値一致不変条件 (docs/design/ai_interface.md §2): digest の便数・件数は
presentation / accounting の値と一致する (再集計しない)。
"""

import json

from click.testing import CliRunner

from gtfs_semantic_diff.cli import main
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.report.bundle import build_bundle
from gtfs_semantic_diff.report.digest import (
    build_digest,
    build_route_digest,
    render_digest_md,
    render_route_digest_md,
)

from .conftest import make_gtfs_zip
from .test_diff0 import NEW_FILES


def _bundle(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config)
    return build_bundle(
        old, new, config, event_set, rawdiffs, identity, trip_delta, core=True)


def test_digest_numeric_invariants(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    d = build_digest(bundle)

    # 説明台帳はそのまま (再集計しない)
    assert d["totals"]["accounting"] == bundle["events"]["accounting"]
    # イベント種別件数の合計 = イベント総数
    assert sum(r["count"] for r in d["events_by_type"]) == len(
        bundle["events"]["events"])
    # 便数 (曜日別) は feed_overview.day_types と同一 (PI-1 の値を透過)
    assert d["totals"]["trips_by_day"] == \
        bundle["presentation"]["feed_overview"]["day_types"]
    # 路線ページ数の整合
    pages = bundle["presentation"]["route_pages"]
    assert d["totals"]["pages"] == len(pages)
    assert d["totals"]["pages_changed"] + d["routes_unchanged"] == len(pages)
    # L0 に ID を含めない (trip_id / stop_id / cluster_id キーが現れない)
    text = json.dumps(d["routes"], ensure_ascii=False) + json.dumps(
        d["stop_changes"], ensure_ascii=False)
    assert "trip_id" not in text and "cluster_id" not in text


def test_digest_md_structure(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    d = build_digest(bundle)
    md = render_digest_md(d)
    for heading in ("# 差分ダイジェスト", "## 1. 比較の概要", "## 2. 全体集計",
                    "## 3. イベント種別", "## 4. 停留所の変化",
                    "## 5. 路線別の変化", "## 6. 路線に紐付かない変化",
                    "## 7. 検証 (説明台帳)"):
        assert heading in md, heading
    # 説明台帳の数値が本文に出る
    acc = bundle["events"]["events"] and bundle["events"]["accounting"]
    assert f"explained_ratio {acc['explained_ratio']:.4f}" in md

    # routes_max で切ると省略が明示される
    if d["routes"]:
        md_cut = render_digest_md(d, routes_max=0)
        assert "全量は JSON 版" in md_cut


def test_route_digest(tmp_path, config):
    bundle = _bundle(tmp_path, config)
    d0 = build_digest(bundle)
    assert d0["routes"], "合成フィードに変化ページがある前提"
    name = d0["routes"][0]["name"]
    d1 = build_route_digest(bundle, name)
    assert d1["scope"] == "route" and d1["route_group"] == name

    # 便の保存則: バケット毎の 変化+無変化+ID変更 = ④の列数
    page = next(p for p in bundle["presentation"]["route_pages"]
                if p["route_group"] == name)
    for b, t in zip(d1["timetable"], page["timetables"]):
        assert len(b["changed"]) + b["unchanged"] + b["id_changed"] == \
            len(t["columns"])

    md = render_route_digest_md(d1)
    assert f"# 路線ダイジェスト: {name}" in md
    assert "## 便の変化" in md

    # 存在しない路線は候補一覧付きのエラー
    try:
        build_route_digest(bundle, "存在しない路線")
        raise AssertionError("KeyError expected")
    except KeyError as e:
        assert "available" in str(e)


def test_cli_digest_outputs(tmp_path):
    old = make_gtfs_zip(tmp_path, name="old.zip")
    new = make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip")
    md_out = tmp_path / "digest.md"
    json_out = tmp_path / "digest.json"
    runner = CliRunner()
    res = runner.invoke(main, [
        "compare", str(old), str(new),
        "--digest", str(md_out), "--digest-json", str(json_out),
    ])
    assert res.exit_code == 0, res.output
    assert "# 差分ダイジェスト" in md_out.read_text(encoding="utf-8")
    d = json.loads(json_out.read_text(encoding="utf-8"))
    assert d["digest_schema"] == 1 and d["scope"] == "feed"

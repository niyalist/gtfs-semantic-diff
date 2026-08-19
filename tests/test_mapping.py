"""ID 対応表 (mapping.json、IM1) のテスト。

原則の機械検査: N:M を潰さない (old/new とも配列)・relation 語彙・
trips が TripDelta と件数一致・改称が対応として現れる。
"""

import json

from click.testing import CliRunner

from gtfs_semantic_diff.cli import main
from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
from gtfs_semantic_diff.load import load_snapshot
from gtfs_semantic_diff.report.mapping import build_mapping

from .conftest import make_gtfs_zip
from .test_diff0 import NEW_FILES

STOP_RELATIONS = {"continued", "renamed", "added", "removed"}
ROUTE_RELATIONS = {"continued", "renamed", "merged", "split", "restructured",
                   "added", "removed"}
TRIP_RELATIONS = {"exact", "id_churn", "modified", "added", "removed"}


def _mapping(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    event_set, _raw, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config)
    return build_mapping(identity, trip_delta, event_set), trip_delta


def test_mapping_invariants(tmp_path, config):
    mp, delta = _mapping(tmp_path, config)
    assert mp["mapping_schema"] == 1

    for s in mp["stops"]:
        assert s["relation"] in STOP_RELATIONS
        for side in ("old", "new"):
            if side in s:
                assert isinstance(s[side]["stop_ids"], list)
        if s["relation"] in ("continued", "renamed"):
            assert "old" in s and "new" in s and "confidence" in s
    for r in mp["routes"]:
        assert r["relation"] in ROUTE_RELATIONS
        assert isinstance(r.get("old", []), list)  # N:M は常に配列
        assert isinstance(r.get("new", []), list)
        for side in r.get("old", []) + r.get("new", []):
            assert isinstance(side["route_ids"], list)
    for t in mp["trips"]:
        assert t["relation"] in TRIP_RELATIONS

    # trips は TripDelta と件数一致 (保存則)
    expected = (len(delta.exact_pairs) + len(delta.modified)
                + len(delta.removed) + len(delta.added))
    assert len(mp["trips"]) == expected
    assert mp["counts"]["trips"] == expected


def test_mapping_rename_visible(tmp_path, config):
    # 市役所前 → 表町一丁目 の改称が「同一クラスタの対応+renamed」として出る
    mp, _ = _mapping(tmp_path, config)
    ren = [s for s in mp["stops"] if s["relation"] == "renamed"]
    assert any(s["old"]["name"] == "市役所前" and s["new"]["name"] == "表町一丁目"
               for s in ren)
    # 対応の両側に GTFS stop_id が入っている (経年結合の実キー)
    s = next(s for s in ren if s["old"]["name"] == "市役所前")
    assert s["old"]["stop_ids"] and s["new"]["stop_ids"]
    # 説明台帳への入口 (関連イベント)
    assert s.get("events")


def test_cli_mapping_and_routes_digest(tmp_path):
    old = make_gtfs_zip(tmp_path, name="old.zip")
    new = make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip")
    mp_out = tmp_path / "mapping.json"
    rt_out = tmp_path / "routes.json"
    res = CliRunner().invoke(main, [
        "compare", str(old), str(new),
        "--mapping", str(mp_out), "--digest-routes", str(rt_out),
    ])
    assert res.exit_code == 0, res.output
    mp = json.loads(mp_out.read_text(encoding="utf-8"))
    assert mp["mapping_schema"] == 1 and mp["stops"]
    rt = json.loads(rt_out.read_text(encoding="utf-8"))
    assert rt["scope"] == "routes" and rt["routes"]
    # 各路線 L1 に時間帯別本数と route_id 軽注記が入る
    for detail in rt["routes"].values():
        assert "time_bands" in detail
        assert "route_ids" in detail
        assert set(detail["route_ids"]) == {"old", "new"}

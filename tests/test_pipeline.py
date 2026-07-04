"""events/pipeline.py と CLI compare の結合テスト。"""

import json

from click.testing import CliRunner

from gtfs_semdiff.cli import main
from gtfs_semdiff.events import compare_snapshots
from gtfs_semdiff.load import load_snapshot

from .conftest import make_gtfs_zip
from .test_diff0 import NEW_FILES


def test_compare_snapshots_m1_all_unexplained(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    event_set, rawdiffs = compare_snapshots(old, new, config)

    acc = event_set.accounting
    assert acc.rawdiff_total == len(rawdiffs) == 9
    assert acc.explained == 0
    assert acc.explained_ratio == 0.0
    assert acc.residual_breakdown_by_file == rawdiffs.count_by_file()

    assert all(e.type == "UNEXPLAINED_RESIDUAL" for e in event_set.events)
    # 説明会計: 全 RawDiff がいずれかのイベントの evidence に載る
    covered = {rid for e in event_set.events for rid in e.evidence}
    assert covered == set(rawdiffs.by_id().keys())

    d = event_set.to_dict()
    assert d["schema_version"] == "0.2"
    assert d["accounting"]["explained_ratio"] == 0.0
    assert d["config_snapshot"] == config.raw
    json.dumps(d, ensure_ascii=False)  # JSON 直列化可能


def test_cli_compare_local_zips(tmp_path):
    old_zip = make_gtfs_zip(tmp_path, name="old.zip")
    new_zip = make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip")
    out_json = tmp_path / "events.json"
    raw_json = tmp_path / "rawdiffs.json"

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(old_zip),
            str(new_zip),
            "-o",
            str(out_json),
            "--rawdiffs",
            str(raw_json),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "explained_ratio" in result.output

    events = json.loads(out_json.read_text(encoding="utf-8"))
    assert events["schema_version"] == "0.2"
    assert events["accounting"]["explained_ratio"] == 0.0
    assert events["accounting"]["rawdiff_total"] == 9

    raw = json.loads(raw_json.read_text(encoding="utf-8"))
    assert len(raw["rawdiffs"]) == 9


def test_cli_compare_requires_input(tmp_path):
    result = CliRunner().invoke(main, ["compare"])
    assert result.exit_code != 0
    assert "入力" in result.output

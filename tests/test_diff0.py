"""diff0/engine.py の単体テスト (合成 GTFS 2世代)。"""

import pytest

from gtfs_semantic_diff.diff0 import enumerate_rawdiffs
from gtfs_semantic_diff.load import load_snapshot

from .conftest import make_gtfs_zip

# 新世代: MINIMAL_FEED に対して
# - stops: S2 改称 (field_changed x1), S4 追加 (row_added x1)
# - trips: T2 削除 (row_removed x1), trip_headsign カラム追加 (column_added x1)
# - stop_times: T2 の3行削除 (row_removed x3), T1 の S3 発時刻変更 (field_changed x1)
# - feed_info.txt 追加 (file_added x1)
NEW_FILES = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,駅前,36.0000,139.0000\n"
        "S2,表町一丁目,36.0100,139.0100\n"
        "S3,病院前,36.0200,139.0200\n"
        "S4,新設団地,36.0300,139.0300\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign\n"
        "R1,WD,T1,病院前行\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T1,08:05:00,08:05:00,S2,2\n"
        "T1,08:10:00,08:12:00,S3,3\n"
    ),
    "feed_info.txt": (
        "feed_publisher_name,feed_publisher_url,feed_lang\n"
        "テストバス,https://example.com,ja\n"
    ),
}


@pytest.fixture
def snapshots(tmp_path, config):
    old = load_snapshot(make_gtfs_zip(tmp_path, name="old.zip"), config=config)
    new = load_snapshot(make_gtfs_zip(tmp_path, files=NEW_FILES, name="new.zip"), config=config)
    return old, new


def test_expected_counts_by_file(snapshots):
    old, new = snapshots
    diffs = enumerate_rawdiffs(old, new)
    assert diffs.count_by_file() == {
        "feed_info.txt": 1,  # file_added
        "stops.txt": 2,  # S2 改称 + S4 追加
        "trips.txt": 2,  # カラム追加 + T2 削除
        "stop_times.txt": 4,  # T2 の3行削除 + 時刻変更1
    }


def test_diff_details(snapshots):
    old, new = snapshots
    by_kind = {}
    for d in enumerate_rawdiffs(old, new).diffs:
        by_kind.setdefault((d.file, d.kind), []).append(d)

    renamed = by_kind[("stops.txt", "field_changed")]
    assert len(renamed) == 1
    assert renamed[0].key == ("S2",)
    assert renamed[0].column == "stop_name"
    assert (renamed[0].old_value, renamed[0].new_value) == ("市役所前", "表町一丁目")

    assert by_kind[("stops.txt", "row_added")][0].key == ("S4",)
    assert by_kind[("trips.txt", "column_added")][0].column == "trip_headsign"
    assert by_kind[("trips.txt", "row_removed")][0].key == ("T2",)
    assert by_kind[("feed_info.txt", "file_added")][0].key == ()

    time_change = by_kind[("stop_times.txt", "field_changed")]
    assert len(time_change) == 1
    assert time_change[0].key == ("T1", "3")
    assert time_change[0].column == "departure_time"

    removed_keys = {d.key for d in by_kind[("stop_times.txt", "row_removed")]}
    assert removed_keys == {("T2", "1"), ("T2", "2"), ("T2", "3")}


def test_ids_are_stable_and_sequential(snapshots):
    old, new = snapshots
    first = [d.to_dict() for d in enumerate_rawdiffs(old, new).diffs]
    second = [d.to_dict() for d in enumerate_rawdiffs(old, new).diffs]
    assert first == second  # 同一入力 → 同一 ID・同一順序
    assert [d["rawdiff_id"] for d in first] == [
        f"rawdiff_{i:06d}" for i in range(1, len(first) + 1)
    ]


def test_identical_snapshots_produce_no_diffs(tmp_path, config):
    snap_a = load_snapshot(make_gtfs_zip(tmp_path, name="a.zip"), config=config)
    snap_b = load_snapshot(make_gtfs_zip(tmp_path, name="b.zip"), config=config)
    assert len(enumerate_rawdiffs(snap_a, snap_b)) == 0


def test_file_removed(tmp_path, config):
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files={"extra.txt": "id,val\nX1,1\n"}, name="old.zip"),
        config=config,
    )
    new = load_snapshot(make_gtfs_zip(tmp_path, name="new.zip"), config=config)
    diffs = enumerate_rawdiffs(old, new)
    assert [(d.file, d.kind) for d in diffs.diffs] == [("extra.txt", "file_removed")]


def test_unknown_file_uses_hash_matching(tmp_path, config):
    # 主キー未定義ファイルの行変更は 削除+追加 のペアになる
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files={"custom.txt": "colA,colB\nx,1\ny,2\n"}, name="old.zip"),
        config=config,
    )
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files={"custom.txt": "colA,colB\nx,1\ny,3\n"}, name="new.zip"),
        config=config,
    )
    diffs = [d for d in enumerate_rawdiffs(old, new).diffs if d.file == "custom.txt"]
    assert sorted(d.kind for d in diffs) == ["row_added", "row_removed"]
    removed = next(d for d in diffs if d.kind == "row_removed")
    added = next(d for d in diffs if d.kind == "row_added")
    assert removed.old_value == "y,2"
    assert added.new_value == "y,3"


def test_duplicate_key_falls_back_to_hash(tmp_path, config):
    # stop_id 重複 (壊れたデータ) でも例外にせずハッシュ突合で列挙する
    dup_stops = (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,駅前,36.0,139.0\n"
        "S1,駅前(重複),36.0,139.0\n"
        "S2,市役所前,36.01,139.01\n"
        "S3,病院前,36.02,139.02\n"
    )
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files={"stops.txt": dup_stops}, name="old.zip"), config=config
    )
    new = load_snapshot(make_gtfs_zip(tmp_path, name="new.zip"), config=config)
    diffs = [d for d in enumerate_rawdiffs(old, new).diffs if d.file == "stops.txt"]
    # 重複2行 + 座標表記差 (36.0 vs 36.0000 等) → 全行が削除+追加として現れる
    assert all(d.kind in ("row_added", "row_removed") for d in diffs)
    assert any(d.old_value and "駅前(重複)" in d.old_value for d in diffs)


# --- 行差分の集約 (bulk、W3 後の鹿沼 fare_rules 200万行対策) ---

def _config_with_threshold(config, n):
    from gtfs_semantic_diff.config import Config

    raw = dict(config.raw)
    raw["diff0"] = {"bulk_row_threshold": n}
    return Config(raw=raw, source_path=config.source_path)


FARE_RULES_OLD = {
    "fare_rules.txt": (
        "fare_id,route_id,origin_id,destination_id\n"
        + "".join(f"F{i},R1,Z{i},Z{i + 1}\n" for i in range(5))
    ),
}
FARE_RULES_NEW = {
    "fare_rules.txt": "fare_id,route_id,origin_id,destination_id\nF0,R1,Z0,Z1\n",
}


def test_bulk_aggregates_keyed_rows(tmp_path, config):
    """閾値超過の非コアファイルは行列挙せず、行数を保持した集約1件になる。"""
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_OLD, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_NEW, name="n.zip"), config=config)
    diffs = [d for d in enumerate_rawdiffs(
        old, new, _config_with_threshold(config, 3)).diffs
        if d.file == "fare_rules.txt"]
    assert [d.kind for d in diffs] == ["rows_removed_bulk"]
    assert diffs[0].old_value == "4"  # F1〜F4 の4行 (台帳上は1件、行数は値に保持)


def test_bulk_not_applied_under_threshold(tmp_path, config):
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_OLD, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_NEW, name="n.zip"), config=config)
    diffs = [d for d in enumerate_rawdiffs(
        old, new, _config_with_threshold(config, 100)).diffs
        if d.file == "fare_rules.txt"]
    assert [d.kind for d in diffs] == ["row_removed"] * 4  # 従来どおりの全列挙


def test_bulk_never_applies_to_row_evidence_tables(tmp_path, config):
    """stop_times 等のコアファイルは検出 evidence に行粒度が必要なため集約しない。"""
    old = load_snapshot(make_gtfs_zip(tmp_path, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=NEW_FILES, name="n.zip"), config=config)
    diffs = enumerate_rawdiffs(old, new, _config_with_threshold(config, 1))
    st = [d.kind for d in diffs.diffs if d.file == "stop_times.txt"]
    assert "rows_removed_bulk" not in st and st.count("row_removed") == 3


def test_bulk_changed_rows_keyed(tmp_path, config):
    """キー突合で「変更行」が閾値を超えた場合は rows_changed_bulk に集約。"""
    old_files = {
        "fare_attributes.txt": (
            "fare_id,price,currency_type\n"
            + "".join(f"F{i},{100 + i},JPY\n" for i in range(4))
        ),
    }
    new_files = {
        "fare_attributes.txt": (
            "fare_id,price,currency_type\n"
            + "".join(f"F{i},{200 + i},JPY\n" for i in range(4))
        ),
    }
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=old_files, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=new_files, name="n.zip"), config=config)
    bulk = [d for d in enumerate_rawdiffs(
        old, new, _config_with_threshold(config, 3)).diffs
        if d.file == "fare_attributes.txt"]
    assert [d.kind for d in bulk] == ["rows_changed_bulk"]
    assert bulk[0].old_value == "4"
    # 閾値内なら従来どおりセル単位
    exact = [d for d in enumerate_rawdiffs(
        old, new, _config_with_threshold(config, 100)).diffs
        if d.file == "fare_attributes.txt"]
    assert [d.kind for d in exact] == ["field_changed"] * 4
    assert {(d.key[0], d.old_value, d.new_value) for d in exact} == {
        (f"F{i}", str(100 + i), str(200 + i)) for i in range(4)
    }


def test_bulk_hashed_fallback(tmp_path, config):
    """主キー未定義ファイル (ハッシュ突合) でも閾値超過は集約される。"""
    old_files = {"pass_rules.txt": "a,b\n" + "".join(f"x{i},y\n" for i in range(5))}
    new_files = {"pass_rules.txt": "a,b\nx0,y\n"}
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=old_files, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=new_files, name="n.zip"), config=config)
    diffs = [d for d in enumerate_rawdiffs(
        old, new, _config_with_threshold(config, 3)).diffs
        if d.file == "pass_rules.txt"]
    assert [d.kind for d in diffs] == ["rows_removed_bulk"]
    assert diffs[0].old_value == "4"


def test_bulk_diffs_are_explained_by_fare_rule(tmp_path, config):
    """集約 RawDiff も説明台帳に載り、FARE_CHANGED が行数込みで消費する。"""
    from gtfs_semantic_diff.events.pipeline import compare_snapshots

    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_OLD, name="o.zip"), config=config)
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=FARE_RULES_NEW, name="n.zip"), config=config)
    event_set, _ = compare_snapshots(old, new, _config_with_threshold(config, 3))
    assert event_set.accounting.explained_ratio == 1.0
    fare = [e for e in event_set.events if e.type == "FARE_CHANGED"]
    assert len(fare) == 1
    assert fare[0].quantification["fare_rules_diffs"] == 4  # bulk は行数で計上

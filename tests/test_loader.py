"""load/loader.py の単体テスト (合成 GTFS zip)。"""

import pytest

from gtfs_semantic_diff.load import GtfsLoadError, load_snapshot

from .conftest import make_gtfs_zip


def test_load_minimal_zip(tmp_path, config):
    snapshot = load_snapshot(make_gtfs_zip(tmp_path), config=config)
    assert snapshot.table_names() >= {"agency", "stops", "routes", "trips", "stop_times"}
    assert snapshot.row_counts()["stops"] == 3
    assert snapshot.day_types == {"WD": "weekday"}


def test_all_values_are_str_and_empty_not_nan(tmp_path, config):
    zip_path = make_gtfs_zip(
        tmp_path,
        files={
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon,stop_desc\n"
                "S1,駅前,36.0,139.0,\n"
                "S2,市役所前,36.01,139.01,説明あり\n"
                "S3,病院前,36.02,139.02,\n"
            )
        },
    )
    stops = load_snapshot(zip_path, config=config).table("stops")
    assert stops["stop_desc"].tolist() == ["", "説明あり", ""]
    # str として読む (数値化しない)
    assert stops["stop_lat"].tolist() == ["36.0", "36.01", "36.02"]
    assert all(isinstance(v, str) for v in stops["stop_lat"])


def test_unknown_extra_file_is_loaded(tmp_path, config):
    # L0 網羅 diff の前提: 既知リスト外のファイルも読む
    zip_path = make_gtfs_zip(
        tmp_path, files={"office_jp.txt": "office_id,office_name\nO1,本社営業所\n"}
    )
    snapshot = load_snapshot(zip_path, config=config)
    assert snapshot.has_table("office_jp")


def test_bom_and_column_whitespace(tmp_path, config):
    zip_path = make_gtfs_zip(
        tmp_path,
        files={
            "agency.txt": (
                "﻿agency_id, agency_name,agency_url,agency_timezone\n"
                "A1,テストバス,https://example.com,Asia/Tokyo\n"
            )
        },
    )
    agency = load_snapshot(zip_path, config=config).table("agency")
    assert list(agency.columns)[:2] == ["agency_id", "agency_name"]


def test_cp932_fallback(tmp_path, config):
    zip_path = make_gtfs_zip(tmp_path, encoding="cp932")
    snapshot = load_snapshot(zip_path, config=config)
    assert snapshot.table("stops")["stop_name"].tolist() == ["駅前", "市役所前", "病院前"]


def test_nested_single_directory_zip(tmp_path, config):
    zip_path = make_gtfs_zip(tmp_path, inner_dir="gtfs")
    snapshot = load_snapshot(zip_path, config=config)
    assert snapshot.row_counts()["trips"] == 2


def test_load_from_directory(tmp_path, config):
    import zipfile

    zip_path = make_gtfs_zip(tmp_path)
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    snapshot = load_snapshot(extract_dir, config=config)
    assert snapshot.row_counts()["stop_times"] == 6


def test_empty_extra_file_tolerated(tmp_path, config):
    # 実例: 米沢市営バス旧世代の result.txt (0バイト、検証ツール出力の混入)。
    # 必須外の空ファイルは 0 行テーブルとして受け入れ、比較を続行する
    zip_path = make_gtfs_zip(tmp_path, files={"result.txt": ""})
    snapshot = load_snapshot(zip_path, config=config)
    assert snapshot.has_table("result")
    assert snapshot.table("result").empty


def test_empty_required_file_raises(tmp_path, config):
    zip_path = make_gtfs_zip(tmp_path, files={"stops.txt": ""})
    with pytest.raises(GtfsLoadError, match="stops.txt が空"):
        load_snapshot(zip_path, config=config)


def test_ragged_csv_raises_clear_message(tmp_path, config):
    # 実例: 立山町旧世代の translations.txt (引用符なしカンマで列数超過)。
    # 生の pandas エラーでなく、ファイル・行・原因が分かる日本語で失敗する
    zip_path = make_gtfs_zip(tmp_path, files={
        "translations.txt": (
            "table_name,field_name,language,translation,record_id,"
            "record_sub_id,field_value\n"
            "agency,agency_name,ja-Hrkt,てすと,A1,,\n"
            "agency,agency_name,en,Test Town, Test Prefecture,A1,,\n"
        )
    })
    with pytest.raises(GtfsLoadError) as ei:
        load_snapshot(zip_path, config=config)
    msg = str(ei.value)
    assert "translations.txt" in msg
    assert "3行目" in msg and "7列" in msg and "8列" in msg
    assert "不備" in msg  # 入力データ側の問題であることの明示


def test_missing_required_file_raises(tmp_path, config):
    import zipfile

    zip_path = tmp_path / "broken.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("stops.txt", "stop_id,stop_name\nS1,駅前\n")
    with pytest.raises(GtfsLoadError, match="必須"):
        load_snapshot(zip_path, config=config)


def test_nonexistent_path_raises(tmp_path, config):
    with pytest.raises(GtfsLoadError):
        load_snapshot(tmp_path / "no_such.zip", config=config)

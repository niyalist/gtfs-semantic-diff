"""テスト共通: 合成 GTFS フィードの生成ヘルパ。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from gtfs_semantic_diff.config import Config

# 最小の妥当な GTFS (必須5ファイル + calendar)
MINIMAL_FEED: dict[str, str] = {
    "agency.txt": (
        "agency_id,agency_name,agency_url,agency_timezone\n"
        "A1,テストバス,https://example.com,Asia/Tokyo\n"
    ),
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,駅前,36.0000,139.0000\n"
        "S2,市役所前,36.0100,139.0100\n"
        "S3,病院前,36.0200,139.0200\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,A1,1,駅前線,3\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id\n"
        "R1,WD,T1\n"
        "R1,WD,T2\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T1,08:05:00,08:05:00,S2,2\n"
        "T1,08:10:00,08:10:00,S3,3\n"
        "T2,09:00:00,09:00:00,S1,1\n"
        "T2,09:05:00,09:05:00,S2,2\n"
        "T2,09:10:00,09:10:00,S3,3\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "WD,1,1,1,1,1,0,0,20260401,20270331\n"
    ),
}


def make_gtfs_zip(
    directory: Path,
    files: dict[str, str] | None = None,
    name: str = "feed.zip",
    encoding: str = "utf-8",
    inner_dir: str = "",
) -> Path:
    """合成 GTFS zip を作る。inner_dir 指定でフォルダに入れ子にする。"""
    content = dict(MINIMAL_FEED)
    if files:
        content.update(files)
    zip_path = directory / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        for filename, text in content.items():
            if text is None:
                continue
            arcname = f"{inner_dir}/{filename}" if inner_dir else filename
            zf.writestr(arcname, text.encode(encoding))
    return zip_path


@pytest.fixture
def config() -> Config:
    return Config.load()

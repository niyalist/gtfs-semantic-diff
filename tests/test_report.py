"""report/markdown.py のレンダリングテスト (JSON 消費者としての検証)。"""

import json

from gtfs_semdiff.report import render_markdown

from .test_rules import run_compare


def render_from(tmp_path, config, **kwargs) -> str:
    event_set, _ = run_compare(tmp_path, config, **kwargs)
    # 実運用と同じく JSON 経由で描画 (コアオブジェクト非依存の確認)
    data = json.loads(json.dumps(event_set.to_dict(), ensure_ascii=False))
    return render_markdown(data)


def test_report_sections_and_summary(tmp_path, config):
    from .test_rules import EXTRA_ROUTE_OLD

    md = render_from(
        tmp_path, config,
        old_files=EXTRA_ROUTE_OLD,
        new_files={"stops.txt": EXTRA_ROUTE_OLD["stops.txt"]},
    )
    assert "# ダイヤ改正 意味的差分レポート" in md
    assert "## 1. 全体サマリ" in md
    assert "**路線廃止**: 99" in md
    assert "### 主要変更 (major)" in md
    assert "## 2. 路線別詳細" in md
    assert "## 4. データ検証" in md
    assert "説明被覆率 (explained_ratio): **1.0000**" in md
    assert "未説明の残差はない" in md


def test_report_stop_chapter_and_band_table(tmp_path, config):
    from .conftest import MINIMAL_FEED

    files = {
        "stops.txt": MINIMAL_FEED["stops.txt"].replace("市役所前", "表町一丁目"),
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",  # T2 減便
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
        ),
    }
    md = render_from(tmp_path, config, new_files=files)
    # 停留所章に改称
    assert "## 3. 停留所の変更" in md
    assert "市役所前 → 表町一丁目" in md
    # 路線別章に時間帯別本数表 (9-16 帯 1→0)
    assert "時間帯別本数 (旧→新):" in md
    assert "1→0" in md
    assert "| 平日 |" in md


def test_unchanged_routes_section(tmp_path, config):
    from .test_rules import EXTRA_ROUTE_OLD

    # family「99」廃止 / family「1」は無変更 → 変更のない路線一覧に「1」が載る
    md = render_from(
        tmp_path, config,
        old_files=EXTRA_ROUTE_OLD,
        new_files={"stops.txt": EXTRA_ROUTE_OLD["stops.txt"]},
    )
    assert "変更のない路線" in md
    assert "| 1 | 1 | 2 |" in md  # 路線 1、構成系統 1、便数 2 (旧=新)
    # 変更のあった路線 (99) は一覧に入らない
    section = md.split("変更のない路線")[1]
    assert "| 99 |" not in section


def test_no_unchanged_section_when_all_routes_changed(tmp_path, config):
    from .conftest import MINIMAL_FEED

    # 唯一の路線に減便イベント → 「変更のない路線」は出ない
    md = render_from(
        tmp_path, config,
        new_files={
            "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "T1,08:00:00,08:00:00,S1,1\n"
                "T1,08:05:00,08:05:00,S2,2\n"
                "T1,08:10:00,08:10:00,S3,3\n"
            ),
        },
    )
    assert "変更のない路線" not in md
    _ = MINIMAL_FEED


def test_report_residual_listing(tmp_path, config):
    # 未知ファイルの差分は残差になる → データ検証章に全件表
    md = render_from(
        tmp_path, config,
        old_files={"custom_jp.txt": "id,val\nX,1\n"},
        new_files={"custom_jp.txt": "id,val\nX,2\n"},
    )
    assert "### 未説明の残差 (UNEXPLAINED_RESIDUAL) 全件" in md
    assert "custom_jp.txt" in md

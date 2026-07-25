"""SD5: 運行日世界 (events/day_worlds.py) の合成テスト。"""

from gtfs_semantic_diff.events.day_worlds import build_day_worlds
from gtfs_semantic_diff.load import load_snapshot

from .conftest import MINIMAL_FEED, make_gtfs_zip

CAL_HEADER = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\n"
)


def _snap(tmp_path, config, calendar, calendar_dates=None, name="w.zip"):
    files = dict(MINIMAL_FEED)
    files["calendar.txt"] = CAL_HEADER + calendar
    if calendar_dates is not None:
        files["calendar_dates.txt"] = (
            "service_id,date,exception_type\n" + calendar_dates)
    return load_snapshot(make_gtfs_zip(tmp_path, files=files, name=name),
                         config=config)


def test_single_world_per_label(tmp_path, config):
    """通常フィード: 各ラベル1世界 (退化保証の前提)。"""
    snap = _snap(tmp_path, config,
                 "WD,1,1,1,1,1,0,0,20260401,20270331\n"
                 "SA,0,0,0,0,0,1,0,20260401,20270331\n")
    w = build_day_worlds(snap)
    assert w.multi_labels == frozenset()
    assert w.world_of("WD") == "weekday#1"
    assert w.world_of("SA") == "saturday#1"


def test_same_label_overlapping_services_merge(tmp_path, config):
    """同じ平日に走る2 service は同一世界 (合算が正当なケース)。"""
    snap = _snap(tmp_path, config,
                 "WD1,1,1,1,1,1,0,0,20260401,20270331\n"
                 "WD2,1,1,1,1,1,0,0,20260401,20270331\n")
    w = build_day_worlds(snap)
    assert w.multi_labels == frozenset()
    assert w.world_of("WD1") == w.world_of("WD2") == "weekday#1"


def test_disjoint_ranges_split_worlds(tmp_path, config):
    """期間分割 (四半期・世代同居・季節) は同ラベル複数世界。初日順の連番。"""
    snap = _snap(tmp_path, config,
                 "WD_B,1,1,1,1,1,0,0,20260701,20270331\n"
                 "WD_A,1,1,1,1,1,0,0,20260401,20260630\n")
    w = build_day_worlds(snap)
    assert w.multi_labels == {"weekday"}
    assert w.world_of("WD_A") == "weekday#1"  # 初日が早い方が #1
    assert w.world_of("WD_B") == "weekday#2"
    by_id = w.by_id()
    assert by_id["weekday#1"].dates[0] == "20260401"
    assert by_id["weekday#2"].dates[-1] <= "20270331"


def test_disjoint_special_days_split(tmp_path, config):
    """PRT 型: 互いに素な特定日 service は別世界。"""
    snap = _snap(
        tmp_path, config,
        "H1,0,0,0,0,0,1,0,20260601,20261031\n"
        "H2,1,0,0,0,0,0,0,20260601,20261031\n",
        calendar_dates=(
            # H1: 土曜フラグを全削除して 7/4 (土) だけ残す
            "".join(f"H1,2026{md},2\n" for md in (
                "0606", "0613", "0620", "0627", "0711", "0718", "0725",
                "0801", "0808", "0815", "0822", "0829", "0905", "0912",
                "0919", "0926", "1003", "1010", "1017", "1024", "1031"))
            + "H2,20260907,1\n"
            + "".join(f"H2,2026{md},2\n" for md in (
                "0601", "0608", "0615", "0622", "0629", "0706", "0713",
                "0720", "0727", "0803", "0810", "0817", "0824", "0831",
                "0914", "0921", "0928", "1005", "1012", "1019", "1026"))
        ),
    )
    w = build_day_worlds(snap)
    assert snap.day_types["H1"] == "irregular"
    assert snap.day_types["H2"] == "irregular"
    assert w.multi_labels == {"irregular"}
    assert w.world_of("H1") != w.world_of("H2")
    by_id = w.by_id()
    assert by_id[w.world_of("H1")].dates == ("20260704",)
    assert by_id[w.world_of("H2")].dates == ("20260907",)


def test_overlap_via_shared_date_merges(tmp_path, config):
    """1日でも共有する service は融合する (データの主張に忠実)。"""
    snap = _snap(
        tmp_path, config,
        "A,0,0,0,0,0,1,0,20260404,20260425\n"
        "B,0,0,0,0,0,1,0,20260425,20260516\n",  # 4/25 を共有
    )
    w = build_day_worlds(snap)
    assert w.world_of("A") == w.world_of("B")
    assert w.multi_labels == frozenset()

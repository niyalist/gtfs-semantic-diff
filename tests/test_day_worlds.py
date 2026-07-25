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


def _ti(trip_id, day_type, service_id, dep="08:00:00"):
    from gtfs_semantic_diff.events.tripdelta import TripInfo
    return TripInfo(
        trip_id=trip_id, route_id="R", family="F", direction="0",
        day_type=day_type, base_seq=("A", "B"),
        times=(("", dep), (dep, "")), service_id=service_id,
    )


def _worlds(*specs):
    """specs: (day_type, world_id, services, dates)"""
    from gtfs_semantic_diff.events.day_worlds import DayWorld, DayWorlds
    ws = tuple(DayWorld(day_type=d, world_id=w, services=tuple(s),
                        dates=tuple(dt)) for d, w, s, dt in specs)
    by_service = {s: w.world_id for w in ws for s in w.services}
    labels = {}
    for w in ws:
        labels.setdefault(w.day_type, []).append(w)
    multi = frozenset(k for k, v in labels.items() if len(v) > 1)
    return DayWorlds(worlds=ws, by_service=by_service, multi_labels=multi)


def test_group_patterns_bundles_identical_worlds(tmp_path, config):
    """内容同一の世界はパターンに束なる (市川三郷の花火分割型)。"""
    from gtfs_semantic_diff.events.day_worlds import group_patterns
    w = _worlds(
        ("irregular", "irregular#1", ["S1"], ["20260704"]),
        ("irregular", "irregular#2", ["S2"], ["20260907"]),
        ("irregular", "irregular#3", ["S3"], ["20261123"]),
    )
    trips = [_ti("t1", "irregular", "S1"), _ti("t2", "irregular", "S2"),
             _ti("t3", "irregular", "S3", dep="09:00:00")]
    pats = group_patterns(trips, w)[("F", "0", "irregular")]
    assert len(pats) == 2  # 8時組 (2世界束ね) + 9時組
    assert pats[0].world_ids == ("irregular#1", "irregular#2")
    assert pats[0].dates == ("20260704", "20260907")
    assert pats[0].trips_per_day == 1


def test_match_patterns_two_signals(tmp_path, config):
    """content 一致 (日付変更) と dates 一致 (内容変更) の厳密 1:1 対応。

    PRT の「旧1日 → 新2日」は group_patterns が新側の同内容世界を
    1パターンに束ねた上での 1:1 (dates に両日が入る)。"""
    from gtfs_semantic_diff.events.day_worlds import (
        WorldPattern, match_patterns)
    p = lambda digest, dates, wids=("x",): WorldPattern(  # noqa: E731
        day_type="irregular", digest=digest, world_ids=wids,
        dates=tuple(dates), trips_per_day=1)
    old = [p("aaa", ["20250525"]), p("bbb", ["20250824"])]
    new = [p("aaa", ["20260704", "20260907"], ("w1", "w2")),
           p("ccc", ["20250824"])]
    m = match_patterns(old, new)
    assert (0, 0, "content") in m  # PRT 型: 束ねられた新パターンと 1:1
    assert (1, 1, "dates") in m    # 新庄まつり型: 日付一致・内容変化
    assert all(r[2] is not None for r in m)
    # 1:1 保証: 各 index は一度しか現れない
    olds = [r[0] for r in m if r[0] is not None]
    news = [r[1] for r in m if r[1] is not None]
    assert len(olds) == len(set(olds)) and len(news) == len(set(news))

"""events/rules/ 各ルールの合成 GTFS 単体テスト (M3 DoD 要件)。"""


from gtfs_semantic_diff.events import compare_snapshots
from gtfs_semantic_diff.load import load_snapshot

from .conftest import MINIMAL_FEED, make_gtfs_zip


def run_compare(tmp_path, config, old_files=None, new_files=None):
    old = load_snapshot(
        make_gtfs_zip(tmp_path, files=old_files, name="old.zip"), config=config
    )
    new = load_snapshot(
        make_gtfs_zip(tmp_path, files=new_files, name="new.zip"), config=config
    )
    return compare_snapshots(old, new, config)


def events_of(event_set, type_):
    return [e for e in event_set.events if e.type == type_]


def assert_fully_explained(event_set):
    assert event_set.accounting.explained_ratio == 1.0, (
        event_set.accounting.residual_breakdown_by_file
    )


# --- D群 ---


def test_stop_added_and_removed(tmp_path, config):
    old_stops = MINIMAL_FEED["stops.txt"] + "S9,旧団地,36.9000,139.9000\n"
    new_stops = MINIMAL_FEED["stops.txt"] + "S8,新団地,36.8000,139.8000\n"
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"stops.txt": old_stops},
        new_files={"stops.txt": new_stops},
    )
    removed = events_of(event_set, "STOP_REMOVED")
    added = events_of(event_set, "STOP_ADDED")
    assert [e.subject["stop_cluster"] for e in removed] == ["旧団地"]
    assert [e.subject["stop_cluster"] for e in added] == ["新団地"]
    assert_fully_explained(event_set)


def test_stop_renamed(tmp_path, config):
    new_stops = MINIMAL_FEED["stops.txt"].replace("市役所前", "表町一丁目")
    event_set, _ = run_compare(tmp_path, config, new_files={"stops.txt": new_stops})
    renamed = events_of(event_set, "STOP_RENAMED")
    assert len(renamed) == 1
    assert renamed[0].old_ref["name"] == "市役所前"
    assert renamed[0].new_ref["name"] == "表町一丁目"
    assert len(renamed[0].evidence) == 1
    assert_fully_explained(event_set)


def test_platform_changed_by_stop_times_reassignment(tmp_path, config):
    # 両世代に乗り場 S2/S2b があり、T1 の停車が S2 → S2b に付け替わる
    stops = (
        MINIMAL_FEED["stops.txt"] + "S2b,市役所前 2,36.0101,139.0101\n"
    )
    new_stop_times = MINIMAL_FEED["stop_times.txt"].replace(
        "T1,08:05:00,08:05:00,S2,2", "T1,08:05:00,08:05:00,S2b,2"
    )
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"stops.txt": stops},
        new_files={"stops.txt": stops, "stop_times.txt": new_stop_times},
    )
    changed = events_of(event_set, "PLATFORM_CHANGED")
    assert len(changed) == 1
    assert changed[0].subject["stop_cluster"] == "市役所前"
    assert_fully_explained(event_set)


# --- A群 ---

EXTRA_ROUTE_OLD = {
    "routes.txt": MINIMAL_FEED["routes.txt"] + "R9,A1,99,山線,3\n",
    "trips.txt": MINIMAL_FEED["trips.txt"] + "R9,WD,T9\n",
    "stops.txt": MINIMAL_FEED["stops.txt"] + "S9,山奥,36.5,139.5\n",
    "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
    + "T9,11:00:00,11:00:00,S1,1\nT9,11:30:00,11:30:00,S9,2\n",
}


def test_route_discontinued_consumes_trip_cascade(tmp_path, config):
    event_set, rawdiffs = run_compare(
        tmp_path, config,
        old_files=EXTRA_ROUTE_OLD,
        new_files={"stops.txt": EXTRA_ROUTE_OLD["stops.txt"]},  # 停留所は残す
    )
    disc = events_of(event_set, "ROUTE_DISCONTINUED")
    assert len(disc) == 1
    assert disc[0].subject["route_family"] == "99"
    assert disc[0].quantification["trip_count"] == 1
    # routes + trips + stop_times の行差分がすべて evidence に載っている
    cascade = {
        d.rawdiff_id
        for d in rawdiffs.diffs
        if d.file in ("routes.txt", "trips.txt", "stop_times.txt")
    }
    assert cascade <= set(disc[0].evidence)
    assert_fully_explained(event_set)


def test_route_added(tmp_path, config):
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"stops.txt": EXTRA_ROUTE_OLD["stops.txt"]},
        new_files=EXTRA_ROUTE_OLD,
    )
    added = events_of(event_set, "ROUTE_ADDED")
    assert [e.subject["route_family"] for e in added] == ["99"]
    assert_fully_explained(event_set)


def test_route_renamed_by_pattern_jaccard(tmp_path, config):
    new_routes = MINIMAL_FEED["routes.txt"].replace("R1,A1,1,", "R1,A1,100,")
    event_set, _ = run_compare(tmp_path, config, new_files={"routes.txt": new_routes})
    renamed = events_of(event_set, "ROUTE_RENAMED")
    assert len(renamed) == 1
    assert renamed[0].old_ref["name"] == "1"
    assert renamed[0].new_ref["name"] == "100"
    assert not events_of(event_set, "ROUTE_ADDED")
    assert not events_of(event_set, "ROUTE_DISCONTINUED")
    assert_fully_explained(event_set)


def test_route_renamed_with_stop_rename(tmp_path, config):
    # M9 名古屋型 (鳴.ワイ→鳴.メグ): 路線改称と停留所改称が同時に起きても、
    # 停留所クラスタ対応による翻訳で family が結ばれる (旧実装は共倒れ)
    event_set, _ = run_compare(
        tmp_path, config,
        new_files={
            "routes.txt": MINIMAL_FEED["routes.txt"].replace("R1,A1,1,", "R1,A1,100,"),
            "stops.txt": MINIMAL_FEED["stops.txt"].replace("市役所前", "表町一丁目"),
            "stop_times.txt": MINIMAL_FEED["stop_times.txt"],
        },
    )
    renamed = events_of(event_set, "ROUTE_RENAMED")
    assert len(renamed) == 1
    assert (renamed[0].old_ref["name"], renamed[0].new_ref["name"]) == ("1", "100")
    assert not events_of(event_set, "ROUTE_ADDED")
    assert not events_of(event_set, "ROUTE_DISCONTINUED")
    assert len(events_of(event_set, "STOP_RENAMED")) == 1
    assert_fully_explained(event_set)


def test_route_merged_variants(tmp_path, config):
    # M9 朝日町型: 変種 family 2つ (朝便/本便) が新世代で1 family へ統合 →
    # N:1 成分 = ROUTE_MERGED。廃止・新設にはしない
    old_files = {
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "RA,A1,［駅前線］朝便,,3\nRB,A1,［駅前線］,,3\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\nRA,WD,T1\nRB,WD,T2\n",
    }
    new_files = {
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "1,A1,A1駅前線,,3\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\n1,WD,T1\n1,WD,T2\n",
    }
    event_set, _ = run_compare(tmp_path, config, old_files=old_files, new_files=new_files)
    merged = events_of(event_set, "ROUTE_MERGED")
    assert len(merged) == 1
    assert merged[0].old_ref["names"] == ["［駅前線］", "［駅前線］朝便"]
    assert merged[0].new_ref["names"] == ["A1駅前線"]
    assert not events_of(event_set, "ROUTE_ADDED")
    assert not events_of(event_set, "ROUTE_DISCONTINUED")
    assert_fully_explained(event_set)


def test_family_link_id_bonus(tmp_path, config):
    # route_id 共有は弱い事前: Jaccard が link_min をわずかに下回っても
    # id_bonus の範囲なら受理する (3/7 ≈ 0.43、閾値 0.5 - 0.1 = 0.4)
    old_files = {
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "S1,駅前,36.0000,139.0000\nS2,市役所前,36.0100,139.0100\n"
            "S3,病院前,36.0200,139.0200\nS4,公園,36.0300,139.0300\n"
            "S5,学校,36.0400,139.0400\nS6,山道,36.5000,139.5000\n"
            "S7,川道,36.5100,139.5100\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\nT1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\nT1,08:15:00,08:15:00,S4,4\n"
            "T1,08:20:00,08:20:00,S5,5\n"
        ),
    }
    new_files = dict(old_files)
    new_files["routes.txt"] = MINIMAL_FEED["routes.txt"].replace("R1,A1,1,", "R1,A1,100,")
    new_files["stop_times.txt"] = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\nT1,08:05:00,08:05:00,S2,2\n"
        "T1,08:10:00,08:10:00,S3,3\nT1,08:15:00,08:15:00,S6,4\n"
        "T1,08:20:00,08:20:00,S7,5\n"
    )
    event_set, _ = run_compare(tmp_path, config, old_files=old_files, new_files=new_files)
    assert len(events_of(event_set, "ROUTE_RENAMED")) == 1
    assert not events_of(event_set, "ROUTE_DISCONTINUED")


def test_component_cap_demotes_to_annotation(tmp_path, config):
    # 成分の関与 group 数が上限を超えたら降格: RENAMED 系は出さず、
    # 現行どおり廃止+新設 (破滅回避、route_identity_review.md §3.3.1)
    config.raw["identity"]["route_family"]["max_component_groups"] = 1
    new_routes = MINIMAL_FEED["routes.txt"].replace("R1,A1,1,", "R1,A1,100,")
    event_set, _ = run_compare(tmp_path, config, new_files={"routes.txt": new_routes})
    assert not events_of(event_set, "ROUTE_RENAMED")
    assert len(events_of(event_set, "ROUTE_ADDED")) == 1
    assert len(events_of(event_set, "ROUTE_DISCONTINUED")) == 1
    assert_fully_explained(event_set)


def test_route_id_churn(tmp_path, config):
    # route_id だけ R1 → Q1 (名称・trip 内容同一)
    event_set, _ = run_compare(
        tmp_path, config,
        new_files={
            "routes.txt": MINIMAL_FEED["routes.txt"].replace("R1,", "Q1,"),
            "trips.txt": MINIMAL_FEED["trips.txt"].replace("R1,", "Q1,"),
        },
    )
    churn = [
        e for e in events_of(event_set, "TECHNICAL_ID_CHURN")
        if e.subject.get("entity") == "route_id"
    ]
    assert len(churn) == 1
    assert churn[0].quantification["removed_route_ids"] == ["R1"]
    assert churn[0].quantification["added_route_ids"] == ["Q1"]
    assert_fully_explained(event_set)


# --- B群 ---


def test_pattern_extended(tmp_path, config):
    files = {
        "stops.txt": MINIMAL_FEED["stops.txt"] + "S4,延伸先,36.03,139.03\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "T1,08:15:00,08:15:00,S4,4\nT2,09:15:00,09:15:00,S4,4\n",
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    extended = events_of(event_set, "PATTERN_EXTENDED")
    assert len(extended) == 1
    assert extended[0].quantification["stops"] == ["延伸先"]
    assert extended[0].quantification["end"] == "end"
    assert extended[0].quantification["trip_count"] == 2
    assert_fully_explained(event_set)


def test_pattern_truncated(tmp_path, config):
    files = {
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T2,09:00:00,09:00:00,S1,1\n"
            "T2,09:05:00,09:05:00,S2,2\n"
        )
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    truncated = events_of(event_set, "PATTERN_TRUNCATED")
    assert len(truncated) == 1
    assert truncated[0].quantification["stops"] == ["病院前"]
    assert_fully_explained(event_set)


def test_stop_inserted_and_detour(tmp_path, config):
    # T1 に1停留所挿入 → STOP_INSERTED_IN_PATTERN
    files = {
        "stops.txt": MINIMAL_FEED["stops.txt"]
        + "S5,経由地,36.005,139.005\nS6,経由地二,36.006,139.006\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:02:00,08:02:00,S5,2\n"
            "T1,08:05:00,08:05:00,S2,3\n"
            "T1,08:10:00,08:10:00,S3,4\n"
        ),
    }
    old_files = {
        "stops.txt": files["stops.txt"],
        "trips.txt": files["trips.txt"],
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
        ),
    }
    event_set, _ = run_compare(tmp_path, config, old_files=old_files, new_files=files)
    inserted = events_of(event_set, "STOP_INSERTED_IN_PATTERN")
    assert len(inserted) == 1
    assert inserted[0].quantification["stops"] == ["経由地"]
    assert_fully_explained(event_set)


def test_detour_added_consumes_time_changes_too(tmp_path, config):
    # 連続2停留所の挿入 + 下流時刻の連鎖変更 → DETOUR_ADDED が丸ごと説明
    old_files = {
        "stops.txt": MINIMAL_FEED["stops.txt"]
        + "S5,施設東,36.005,139.005\nS6,施設西,36.006,139.006\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
        ),
    }
    new_files = dict(old_files)
    new_files["stop_times.txt"] = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n"
        "T1,08:03:00,08:03:00,S5,2\n"
        "T1,08:06:00,08:06:00,S6,3\n"
        "T1,08:09:00,08:09:00,S2,4\n"
        "T1,08:14:00,08:14:00,S3,5\n"
    )
    event_set, _ = run_compare(tmp_path, config, old_files=old_files, new_files=new_files)
    detour = events_of(event_set, "DETOUR_ADDED")
    assert len(detour) == 1
    assert detour[0].quantification["stops"] == ["施設東", "施設西"]
    assert_fully_explained(event_set)  # 時刻変更の diff も evidence で説明済み


# --- C群 ---


def test_service_reduced(tmp_path, config):
    files = {
        "trips.txt": "route_id,service_id,trip_id\nR1,WD,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:05:00,08:05:00,S2,2\n"
            "T1,08:10:00,08:10:00,S3,3\n"
        ),
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    reduced = events_of(event_set, "SERVICE_REDUCED")
    assert len(reduced) == 1
    q = reduced[0].quantification
    assert (q["time_band"], q["old_count"], q["new_count"]) == ("09:00-16:00", 1, 0)
    assert_fully_explained(event_set)


def test_service_increased_in_commute_band(tmp_path, config):
    files = {
        "trips.txt": MINIMAL_FEED["trips.txt"] + "R1,WD,T3\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "T3,07:30:00,07:30:00,S1,1\nT3,07:35:00,07:35:00,S2,2\nT3,07:40:00,07:40:00,S3,3\n",
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    increased = events_of(event_set, "SERVICE_INCREASED")
    assert len(increased) == 1
    assert increased[0].quantification["time_band"] == "07:00-09:00"
    assert_fully_explained(event_set)


def test_timetable_shifted_uniform(tmp_path, config):
    # T2 の全時刻を +20 分 (同一 trip_id) → 一様シフト
    new_st = (
        MINIMAL_FEED["stop_times.txt"]
        .replace("T2,09:00:00,09:00:00", "T2,09:20:00,09:20:00")
        .replace("T2,09:05:00,09:05:00", "T2,09:25:00,09:25:00")
        .replace("T2,09:10:00,09:10:00", "T2,09:30:00,09:30:00")
    )
    event_set, _ = run_compare(tmp_path, config, new_files={"stop_times.txt": new_st})
    shifted = events_of(event_set, "TIMETABLE_SHIFTED")
    assert len(shifted) == 1
    assert shifted[0].quantification["shift_min"] == 20
    assert shifted[0].quantification["uniform"] is True
    assert_fully_explained(event_set)


def test_first_last_changed(tmp_path, config):
    # 終発 09:00 → 21:00 (band も変わる: removed+added → SERVICE イベント + FIRST_LAST)
    new_st = (
        MINIMAL_FEED["stop_times.txt"]
        .replace("T2,09:00:00,09:00:00", "T2b,21:00:00,21:00:00")
        .replace("T2,09:05:00,09:05:00", "T2b,21:05:00,21:05:00")
        .replace("T2,09:10:00,09:10:00", "T2b,21:10:00,21:10:00")
    )
    files = {
        "trips.txt": MINIMAL_FEED["trips.txt"].replace("R1,WD,T2", "R1,WD,T2b"),
        "stop_times.txt": new_st,
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    fl = events_of(event_set, "FIRST_LAST_CHANGED")
    assert len(fl) == 1
    assert fl[0].quantification["last_shift_min"] == 720.0  # 12時間繰り下げ
    assert_fully_explained(event_set)


# --- F群 / churn ---


def test_technical_trip_id_churn(tmp_path, config):
    files = {
        "trips.txt": MINIMAL_FEED["trips.txt"].replace("T1", "X1").replace("T2", "X2"),
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"].replace("T1", "X1").replace("T2", "X2"),
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    churn = [
        e for e in events_of(event_set, "TECHNICAL_ID_CHURN")
        if e.subject.get("entity") == "trip_id"
    ]
    assert len(churn) == 1
    assert churn[0].quantification["trip_pairs"] == 2
    assert not events_of(event_set, "SERVICE_REDUCED")
    assert not events_of(event_set, "SERVICE_INCREASED")
    assert_fully_explained(event_set)


def test_fare_changed(tmp_path, config):
    fare = {
        "fare_attributes.txt": "fare_id,price,currency_type,payment_method,transfers\nF100,100,JPY,0,0\n",
        "fare_rules.txt": "fare_id,route_id\nF100,R1\n",
    }
    new_fare = {
        "fare_attributes.txt": "fare_id,price,currency_type,payment_method,transfers\nF180,180,JPY,0,0\n",
        "fare_rules.txt": "fare_id,route_id\nF180,R1\n",
    }
    event_set, _ = run_compare(tmp_path, config, old_files=fare, new_files=new_fare)
    fare_events = events_of(event_set, "FARE_CHANGED")
    assert len(fare_events) == 1
    assert_fully_explained(event_set)


def test_feed_validity_changed_calendar_end_date(tmp_path, config):
    new_cal = MINIMAL_FEED["calendar.txt"].replace("20270331", "20280331")
    event_set, _ = run_compare(tmp_path, config, new_files={"calendar.txt": new_cal})
    validity = events_of(event_set, "FEED_VALIDITY_CHANGED")
    assert len(validity) == 1
    assert_fully_explained(event_set)


def test_holiday_exception_changed(tmp_path, config):
    old_cd = {"calendar_dates.txt": "service_id,date,exception_type\nWD,20260504,2\n"}
    new_cd = {"calendar_dates.txt": "service_id,date,exception_type\nWD,20260504,2\nWD,20260923,2\n"}
    event_set, _ = run_compare(tmp_path, config, old_files=old_cd, new_files=new_cd)
    holiday = events_of(event_set, "HOLIDAY_EXCEPTION_CHANGED")
    assert len(holiday) == 1
    assert holiday[0].subject["day_type"] == "weekday"
    assert_fully_explained(event_set)


def test_daytype_restructured(tmp_path, config):
    # 土曜ダイヤの新設 (day_type 集合 {weekday} → {weekday, saturday})
    files = {
        "calendar.txt": MINIMAL_FEED["calendar.txt"]
        + "SAT,0,0,0,0,0,1,0,20260401,20270331\n",
        "trips.txt": MINIMAL_FEED["trips.txt"] + "R1,SAT,T7\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "T7,10:00:00,10:00:00,S1,1\nT7,10:05:00,10:05:00,S2,2\nT7,10:10:00,10:10:00,S3,3\n",
    }
    event_set, _ = run_compare(tmp_path, config, new_files=files)
    restructured = events_of(event_set, "DAYTYPE_RESTRUCTURED")
    assert len(restructured) == 1
    assert restructured[0].new_ref["day_types"] == ["saturday", "weekday"]
    assert_fully_explained(event_set)

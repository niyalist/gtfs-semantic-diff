"""M5 で追加・詳細化したルールの合成 GTFS 単体テスト。"""

from gtfs_semdiff.events.geometry import discrete_frechet_m

from .conftest import MINIMAL_FEED
from .test_rules import assert_fully_explained, events_of, run_compare

# --- 幾何 ---


def test_discrete_frechet_basic():
    a = [(36.0, 139.0), (36.0, 139.01)]  # 東西 ~890m の線分
    assert discrete_frechet_m(a, a) == 0.0
    b = [(36.001, 139.0), (36.001, 139.01)]  # 111m 北に平行移動
    assert 100 < discrete_frechet_m(a, b) < 125


# --- SHAPE_CHANGED 詳細 ---

SHAPE_STRAIGHT = (
    "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    + "".join(f"SH1,36.0,{139.0 + i * 0.001:.4f},{i + 1}\n" for i in range(10))
)
# 中間で北に約550m 膨らむ (迂回)
SHAPE_DETOUR = (
    "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    + "".join(
        f"SH1,{36.005 if 3 <= i <= 6 else 36.0},{139.0 + i * 0.001:.4f},{i + 1}\n"
        for i in range(10)
    )
)
# 点の振り直しのみ (幾何ほぼ同一、点数変更)
SHAPE_RESAMPLED = (
    "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    + "".join(f"SH1,36.0,{139.0 + i * 0.0005:.5f},{i + 1}\n" for i in range(19))
)

TRIPS_WITH_SHAPE = "route_id,service_id,trip_id,shape_id\nR1,WD,T1,SH1\nR1,WD,T2,SH1\n"


def test_shape_changed_significant(tmp_path, config):
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"shapes.txt": SHAPE_STRAIGHT, "trips.txt": TRIPS_WITH_SHAPE},
        new_files={"shapes.txt": SHAPE_DETOUR, "trips.txt": TRIPS_WITH_SHAPE},
    )
    changed = events_of(event_set, "SHAPE_CHANGED")
    assert len(changed) == 1
    q = changed[0].quantification
    assert q["significant"] is True
    assert q["frechet_m"] > 150
    assert q["max_deviation_m"] > 150
    assert "max_deviation_at" in q
    assert changed[0].subject["route_families"] == ["1"]
    assert_fully_explained(event_set)


def test_shape_resampled_not_significant(tmp_path, config):
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"shapes.txt": SHAPE_STRAIGHT, "trips.txt": TRIPS_WITH_SHAPE},
        new_files={"shapes.txt": SHAPE_RESAMPLED, "trips.txt": TRIPS_WITH_SHAPE},
    )
    changed = events_of(event_set, "SHAPE_CHANGED")
    assert len(changed) == 1
    assert changed[0].quantification["significant"] is False
    assert changed[0].severity == "info"
    assert_fully_explained(event_set)


def test_shape_id_churn(tmp_path, config):
    # shape_id を SH1 → SH9 に張り替え (幾何同一) → TECHNICAL_ID_CHURN
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"shapes.txt": SHAPE_STRAIGHT, "trips.txt": TRIPS_WITH_SHAPE},
        new_files={
            "shapes.txt": SHAPE_STRAIGHT.replace("SH1,", "SH9,"),
            "trips.txt": TRIPS_WITH_SHAPE.replace(",SH1", ",SH9"),
        },
    )
    churn = [
        e for e in events_of(event_set, "TECHNICAL_ID_CHURN")
        if e.subject.get("entity") == "shape_id"
    ]
    assert len(churn) == 1
    assert churn[0].quantification["frechet_m"] < 150
    assert not events_of(event_set, "SHAPE_CHANGED")
    assert_fully_explained(event_set)


# --- TRAVEL_TIME_CHANGED 詳細 ---


def test_travel_time_segments(tmp_path, config):
    # T1 の S2→S3 区間だけ 5分 → 13分に (非一様変化: std > uniform_shift_max_std_sec)
    new_st = MINIMAL_FEED["stop_times.txt"].replace(
        "T1,08:10:00,08:10:00,S3,3", "T1,08:18:00,08:18:00,S3,3"
    )
    event_set, _ = run_compare(tmp_path, config, new_files={"stop_times.txt": new_st})
    tt = events_of(event_set, "TRAVEL_TIME_CHANGED")
    assert len(tt) == 1
    segments = tt[0].quantification["segments"]
    assert segments[0]["segment"] == "市役所前→病院前"
    assert segments[0]["old_median_sec"] == 300
    assert segments[0]["new_median_sec"] == 780
    assert "old_p90" in segments[0] and "new_p90" in segments[0]
    assert_fully_explained(event_set)


# --- DEMAND_RESPONSIVE_CHANGE ---


def test_demand_responsive_pickup_type(tmp_path, config):
    old_st = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
        "T1,08:00:00,08:00:00,S1,1,0\n"
        "T1,08:05:00,08:05:00,S2,2,0\n"
        "T1,08:10:00,08:10:00,S3,3,0\n"
        "T2,09:00:00,09:00:00,S1,1,0\n"
        "T2,09:05:00,09:05:00,S2,2,0\n"
        "T2,09:10:00,09:10:00,S3,3,0\n"
    )
    new_st = old_st.replace("S2,2,0", "S2,2,2")  # S2 が要電話予約に
    event_set, _ = run_compare(
        tmp_path, config,
        old_files={"stop_times.txt": old_st},
        new_files={"stop_times.txt": new_st},
    )
    demand = events_of(event_set, "DEMAND_RESPONSIVE_CHANGE")
    assert len(demand) == 1
    assert demand[0].confidence == 0.5  # 単独兆候
    assert "pickup/drop_off_type" in demand[0].quantification["signals"][0]
    assert_fully_explained(event_set)


# --- FARE_CHANGED 詳細 ---


def test_fare_changed_decomposition(tmp_path, config):
    old_fare = {
        "fare_attributes.txt": (
            "fare_id,price,currency_type,payment_method,transfers\n"
            "F100,100,JPY,0,0\nFZ,500,JPY,0,0\n"
        ),
        "fare_rules.txt": "fare_id,route_id\nF100,R1\nFZ,R1\n",
    }
    new_fare = {
        "fare_attributes.txt": (
            "fare_id,price,currency_type,payment_method,transfers\n"
            "F180,180,JPY,0,0\nFZ,520,JPY,0,0\n"
        ),
        "fare_rules.txt": "fare_id,route_id\nF180,R1\nFZ,R1\n",
    }
    event_set, _ = run_compare(tmp_path, config, old_files=old_fare, new_files=new_fare)
    fare = events_of(event_set, "FARE_CHANGED")[0]
    q = fare.quantification
    assert q["removed_fares"] == [{"fare_id": "F100", "price": "100"}]
    assert q["added_fares"] == [{"fare_id": "F180", "price": "180"}]
    assert q["price_changes"] == [{"fare_id": "FZ", "old_price": "500", "new_price": "520"}]
    assert_fully_explained(event_set)


# --- HEADSIGN_CHANGED ---


def test_headsign_changed(tmp_path, config):
    old_files = {
        "trips.txt": "route_id,service_id,trip_id,trip_headsign\nR1,WD,T1,富山駅前\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign\n"
            "T1,08:00:00,08:00:00,S1,1,富山駅前\n"
            "T1,08:05:00,08:05:00,S2,2,富山駅前\n"
            "T1,08:10:00,08:10:00,S3,3,富山駅前\n"
        ),
    }
    new_files = {
        "trips.txt": old_files["trips.txt"].replace("富山駅前", "富山駅"),
        "stop_times.txt": old_files["stop_times.txt"].replace("富山駅前", "富山駅"),
    }
    event_set, _ = run_compare(tmp_path, config, old_files=old_files, new_files=new_files)
    headsign = events_of(event_set, "HEADSIGN_CHANGED")
    assert len(headsign) == 1
    assert headsign[0].subject["route_family"] == "1"
    assert headsign[0].quantification["changed_fields"] == 4  # trip 1 + stop_times 3
    assert headsign[0].quantification["samples"] == ["富山駅前 → 富山駅"]
    assert_fully_explained(event_set)


# --- STOP_RELOCATED (リンク半径超の移設) ---


def test_stop_relocated_beyond_link_radius(tmp_path, config):
    # S3 を約550m 移設 (inter_generation_radius 300m 超)。stop_id 共有で対応づく
    new_stops = MINIMAL_FEED["stops.txt"].replace(
        "S3,病院前,36.0200,139.0200", "S3,病院前,36.0250,139.0200"
    )
    event_set, _ = run_compare(tmp_path, config, new_files={"stops.txt": new_stops})
    relocated = events_of(event_set, "STOP_RELOCATED")
    assert len(relocated) == 1
    assert relocated[0].quantification["moved_m"] > 300
    assert not events_of(event_set, "STOP_ADDED")
    assert not events_of(event_set, "STOP_REMOVED")
    assert_fully_explained(event_set)


# --- SEASONAL_SERVICE_CHANGED ---


def test_seasonal_service_disappearance(tmp_path, config):
    # 特定日運行のみの family「ぶり」が消滅 → SEASONAL_SERVICE_CHANGED
    old_files = {
        "routes.txt": MINIMAL_FEED["routes.txt"] + "RB,A1,ぶり,観光線,3\n",
        "trips.txt": MINIMAL_FEED["trips.txt"] + "RB,WINTER,TB1\n",
        "stop_times.txt": MINIMAL_FEED["stop_times.txt"]
        + "TB1,10:00:00,10:00:00,S1,1\nTB1,10:10:00,10:10:00,S3,2\n",
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "WINTER,20261205,1\nWINTER,20261206,1\nWINTER,20261212,1\nWINTER,20270110,1\n"
        ),
    }
    event_set, _ = run_compare(tmp_path, config, old_files=old_files)
    seasonal = events_of(event_set, "SEASONAL_SERVICE_CHANGED")
    assert len(seasonal) == 1
    assert seasonal[0].subject["route_family"] == "ぶり"
    assert seasonal[0].quantification["change"] == "disappeared"
    assert seasonal[0].confidence == 0.6
    assert not events_of(event_set, "ROUTE_DISCONTINUED")
    assert_fully_explained(event_set)


# --- カレンダー重なり正規化 ---


def test_holiday_exception_overlap_normalization(tmp_path, config):
    # 有効期間: 旧 2026-04-01〜2027-03-31 / 新も同一 (MINIMAL_FEED の calendar)
    # 窓内の追加日 → within_overlap にカウント
    old_cd = {"calendar_dates.txt": "service_id,date,exception_type\nWD,20260504,2\n"}
    new_cd = {"calendar_dates.txt": "service_id,date,exception_type\nWD,20260504,2\nWD,20260923,2\n"}
    event_set, _ = run_compare(tmp_path, config, old_files=old_cd, new_files=new_cd)
    holiday = events_of(event_set, "HOLIDAY_EXCEPTION_CHANGED")[0]
    q = holiday.quantification
    assert q["within_overlap"] == 1
    assert q["substantive"] is True
    assert holiday.confidence == 1.0
    assert_fully_explained(event_set)

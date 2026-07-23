"""events/windows.py (SD2 区間計算) の単体テスト。

シナリオは docs/design/service_days.md §2.2 の表と対応:
- 同居 (旧側) vs 改正後のみ → 旧世代は窓外、区間1つ
- 改正前のみ vs 同居 (新側) → 改正日で2分割
- 単一世代同士 → 区間1つ (現行挙動への退化)
"""

import datetime

import pandas as pd

from gtfs_semantic_diff.events.windows import (
    DateInterval,
    active_services,
    common_window,
    snapshot_window,
    window_intervals,
)
from gtfs_semantic_diff.model.snapshot import GtfsSnapshot, SnapshotMeta

DAY_COLS = "monday,tuesday,wednesday,thursday,friday,saturday,sunday".split(",")


def snap(calendar_rows, calendar_dates_rows=None, feed_info=None):
    """service_id → (フラグ, start, end) から GtfsSnapshot を作る。"""
    records = []
    for sid, (flags, start, end) in calendar_rows.items():
        rec = {"service_id": sid, "start_date": start, "end_date": end}
        rec.update({c: f for c, f in zip(DAY_COLS, flags)})
        records.append(rec)
    tables = {"calendar": pd.DataFrame(records, dtype=str)}
    if calendar_dates_rows:
        tables["calendar_dates"] = pd.DataFrame(
            calendar_dates_rows, columns=["service_id", "date", "exception_type"],
            dtype=str)
    if feed_info:
        tables["feed_info"] = pd.DataFrame(
            [{"feed_start_date": feed_info[0], "feed_end_date": feed_info[1]}],
            dtype=str)
    return GtfsSnapshot(meta=SnapshotMeta(source="test"), tables=tables)


def d(text):
    return datetime.datetime.strptime(text, "%Y%m%d").date()


# 桑名の実構造を模した3世代分のフィクスチャ
COEX = {  # 同居 (prev_19 相当): 旧世代 6/1〜7/10 + 新世代 7/11〜10/12
    "A_wd": ("1111100", "20260601", "20260710"),
    "A_sa": ("0000010", "20260601", "20260710"),
    "B_wd": ("1111100", "20260711", "20261012"),
    "B_sa": ("0000010", "20260711", "20261012"),
}
PRE = {  # 改正前のみ (prev_20 相当): 6/1〜10/3
    "A_wd": ("1111100", "20260601", "20261003"),
    "A_sa": ("0000010", "20260601", "20261003"),
}
POST = {  # 改正後のみ (current 相当): 7/11〜10/23
    "B_wd": ("1111100", "20260711", "20261023"),
    "B_sa": ("0000010", "20260711", "20261023"),
}


def test_snapshot_window_prefers_feed_info():
    s = snap(PRE, feed_info=("20260601", "20261003"))
    assert snapshot_window(s) == DateInterval(d("20260601"), d("20261003"))


def test_snapshot_window_falls_back_to_calendar_span():
    s = snap(COEX)
    assert snapshot_window(s) == DateInterval(d("20260601"), d("20261012"))


def test_coexistence_as_old_side_single_interval():
    # 同居 (旧側) vs 改正後のみ: 共通窓 7/11〜10/12、内部境界なし → 区間1つ。
    # 旧世代 service は区間に現れない (窓外)
    old, new = snap(COEX), snap(POST)
    window, intervals = window_intervals(old, new)
    assert window == DateInterval(d("20260711"), d("20261012"))
    assert intervals == [DateInterval(d("20260711"), d("20261012"))]
    assert active_services(old, intervals[0]) == {"B_wd", "B_sa"}
    assert active_services(new, intervals[0]) == {"B_wd", "B_sa"}


def test_coexistence_as_new_side_splits_at_revision():
    # 改正前のみ vs 同居 (新側): 共通窓 6/1〜10/3 が改正日 7/11 で2分割。
    # 区間1は旧世代同士、区間2は「7/11 改正」の中身
    old, new = snap(PRE), snap(COEX)
    window, intervals = window_intervals(old, new)
    assert window == DateInterval(d("20260601"), d("20261003"))
    assert intervals == [
        DateInterval(d("20260601"), d("20260710")),
        DateInterval(d("20260711"), d("20261003")),
    ]
    assert active_services(old, intervals[0]) == {"A_wd", "A_sa"}
    assert active_services(new, intervals[0]) == {"A_wd", "A_sa"}
    assert active_services(old, intervals[1]) == {"A_wd", "A_sa"}
    assert active_services(new, intervals[1]) == {"B_wd", "B_sa"}


def test_single_generation_pair_degenerates_to_one_interval():
    # 単一世代同士 → 区間1つ = 現行挙動への退化 (回帰保証の主眼)
    old = snap({"X": ("1111100", "20260401", "20260930")})
    new = snap({"Y": ("1111100", "20260401", "20260930")})
    window, intervals = window_intervals(old, new)
    assert intervals == [DateInterval(d("20260401"), d("20260930"))]


def test_no_overlap_returns_none():
    old = snap({"X": ("1111100", "20250401", "20250930")})
    new = snap({"Y": ("1111100", "20260401", "20260930")})
    assert common_window(old, new) is None
    assert window_intervals(old, new) == (None, [])


def test_active_services_respects_removals_and_additions():
    # 全削除された service は区間に現れず、追加日だけの service は現れる
    cal = {"S": ("0000010", "20260704", "20260718")}
    cd = [("S", "20260704", "2"), ("S", "20260711", "2"), ("S", "20260718", "2"),
          ("H", "20260713", "1")]
    s = snap(cal, cd)
    iv = DateInterval(d("20260701"), d("20260731"))
    assert active_services(s, iv) == {"H"}


def test_interval_days():
    assert DateInterval(d("20260601"), d("20260710")).days() == 40

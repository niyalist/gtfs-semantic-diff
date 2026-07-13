

def test_lcs_memoization_identical_results():
    """P1: LCS メモ化 (同一パターンの繰り返しが多いブロック) が結果を変えないこと。
    多数便×少パターンのブロックで、素の lcs_ratio と同じ受理・割当になる。"""
    from gtfs_semantic_diff.events.tripdelta import (
        TripInfo, build_trip_delta, lcs_ratio)

    seq_a = ("A", "B", "C", "D")
    seq_b = ("A", "B", "X", "D")   # lcs_ratio = 3/4 (受理域)
    seq_c = ("P", "Q", "R", "S")   # 無関係 (0.0、棄却域)

    def trip(gen, i, seq, hh):
        times = tuple((f"{hh:02d}:{5 * i % 60:02d}:00",) * 2 for _ in seq)
        return TripInfo(trip_id=f"{gen}{i}", route_id="R1", family="F1",
                        direction="0", day_type="weekday",
                        base_seq=seq, times=times)

    # 旧: seq_a 20便 + seq_c 3便 / 新: seq_b 20便 (時刻はほぼ据え置き)
    old = {t.trip_id: t for i in range(20) for t in [trip("o", i, seq_a, 8)]}
    old |= {t.trip_id: t for i in range(3) for t in [trip("oc", i, seq_c, 8)]}
    new = {t.trip_id: t for i in range(20) for t in [trip("n", i, seq_b, 8)]}
    delta = build_trip_delta(old, new)
    assert len(delta.modified) == 20              # seq_a ↔ seq_b が全て対応
    assert all(o.base_seq == seq_a and n.base_seq == seq_b
               for o, n in delta.modified)
    assert {t.trip_id for t in delta.removed} == {f"oc{i}" for i in range(3)}
    assert lcs_ratio(seq_a, seq_b) == 0.75        # メモ化対象の素関数は不変


def test_segment_stats_deterministic_order():
    """再現性: 区間統計は set 交差の反復順 (PYTHONHASHSEED 依存) に依らず、
    |中央値差| 降順 → 区間名でタイブレークの決定的順序で出る。"""
    from gtfs_semantic_diff.events.rules.frequency import _segment_stats
    from gtfs_semantic_diff.events.tripdelta import TripInfo

    def trip(gen, seq, minutes):
        times = tuple((f"08:{m:02d}:00", f"08:{m:02d}:00") for m in minutes)
        return TripInfo(trip_id=gen, route_id="R", family="F", direction="0",
                        day_type="weekday", base_seq=seq, times=times)

    # 3区間とも中央値差60秒 (全てタイ) — 順序は区間名の辞書順に決まるべき
    o = trip("o", ("A", "B", "C", "D"), (0, 5, 10, 15))
    n = trip("n", ("A", "B", "C", "D"), (0, 6, 12, 18))
    stats = _segment_stats([(o, n, None)])
    assert [s["segment"] for s in stats] == ["A→B", "B→C", "C→D"]


def test_exact_pairs_deterministic_order():
    """再現性: 内容署名一致 (段1) の組は署名のソート順で列挙される。"""
    from gtfs_semantic_diff.events.tripdelta import TripInfo, build_trip_delta

    def trip(tid, seq):
        return TripInfo(trip_id=tid, route_id="R", family="F", direction="0",
                        day_type="weekday", base_seq=seq,
                        times=(("08:00:00", "08:00:00"),) * len(seq))

    old = {t.trip_id: t for t in
           [trip("o1", ("X", "Y")), trip("o2", ("A", "B")), trip("o3", ("M", "N"))]}
    new = {t.trip_id: t for t in
           [trip("n1", ("X", "Y")), trip("n2", ("A", "B")), trip("n3", ("M", "N"))]}
    delta = build_trip_delta(old, new)
    # base_seq のソート順 = (A,B) < (M,N) < (X,Y)
    assert [(o.trip_id, n.trip_id) for o, n in delta.exact_pairs] == [
        ("o2", "n2"), ("o3", "n3"), ("o1", "n1")]

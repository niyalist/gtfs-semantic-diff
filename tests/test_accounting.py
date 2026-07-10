"""events/accounting.py の単体テスト。"""

import pytest

from gtfs_semantic_diff.events import EvidenceLedger, UnknownRawDiffError
from gtfs_semantic_diff.model import RawDiff, RawDiffSet


@pytest.fixture
def rawdiffs() -> RawDiffSet:
    return RawDiffSet(
        [
            RawDiff("rawdiff_000001", "stops.txt", "row_added", ("S4",)),
            RawDiff("rawdiff_000002", "stops.txt", "field_changed", ("S2",), "stop_name", "a", "b"),
            RawDiff("rawdiff_000003", "trips.txt", "row_removed", ("T2",)),
            RawDiff("rawdiff_000004", "stop_times.txt", "row_removed", ("T2", "1")),
        ]
    )


def test_all_unexplained_when_nothing_consumed(rawdiffs):
    ledger = EvidenceLedger(rawdiffs)
    events = ledger.residual_events()
    acc = ledger.accounting()

    assert acc.rawdiff_total == 4
    assert acc.explained == 0
    assert acc.explained_ratio == 0.0
    assert acc.residual_breakdown_by_file == {
        "stop_times.txt": 1,
        "stops.txt": 2,
        "trips.txt": 1,
    }
    # 残差イベントはファイル単位で、全 RawDiff を evidence に持つ
    assert [e.subject["file"] for e in events] == ["stop_times.txt", "stops.txt", "trips.txt"]
    assert sorted(rid for e in events for rid in e.evidence) == [
        f"rawdiff_{i:06d}" for i in range(1, 5)
    ]
    assert all(e.type == "UNEXPLAINED_RESIDUAL" for e in events)


def test_consume_marks_explained(rawdiffs):
    ledger = EvidenceLedger(rawdiffs)
    ledger.consume("evt_x00001", ["rawdiff_000001", "rawdiff_000002"])
    events = ledger.residual_events()
    acc = ledger.accounting()

    assert acc.explained == 2
    assert acc.explained_ratio == pytest.approx(0.5)
    assert acc.residual_breakdown_by_file == {"stop_times.txt": 1, "trips.txt": 1}
    assert {e.subject["file"] for e in events} == {"stop_times.txt", "trips.txt"}


def test_multiple_events_may_share_evidence(rawdiffs):
    ledger = EvidenceLedger(rawdiffs)
    ledger.consume("evt_a", ["rawdiff_000001"], primary=True)
    ledger.consume("evt_b", ["rawdiff_000001"], primary=True)
    assert ledger.primary_event_of("rawdiff_000001") == "evt_a"  # 最初の primary が勝つ
    assert ledger.explained_count() == 1


def test_unknown_rawdiff_id_raises(rawdiffs):
    ledger = EvidenceLedger(rawdiffs)
    with pytest.raises(UnknownRawDiffError):
        ledger.consume("evt_a", ["rawdiff_999999"])


def test_residual_not_counted_as_explained(rawdiffs):
    ledger = EvidenceLedger(rawdiffs)
    ledger.residual_events()
    # 残差イベントが全件を consume しても explained は増えない
    assert ledger.explained_count() == 0
    assert len(ledger.unexplained()) == 4  # 台帳上は依然として未説明
    assert ledger.unconsumed() == []  # ただし二重に残差イベント化はされない
    assert ledger.residual_events(event_id_start=100) == []

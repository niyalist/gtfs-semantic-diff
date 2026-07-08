"""model/ データクラスの単体テスト。"""

import pytest

from gtfs_semantic_diff.model import (
    EVENT_TYPES,
    Accounting,
    ChangeEvent,
    ChangeEventSet,
    MatchEdge,
    MatchGraph,
    RawDiff,
    RawDiffSet,
)


class TestRawDiff:
    def test_roundtrip(self):
        d = RawDiff(
            rawdiff_id="rawdiff_000001",
            file="stop_times.txt",
            kind="field_changed",
            key=("T1", "3"),
            column="departure_time",
            old_value="08:10:00",
            new_value="08:12:00",
        )
        assert RawDiff.from_dict(d.to_dict()) == d

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="kind"):
            RawDiff(rawdiff_id="rawdiff_000001", file="stops.txt", kind="mutated")

    def test_count_by_file(self):
        diffs = RawDiffSet(
            [
                RawDiff("rawdiff_1", "stops.txt", "row_added", ("S9",)),
                RawDiff("rawdiff_2", "stops.txt", "row_removed", ("S1",)),
                RawDiff("rawdiff_3", "trips.txt", "row_added", ("T9",)),
            ]
        )
        assert diffs.count_by_file() == {"stops.txt": 2, "trips.txt": 1}
        assert len(diffs) == 3


class TestChangeEvent:
    def test_default_severity_and_display_name(self):
        e = ChangeEvent(event_id="evt_000001", type="ROUTE_DISCONTINUED")
        assert e.severity == "major"
        assert e.display_name_ja == "路線廃止"

    def test_severity_override(self):
        e = ChangeEvent(event_id="evt_000001", type="SERVICE_REDUCED", severity="major")
        assert e.severity == "major"

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError, match="event type"):
            ChangeEvent(event_id="evt_000001", type="SOMETHING_ELSE")

    def test_json_roundtrip(self):
        e = ChangeEvent(
            event_id="evt_000123",
            type="SERVICE_REDUCED",
            subject={"route_family": "41号線", "day_type": "weekday"},
            quantification={"time_band": "9-16", "old_count": 21, "new_count": 14},
            evidence=["rawdiff_00871", "rawdiff_00872"],
            confidence=0.94,
        )
        d = e.to_dict()
        assert d["display_name_ja"] == "減便"
        restored = ChangeEvent.from_dict(d)
        assert restored.to_dict() == d

    def test_catalog_covers_ontology_categories(self):
        assert {t.category for t in EVENT_TYPES.values()} == {"A", "B", "C", "D", "E", "F"}
        assert "UNEXPLAINED_RESIDUAL" in EVENT_TYPES
        assert "TECHNICAL_ID_CHURN" in EVENT_TYPES


class TestAccounting:
    def test_ratio(self):
        a = Accounting(rawdiff_total=200, explained=150)
        assert a.explained_ratio == pytest.approx(0.75)

    def test_empty_is_fully_explained(self):
        assert Accounting().explained_ratio == 1.0

    def test_event_set_top_level_schema(self):
        s = ChangeEventSet(feed={"org_id": "x", "feed_id": "y"})
        d = s.to_dict()
        assert d["schema_version"] == "0.2"
        assert set(d) == {
            "schema_version",
            "feed",
            "generated_at",
            "config_snapshot",
            "events",
            "accounting",
            "context",
        }


class TestMatchGraph:
    def test_queries_sorted_by_confidence(self):
        g = MatchGraph()
        g.add(MatchEdge("stop_cluster", "old_A", "new_B", 0.5, "proximity"))
        g.add(MatchEdge("stop_cluster", "old_A", "new_C", 0.9, "name_exact"))
        g.add(MatchEdge("route_family", "old_A", "new_D", 0.7, "pattern"))
        matches = g.matches_for_old("stop_cluster", "old_A")
        assert [e.new_id for e in matches] == ["new_C", "new_B"]
        assert len(g.for_type("route_family")) == 1

    def test_validation(self):
        with pytest.raises(ValueError):
            MatchEdge("bogus_type", "a", "b", 0.5, "m")
        with pytest.raises(ValueError):
            MatchEdge("service", "a", "b", 1.5, "m")

"""Tests for Phase 4 comparison automation scripts.

Tests cover:
- ComparisonDataStore: JSON persistence, session management, summary stats
- ComparisonRecorder: briefing token count extraction, event count extraction
- ComparisonReporter: A/B table generation, improvement calculations, success criteria
- _calc_improvement: edge cases for both lower/higher-is-better metrics
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.testing.comparison_recorder import (
    CHARS_PER_TOKEN,
    ComparisonDataStore,
    ComparisonRecorder,
)
from scripts.testing.comparison_reporter import ComparisonReporter, _calc_improvement
from scripts.testing.session_recorder import BaselineDataStore

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def comparison_store(tmp_path: Path) -> ComparisonDataStore:
    """A ComparisonDataStore backed by a temp directory."""
    return ComparisonDataStore(tmp_path / "comparison-data.json")


@pytest.fixture
def baseline_store(tmp_path: Path) -> BaselineDataStore:
    """A BaselineDataStore backed by a temp directory."""
    return BaselineDataStore(tmp_path / "baseline-data.json")


def _make_comparison_session(**overrides) -> dict:
    """Create a minimal comparison session dict for testing."""
    session = {
        "date": "2026-02-10",
        "task_description": "test task",
        "cold_start_minutes": 1.0,
        "decision_regression_count": 0,
        "re_exploration_count": 2,
        "continuity_score": 4,
        "briefing_token_count": 500,
        "event_count": 25,
        "notes": "",
        "transcript_path": "/tmp/test.jsonl",
        "files_explored": ["/src/main.py", "/src/utils.py"],
        "files_modified": ["/src/main.py"],
        "session_duration_minutes": 30.0,
        "tool_call_count": 50,
    }
    session.update(overrides)
    return session


def _make_baseline_session(**overrides) -> dict:
    """Create a minimal baseline session dict for testing."""
    session = {
        "date": "2026-02-05",
        "task_description": "baseline task",
        "cold_start_minutes": 5.0,
        "decision_regression_count": 1,
        "re_exploration_count": 6,
        "continuity_score": 3,
        "notes": "",
        "transcript_path": "/tmp/baseline.jsonl",
        "files_explored": ["/src/main.py"],
        "files_modified": ["/src/main.py"],
        "session_duration_minutes": 45.0,
        "tool_call_count": 80,
    }
    session.update(overrides)
    return session


# ============================================================================
# ComparisonDataStore tests
# ============================================================================


class TestComparisonDataStoreBasics:
    """Tests for basic ComparisonDataStore operations."""

    def test_empty_store_returns_empty_sessions(self, comparison_store: ComparisonDataStore) -> None:
        """A new store has no sessions."""
        assert comparison_store.get_sessions() == []

    def test_empty_store_returns_empty_summary(self, comparison_store: ComparisonDataStore) -> None:
        """A new store has an empty summary."""
        assert comparison_store.get_summary() == {}

    def test_load_creates_structure(self, comparison_store: ComparisonDataStore) -> None:
        """Loading a non-existent store creates the default structure."""
        data = comparison_store.load()
        assert data["version"] == 1
        assert data["phase"] == "comparison"
        assert data["sessions"] == []

    def test_path_property(self, comparison_store: ComparisonDataStore) -> None:
        """The path property returns the data file path."""
        assert comparison_store.path.name == "comparison-data.json"


class TestComparisonDataStoreAddSession:
    """Tests for adding sessions to ComparisonDataStore."""

    def test_add_session_increments_count(self, comparison_store: ComparisonDataStore) -> None:
        """Adding a session increments the session count."""
        comparison_store.add_session(_make_comparison_session())
        assert len(comparison_store.get_sessions()) == 1

    def test_add_session_assigns_number(self, comparison_store: ComparisonDataStore) -> None:
        """Sessions get auto-assigned sequential numbers."""
        comparison_store.add_session(_make_comparison_session())
        comparison_store.add_session(_make_comparison_session())
        sessions = comparison_store.get_sessions()
        assert sessions[0]["session_number"] == 1
        assert sessions[1]["session_number"] == 2

    def test_add_session_records_timestamp(self, comparison_store: ComparisonDataStore) -> None:
        """Sessions get a recorded_at timestamp."""
        comparison_store.add_session(_make_comparison_session())
        session = comparison_store.get_sessions()[0]
        assert "recorded_at" in session

    def test_add_session_persists_to_disk(self, comparison_store: ComparisonDataStore) -> None:
        """Sessions survive a store reload."""
        comparison_store.add_session(_make_comparison_session(task_description="persist test"))
        fresh = ComparisonDataStore(comparison_store.path)
        sessions = fresh.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["task_description"] == "persist test"


class TestComparisonDataStoreSummary:
    """Tests for summary recomputation with 6 metrics."""

    def test_summary_with_sessions(self, comparison_store: ComparisonDataStore) -> None:
        """Summary includes all 6 metric statistics."""
        comparison_store.add_session(
            _make_comparison_session(
                cold_start_minutes=2.0,
                decision_regression_count=0,
                re_exploration_count=3,
                continuity_score=4,
                briefing_token_count=600,
                event_count=30,
            )
        )
        comparison_store.add_session(
            _make_comparison_session(
                cold_start_minutes=4.0,
                decision_regression_count=1,
                re_exploration_count=5,
                continuity_score=3,
                briefing_token_count=800,
                event_count=40,
            )
        )
        summary = comparison_store.get_summary()

        assert summary["total_sessions"] == 2
        assert summary["cold_start"]["avg"] == 3.0
        assert summary["briefing_token_count"]["avg"] == 700.0
        assert summary["event_count"]["avg"] == 35.0
        assert summary["continuity_score"]["min"] == 3
        assert summary["continuity_score"]["max"] == 4

    def test_empty_summary(self, comparison_store: ComparisonDataStore) -> None:
        """Empty store summary has zero total."""
        comparison_store.save(comparison_store.load())
        summary = comparison_store.get_summary()
        assert summary["total_sessions"] == 0


class TestComparisonDataStoreReset:
    """Tests for resetting comparison data."""

    def test_reset_clears_sessions(self, comparison_store: ComparisonDataStore) -> None:
        """Reset removes all sessions."""
        comparison_store.add_session(_make_comparison_session())
        comparison_store.add_session(_make_comparison_session())
        comparison_store.reset()
        assert comparison_store.get_sessions() == []

    def test_reset_preserves_phase(self, comparison_store: ComparisonDataStore) -> None:
        """Reset keeps the phase marker."""
        comparison_store.add_session(_make_comparison_session())
        comparison_store.reset()
        data = comparison_store.load()
        assert data["phase"] == "comparison"


class TestComparisonDataStoreFiles:
    """Tests for file tracking across sessions."""

    def test_get_all_files_explored(self, comparison_store: ComparisonDataStore) -> None:
        """Cumulative file set spans all sessions."""
        comparison_store.add_session(_make_comparison_session(files_explored=["/a.py", "/b.py"]))
        comparison_store.add_session(_make_comparison_session(files_explored=["/b.py", "/c.py"]))
        files = comparison_store.get_all_files_explored()
        assert files == {"/a.py", "/b.py", "/c.py"}

    def test_empty_files_explored(self, comparison_store: ComparisonDataStore) -> None:
        """Empty store returns empty file set."""
        assert comparison_store.get_all_files_explored() == set()


# ============================================================================
# ComparisonRecorder tests (metric extraction)
# ============================================================================


class TestBriefingTokenCount:
    """Tests for _read_briefing_token_count."""

    def test_briefing_exists(self, tmp_path: Path) -> None:
        """Token count is chars // CHARS_PER_TOKEN when briefing exists."""
        project = tmp_path / "project"
        briefing_dir = project / ".claude" / "rules"
        briefing_dir.mkdir(parents=True)
        briefing_path = briefing_dir / "cortex-briefing.md"
        content = "A" * 400  # 400 chars -> 100 tokens
        briefing_path.write_text(content, encoding="utf-8")

        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=str(project))
        result = recorder._read_briefing_token_count()
        assert result == 400 // CHARS_PER_TOKEN

    def test_briefing_missing(self, tmp_path: Path) -> None:
        """Returns 0 when no briefing file exists."""
        project = tmp_path / "project"
        project.mkdir()

        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=str(project))
        assert recorder._read_briefing_token_count() == 0

    def test_briefing_empty(self, tmp_path: Path) -> None:
        """Returns 0 when briefing file is empty."""
        project = tmp_path / "project"
        briefing_dir = project / ".claude" / "rules"
        briefing_dir.mkdir(parents=True)
        (briefing_dir / "cortex-briefing.md").write_text("", encoding="utf-8")

        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=str(project))
        assert recorder._read_briefing_token_count() == 0

    def test_no_project_cwd(self, tmp_path: Path) -> None:
        """Returns 0 when no project directory is specified."""
        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=None)
        assert recorder._read_briefing_token_count() == 0


class TestEventCount:
    """Tests for _read_event_count."""

    def test_with_events(self, tmp_path: Path, tmp_cortex_home: Path, sample_config, event_store) -> None:
        """Event count matches the number of events in the store."""
        from cortex.models import EventType, create_event

        event_store.append(create_event(EventType.DECISION_MADE, "chose X"))
        event_store.append(create_event(EventType.KNOWLEDGE_ACQUIRED, "learned Y"))

        # WHAT: Mock get_project_hash to return the sample hash.
        # WHY: The recorder calls get_project_hash(project_cwd) which
        #       would hash the actual tmp_path, not match our fixture.
        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=str(tmp_path))

        with (
            patch("scripts.testing.comparison_recorder.get_project_hash") as mock_hash,
            patch("scripts.testing.comparison_recorder.EventStore") as mock_store_cls,
        ):
            mock_hash.return_value = "abc123def456abcd"
            mock_store_cls.return_value = event_store
            result = recorder._read_event_count()
            assert result == 2

    def test_empty_store(self, tmp_path: Path) -> None:
        """Returns 0 for empty event store."""
        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=str(tmp_path))

        with (
            patch("scripts.testing.comparison_recorder.get_project_hash") as mock_hash,
            patch("scripts.testing.comparison_recorder.EventStore") as mock_store_cls,
        ):
            mock_hash.return_value = "test_hash"
            mock_instance = mock_store_cls.return_value
            mock_instance.count.return_value = 0
            result = recorder._read_event_count()
            assert result == 0

    def test_no_project_cwd(self, tmp_path: Path) -> None:
        """Returns 0 when no project directory is specified."""
        store = ComparisonDataStore(tmp_path / "data.json")
        recorder = ComparisonRecorder(store, project_cwd=None)
        assert recorder._read_event_count() == 0


# ============================================================================
# _calc_improvement tests
# ============================================================================


class TestCalcImprovement:
    """Tests for the improvement percentage calculation."""

    def test_lower_is_better_reduction(self) -> None:
        """80% reduction when baseline=10, comparison=2."""
        assert _calc_improvement(10, 2, lower_is_better=True) == 80.0

    def test_lower_is_better_no_change(self) -> None:
        """0% improvement when no change."""
        assert _calc_improvement(5, 5, lower_is_better=True) == 0.0

    def test_lower_is_better_increase(self) -> None:
        """Negative improvement when comparison is worse."""
        result = _calc_improvement(5, 10, lower_is_better=True)
        assert result == -100.0

    def test_higher_is_better_increase(self) -> None:
        """100% improvement when doubled."""
        assert _calc_improvement(2, 4, lower_is_better=False) == 100.0

    def test_higher_is_better_decrease(self) -> None:
        """Negative improvement when comparison is worse."""
        result = _calc_improvement(4, 2, lower_is_better=False)
        assert result == -50.0

    def test_zero_baseline(self) -> None:
        """Returns 0 when baseline is zero (can't compute percentage)."""
        assert _calc_improvement(0, 5, lower_is_better=True) == 0.0
        assert _calc_improvement(0, 5, lower_is_better=False) == 0.0

    def test_both_zero(self) -> None:
        """Returns 0 when both are zero."""
        assert _calc_improvement(0, 0, lower_is_better=True) == 0.0

    def test_comparison_to_zero(self) -> None:
        """100% reduction when comparison is zero."""
        assert _calc_improvement(10, 0, lower_is_better=True) == 100.0


# ============================================================================
# ComparisonReporter tests
# ============================================================================


class TestComparisonReporterTable:
    """Tests for A/B comparison table generation."""

    def _setup_stores(self, tmp_path: Path) -> tuple[BaselineDataStore, ComparisonDataStore]:
        """Create stores with sample data for testing."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        # Add baseline sessions
        for _ in range(3):
            session = _make_baseline_session(
                cold_start_minutes=10.0,
                decision_regression_count=1,
                re_exploration_count=6,
                continuity_score=2,
            )
            baseline.add_session(session)

        # Add comparison sessions (improved)
        for _ in range(3):
            session = _make_comparison_session(
                cold_start_minutes=1.0,
                decision_regression_count=0,
                re_exploration_count=2,
                continuity_score=4,
                briefing_token_count=500,
                event_count=30,
            )
            comparison.add_session(session)

        return baseline, comparison

    def test_report_generates_markdown(self, tmp_path: Path) -> None:
        """Report generates a non-empty markdown string."""
        baseline, comparison = self._setup_stores(tmp_path)
        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert len(report) > 100
        assert "# Tier 0 A/B Comparison Results" in report

    def test_report_includes_comparison_table(self, tmp_path: Path) -> None:
        """Report includes the A/B comparison results table."""
        baseline, comparison = self._setup_stores(tmp_path)
        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert "A/B Comparison Results" in report
        assert "Cold start time (min)" in report
        assert "Token overhead" in report

    def test_report_includes_success_criteria(self, tmp_path: Path) -> None:
        """Report includes success criteria evaluation."""
        baseline, comparison = self._setup_stores(tmp_path)
        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert "Success Criteria Evaluation" in report
        assert "Pass" in report or "Fail" in report

    def test_report_handles_empty_comparison(self, tmp_path: Path) -> None:
        """Report handles empty comparison data gracefully."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        baseline.add_session(_make_baseline_session())
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert "Need both baseline and comparison data" in report

    def test_write_report(self, tmp_path: Path) -> None:
        """write_report creates a file on disk."""
        baseline, comparison = self._setup_stores(tmp_path)
        reporter = ComparisonReporter(baseline, comparison)
        output = tmp_path / "report.md"
        reporter.write_report(output)
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "Tier 0 A/B Comparison Results" in content


class TestComparisonReporterCriteria:
    """Tests for success criteria pass/fail logic."""

    def test_cold_start_passes_at_80_percent(self, tmp_path: Path) -> None:
        """Cold start criterion passes at exactly 80% reduction."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        baseline.add_session(_make_baseline_session(cold_start_minutes=10.0))
        comparison.add_session(
            _make_comparison_session(cold_start_minutes=2.0)  # 80% reduction
        )

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        # Find the cold start row and check it passes
        lines = report.split("\n")
        cold_start_lines = [line for line in lines if "Cold start time reduction" in line]
        assert len(cold_start_lines) == 1
        assert "Pass" in cold_start_lines[0]

    def test_token_overhead_fails_above_15_percent(self, tmp_path: Path) -> None:
        """Token overhead criterion fails when above 15%."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        baseline.add_session(_make_baseline_session())
        # 200K * 0.16 = 32000 tokens (16% overhead -> should fail)
        comparison.add_session(_make_comparison_session(briefing_token_count=32000))

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        lines = report.split("\n")
        # WHAT: Check the success criteria table (uses "Pass"/"Fail"),
        #       not the comparison table (uses "Yes"/"No").
        token_lines = [line for line in lines if "Token overhead" in line and "Fail" in line]
        assert len(token_lines) >= 1

    def test_decision_regression_near_zero(self, tmp_path: Path) -> None:
        """Decision regression passes when avg <= 0.1."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        baseline.add_session(_make_baseline_session(decision_regression_count=2))
        comparison.add_session(_make_comparison_session(decision_regression_count=0))

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        lines = report.split("\n")
        # WHAT: Check the success criteria table (uses "Pass"/"Fail"),
        #       not the comparison table (uses "Yes"/"No").
        regression_lines = [line for line in lines if "Decision regression" in line and "Pass" in line]
        assert len(regression_lines) >= 1


class TestComparisonReporterObservations:
    """Tests for auto-generated observation sections."""

    def test_briefing_analysis_shown(self, tmp_path: Path) -> None:
        """Briefing size analysis appears in observations."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        baseline.add_session(_make_baseline_session())
        comparison.add_session(_make_comparison_session(briefing_token_count=750))

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert "Briefing Size Analysis" in report
        assert "750" in report

    def test_qualitative_sections_present(self, tmp_path: Path) -> None:
        """Qualitative observation placeholders are in the report."""
        baseline = BaselineDataStore(tmp_path / "baseline.json")
        comparison = ComparisonDataStore(tmp_path / "comparison.json")

        baseline.add_session(_make_baseline_session())
        comparison.add_session(_make_comparison_session())

        reporter = ComparisonReporter(baseline, comparison)
        report = reporter.generate_report()
        assert "Briefing Quality" in report
        assert "Context Preservation" in report
        assert "Pain Points" in report
        assert "Unexpected Benefits" in report

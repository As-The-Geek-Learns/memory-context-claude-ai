"""Tests for hybrid search (FTS5 + vector with RRF).

Tests cover:
- RRF score computation
- Hybrid search with both FTS and vector results
- FTS-only and vector-only fallback
- Filters (event_type, branch, min_confidence)
- Edge cases (empty queries, no results)
- Result ordering and limiting
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from cortex import db
from cortex.hybrid_search import (
    DEFAULT_RRF_K,
    HybridResult,
    _compute_rrf_score,
    _fts_only_results,
    _load_event,
    _vec_only_results,
    hybrid_search,
    search_semantic,
)
from cortex.models import Event, EventType
from cortex.search import SearchResult
from cortex.vec import VectorSearchResult

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with schema initialized."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db.initialize_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def sample_events(test_db):
    """Insert sample events and return their IDs."""
    now = datetime.now(timezone.utc).isoformat()
    events = [
        ("evt1", "decision_made", "Use SQLite for database storage", 0.9, "main"),
        ("evt2", "knowledge_acquired", "Python supports async await patterns", 0.7, "main"),
        ("evt3", "error_resolved", "Fixed import error in module", 0.6, "feature"),
        ("evt4", "decision_made", "Use pytest for testing framework", 0.8, "main"),
        ("evt5", "knowledge_acquired", "SQLite has FTS5 for full text search", 0.85, "main"),
    ]
    for event_id, event_type, content, confidence, branch in events:
        test_db.execute(
            """
            INSERT INTO events (
                id, session_id, project, git_branch, type, content,
                metadata, salience, confidence, created_at, accessed_at,
                access_count, immortal, provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                "session1",
                "test-project",
                branch,
                event_type,
                content,
                "{}",
                0.5,
                confidence,
                now,
                now,
                0,
                0,
                "test",
            ),
        )
    test_db.commit()
    return [e[0] for e in events]


# =============================================================================
# Test RRF Score Computation
# =============================================================================


class TestComputeRRFScore:
    """Tests for _compute_rrf_score function."""

    def test_both_ranks_present(self):
        """Both FTS and vec ranks contribute to score."""
        score = _compute_rrf_score(
            fts_rank=1,
            vec_rank=1,
            k=60,
            fts_weight=0.5,
            vec_weight=0.5,
        )
        # Expected: 0.5/(60+1) + 0.5/(60+1) = 1.0/61
        expected = 1.0 / 61
        assert abs(score - expected) < 0.0001

    def test_only_fts_rank(self):
        """Only FTS rank contributes when vec is None."""
        score = _compute_rrf_score(
            fts_rank=1,
            vec_rank=None,
            k=60,
            fts_weight=0.5,
            vec_weight=0.5,
        )
        expected = 0.5 / 61
        assert abs(score - expected) < 0.0001

    def test_only_vec_rank(self):
        """Only vec rank contributes when FTS is None."""
        score = _compute_rrf_score(
            fts_rank=None,
            vec_rank=1,
            k=60,
            fts_weight=0.5,
            vec_weight=0.5,
        )
        expected = 0.5 / 61
        assert abs(score - expected) < 0.0001

    def test_neither_rank_present(self):
        """Score is 0 when both ranks are None."""
        score = _compute_rrf_score(
            fts_rank=None,
            vec_rank=None,
            k=60,
            fts_weight=0.5,
            vec_weight=0.5,
        )
        assert score == 0.0

    def test_higher_rank_lower_score(self):
        """Higher ranks (worse) produce lower scores."""
        score_rank1 = _compute_rrf_score(1, 1, 60, 0.5, 0.5)
        score_rank10 = _compute_rrf_score(10, 10, 60, 0.5, 0.5)
        assert score_rank1 > score_rank10

    def test_custom_k_parameter(self):
        """Different k values affect scores."""
        score_k60 = _compute_rrf_score(1, 1, 60, 0.5, 0.5)
        score_k10 = _compute_rrf_score(1, 1, 10, 0.5, 0.5)
        # Lower k means higher score for rank 1
        assert score_k10 > score_k60

    def test_unequal_weights(self):
        """Unequal weights bias toward one method."""
        score_fts_heavy = _compute_rrf_score(1, 10, 60, 0.8, 0.2)
        score_vec_heavy = _compute_rrf_score(1, 10, 60, 0.2, 0.8)
        # FTS-heavy should score better when FTS rank is lower
        assert score_fts_heavy > score_vec_heavy

    def test_default_k_constant(self):
        """DEFAULT_RRF_K is the standard value."""
        assert DEFAULT_RRF_K == 60


# =============================================================================
# Test HybridResult Dataclass
# =============================================================================


class TestHybridResultDataclass:
    """Tests for HybridResult dataclass."""

    def test_creates_result_with_all_fields(self):
        """HybridResult holds all search metadata."""
        event = Event(
            id="evt1",
            type=EventType.DECISION_MADE,
            content="Test content",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        result = HybridResult(
            event=event,
            fts_rank=1,
            vec_rank=2,
            rrf_score=0.016,
            fts_score=2.5,
            similarity=0.85,
            snippet="Test **content**",
        )
        assert result.event.id == "evt1"
        assert result.fts_rank == 1
        assert result.vec_rank == 2
        assert result.rrf_score == 0.016
        assert result.fts_score == 2.5
        assert result.similarity == 0.85
        assert "**content**" in result.snippet

    def test_optional_fields_can_be_none(self):
        """Optional fields can be None."""
        event = Event(
            id="evt1",
            type=EventType.DECISION_MADE,
            content="Test",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        result = HybridResult(
            event=event,
            fts_rank=None,
            vec_rank=1,
            rrf_score=0.008,
            fts_score=None,
            similarity=0.9,
            snippet="Test",
        )
        assert result.fts_rank is None
        assert result.fts_score is None


# =============================================================================
# Test Load Event
# =============================================================================


class TestLoadEvent:
    """Tests for _load_event helper function."""

    def test_loads_existing_event(self, test_db, sample_events):
        """Loads event from database by ID."""
        event = _load_event(test_db, "evt1")
        assert event is not None
        assert event.id == "evt1"
        assert event.type == EventType.DECISION_MADE
        assert "SQLite" in event.content

    def test_returns_none_for_missing_event(self, test_db):
        """Returns None for non-existent event."""
        event = _load_event(test_db, "nonexistent")
        assert event is None

    def test_handles_empty_metadata(self, test_db, sample_events):
        """Handles empty JSON metadata string."""
        event = _load_event(test_db, "evt1")
        assert event.metadata == {}


# =============================================================================
# Test FTS-Only Results
# =============================================================================


class TestFTSOnlyResults:
    """Tests for _fts_only_results conversion."""

    def test_converts_fts_results(self):
        """Converts FTS SearchResults to HybridResults."""
        event = Event(
            id="evt1",
            type=EventType.DECISION_MADE,
            content="Test content",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        fts_results = [
            SearchResult(event=event, score=2.5, snippet="Test **content**"),
        ]

        results = _fts_only_results(fts_results, k=60, fts_weight=0.5, limit=10)

        assert len(results) == 1
        assert results[0].fts_rank == 1
        assert results[0].vec_rank is None
        assert results[0].fts_score == 2.5
        assert results[0].similarity is None

    def test_assigns_ranks_in_order(self):
        """Ranks are assigned 1, 2, 3..."""
        events = [
            Event(
                id=f"evt{i}",
                type=EventType.DECISION_MADE,
                content=f"Content {i}",
                created_at=datetime.now(timezone.utc).isoformat(),
                accessed_at=datetime.now(timezone.utc).isoformat(),
            )
            for i in range(3)
        ]
        fts_results = [SearchResult(event=e, score=1.0, snippet=e.content) for e in events]

        results = _fts_only_results(fts_results, k=60, fts_weight=0.5, limit=10)

        assert [r.fts_rank for r in results] == [1, 2, 3]

    def test_respects_limit(self):
        """Respects the limit parameter."""
        events = [
            Event(
                id=f"evt{i}",
                type=EventType.DECISION_MADE,
                content=f"Content {i}",
                created_at=datetime.now(timezone.utc).isoformat(),
                accessed_at=datetime.now(timezone.utc).isoformat(),
            )
            for i in range(10)
        ]
        fts_results = [SearchResult(event=e, score=1.0, snippet=e.content) for e in events]

        results = _fts_only_results(fts_results, k=60, fts_weight=0.5, limit=3)

        assert len(results) == 3


# =============================================================================
# Test Vec-Only Results
# =============================================================================


class TestVecOnlyResults:
    """Tests for _vec_only_results conversion."""

    def test_converts_vec_results(self, test_db, sample_events):
        """Converts VectorSearchResults to HybridResults."""
        vec_results = [
            VectorSearchResult(event_id="evt1", distance=0.5, similarity=0.85),
        ]

        results = _vec_only_results(test_db, vec_results, k=60, vec_weight=0.5, limit=10)

        assert len(results) == 1
        assert results[0].fts_rank is None
        assert results[0].vec_rank == 1
        assert results[0].similarity == 0.85
        assert results[0].fts_score is None

    def test_skips_missing_events(self, test_db):
        """Skips events that can't be loaded."""
        vec_results = [
            VectorSearchResult(event_id="nonexistent", distance=0.5, similarity=0.85),
        ]

        results = _vec_only_results(test_db, vec_results, k=60, vec_weight=0.5, limit=10)

        assert len(results) == 0


# =============================================================================
# Test Hybrid Search
# =============================================================================


class TestHybridSearch:
    """Tests for hybrid_search function."""

    def test_empty_query_returns_empty(self, test_db, sample_events):
        """Empty query returns empty results."""
        results = hybrid_search(test_db, "", query_embedding=None)
        assert results == []

    def test_whitespace_query_returns_empty(self, test_db, sample_events):
        """Whitespace-only query returns empty results."""
        results = hybrid_search(test_db, "   ", query_embedding=None)
        assert results == []

    def test_fts_only_when_no_embedding(self, test_db, sample_events):
        """Falls back to FTS-only when no embedding provided."""
        results = hybrid_search(test_db, "SQLite", query_embedding=None)
        assert len(results) > 0
        for r in results:
            assert r.fts_rank is not None
            assert r.vec_rank is None

    @patch("cortex.hybrid_search.search_similar")
    def test_vec_only_when_no_query(self, mock_search_similar, test_db, sample_events):
        """Falls back to vec-only when empty query but embedding provided."""
        mock_search_similar.return_value = [
            VectorSearchResult(event_id="evt1", distance=0.5, similarity=0.85),
        ]

        results = hybrid_search(test_db, "", query_embedding=[0.1] * 384)

        assert len(results) == 1
        assert results[0].fts_rank is None
        assert results[0].vec_rank == 1

    @patch("cortex.hybrid_search.search_similar")
    @patch("cortex.hybrid_search.search")
    def test_combines_fts_and_vec(self, mock_fts, mock_vec, test_db, sample_events):
        """Combines FTS and vector results using RRF."""
        # FTS returns evt1, evt2
        event1 = Event(
            id="evt1",
            type=EventType.DECISION_MADE,
            content="SQLite",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        event2 = Event(
            id="evt2",
            type=EventType.KNOWLEDGE_ACQUIRED,
            content="Python",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        mock_fts.return_value = [
            SearchResult(event=event1, score=2.5, snippet="SQLite"),
            SearchResult(event=event2, score=1.5, snippet="Python"),
        ]

        # Vec returns evt2, evt3
        mock_vec.return_value = [
            VectorSearchResult(event_id="evt2", distance=0.3, similarity=0.9),
            VectorSearchResult(event_id="evt3", distance=0.5, similarity=0.8),
        ]

        results = hybrid_search(test_db, "test", query_embedding=[0.1] * 384, limit=10)

        # evt2 should rank highest (appears in both)
        assert len(results) == 3  # evt1, evt2, evt3
        assert results[0].event.id == "evt2"  # Best RRF score
        assert results[0].fts_rank == 2
        assert results[0].vec_rank == 1

    def test_respects_limit(self, test_db, sample_events):
        """Respects the limit parameter."""
        results = hybrid_search(test_db, "SQLite OR Python OR testing", limit=2)
        assert len(results) <= 2

    @patch("cortex.hybrid_search.search_similar")
    def test_filters_by_event_type(self, mock_vec, test_db, sample_events):
        """Filters results by event type."""
        mock_vec.return_value = []

        results = hybrid_search(
            test_db,
            "SQLite",
            event_type=EventType.DECISION_MADE,
        )

        # Only DECISION_MADE events should appear
        for r in results:
            assert r.event.type == EventType.DECISION_MADE

    @patch("cortex.hybrid_search.search_similar")
    def test_filters_by_branch(self, mock_vec, test_db, sample_events):
        """Filters results by git branch."""
        mock_vec.return_value = []

        results = hybrid_search(test_db, "error", branch="feature")

        # Only feature branch events should appear
        for r in results:
            assert r.event.git_branch == "feature" or r.event.git_branch in ("", None)

    def test_custom_k_parameter(self, test_db, sample_events):
        """Custom k parameter affects RRF scores."""
        results_k60 = hybrid_search(test_db, "SQLite", k=60)
        results_k10 = hybrid_search(test_db, "SQLite", k=10)

        # Different k values produce different scores
        if results_k60 and results_k10:
            assert results_k60[0].rrf_score != results_k10[0].rrf_score

    def test_custom_weights(self, test_db, sample_events):
        """Custom weights affect RRF scores."""
        results_fts_heavy = hybrid_search(
            test_db,
            "SQLite",
            fts_weight=0.9,
            vec_weight=0.1,
        )
        results_balanced = hybrid_search(
            test_db,
            "SQLite",
            fts_weight=0.5,
            vec_weight=0.5,
        )

        # Different weights produce different scores
        if results_fts_heavy and results_balanced:
            # FTS-heavy should give higher scores for FTS-only results
            assert results_fts_heavy[0].rrf_score != results_balanced[0].rrf_score


# =============================================================================
# Test Semantic Search
# =============================================================================


class TestSearchSemantic:
    """Tests for search_semantic function."""

    @patch("cortex.hybrid_search.search_similar")
    def test_returns_vec_results(self, mock_search_similar, test_db, sample_events):
        """Returns vector similarity results."""
        mock_search_similar.return_value = [
            VectorSearchResult(event_id="evt1", distance=0.3, similarity=0.9),
            VectorSearchResult(event_id="evt2", distance=0.5, similarity=0.8),
        ]

        results = search_semantic(test_db, [0.1] * 384, limit=10)

        assert len(results) == 2
        assert results[0].similarity == 0.9
        assert results[0].fts_rank is None

    @patch("cortex.hybrid_search.search_similar")
    def test_uses_similarity_as_score(self, mock_search_similar, test_db, sample_events):
        """Uses vector similarity as the RRF score."""
        mock_search_similar.return_value = [
            VectorSearchResult(event_id="evt1", distance=0.3, similarity=0.9),
        ]

        results = search_semantic(test_db, [0.1] * 384)

        assert results[0].rrf_score == 0.9

    @patch("cortex.hybrid_search.search_similar")
    def test_returns_empty_for_no_matches(self, mock_search_similar, test_db):
        """Returns empty list when no matches found."""
        mock_search_similar.return_value = []

        results = search_semantic(test_db, [0.1] * 384)

        assert results == []

    @patch("cortex.hybrid_search.search_similar")
    def test_filters_by_event_type(self, mock_search_similar, test_db, sample_events):
        """Passes event_type filter to search_similar."""
        mock_search_similar.return_value = []

        search_semantic(test_db, [0.1] * 384, event_type=EventType.DECISION_MADE)

        # Verify the filter was passed
        mock_search_similar.assert_called_once()
        call_kwargs = mock_search_similar.call_args[1]
        assert call_kwargs["event_type"] == "decision_made"

    @patch("cortex.hybrid_search.search_similar")
    def test_filters_by_branch(self, mock_search_similar, test_db, sample_events):
        """Passes branch filter to search_similar."""
        mock_search_similar.return_value = []

        search_semantic(test_db, [0.1] * 384, branch="main")

        call_kwargs = mock_search_similar.call_args[1]
        assert call_kwargs["git_branch"] == "main"

    @patch("cortex.hybrid_search.search_similar")
    def test_respects_limit(self, mock_search_similar, test_db, sample_events):
        """Respects the limit parameter."""
        mock_search_similar.return_value = [
            VectorSearchResult(event_id=f"evt{i}", distance=0.1 * i, similarity=0.9 - 0.1 * i) for i in range(1, 6)
        ]

        results = search_semantic(test_db, [0.1] * 384, limit=2)

        assert len(results) == 2


# =============================================================================
# Test Integration
# =============================================================================


class TestHybridSearchIntegration:
    """Integration tests for hybrid search."""

    def test_real_fts_search(self, test_db, sample_events):
        """Tests with real FTS5 search."""
        results = hybrid_search(test_db, "SQLite database")

        assert len(results) > 0
        # First result should be about SQLite
        assert "SQLite" in results[0].event.content

    def test_results_sorted_by_rrf_score(self, test_db, sample_events):
        """Results are sorted by RRF score descending."""
        results = hybrid_search(test_db, "SQLite OR pytest OR Python")

        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].rrf_score >= results[i + 1].rrf_score

    def test_snippets_contain_highlights(self, test_db, sample_events):
        """FTS snippets contain match highlights."""
        results = hybrid_search(test_db, "SQLite")

        if results and results[0].fts_rank is not None:
            # FTS results should have highlighted snippets
            assert "**" in results[0].snippet or "SQLite" in results[0].snippet

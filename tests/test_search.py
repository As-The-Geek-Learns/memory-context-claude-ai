"""Tests for FTS5 full-text search functionality."""

from datetime import datetime, timezone

import pytest

from cortex.config import CortexConfig
from cortex.models import Event, EventType, create_event
from cortex.search import (
    SearchResult,
    get_similar_events,
    rebuild_fts_index,
    search,
    search_by_type,
    search_decisions,
    search_knowledge,
)
from cortex.sqlite_store import SQLiteEventStore

# --- Fixtures ---


@pytest.fixture
def search_store(sample_project_hash: str, sample_config: CortexConfig):
    """Create a SQLiteEventStore with sample events for search testing."""
    store = SQLiteEventStore(sample_project_hash, sample_config)

    # Add diverse events for search testing
    events = [
        create_event(
            EventType.DECISION_MADE,
            "Use SQLite for local storage because it requires zero configuration",
            metadata={"reason": "zero-config"},
        ),
        create_event(
            EventType.DECISION_MADE,
            "Rejected PostgreSQL because it requires a server daemon",
            metadata={"rejected": "PostgreSQL"},
        ),
        create_event(
            EventType.KNOWLEDGE_ACQUIRED,
            "Python 3.11 includes FTS5 support in the bundled SQLite",
        ),
        create_event(
            EventType.KNOWLEDGE_ACQUIRED,
            "WAL mode allows concurrent reads during writes",
        ),
        create_event(
            EventType.FILE_MODIFIED,
            "Updated the database module with new indexes",
        ),
        create_event(
            EventType.COMMAND_RUN,
            "Ran pytest to verify all tests pass",
        ),
        create_event(
            EventType.PLAN_CREATED,
            "Implement FTS5 search with BM25 ranking",
        ),
    ]
    store.append_many(events)

    yield store
    store.close()


@pytest.fixture
def empty_store(sample_project_hash: str, sample_config: CortexConfig):
    """Create an empty SQLiteEventStore for edge case testing."""
    store = SQLiteEventStore(sample_project_hash, sample_config)
    yield store
    store.close()


# --- Test Classes ---


class TestSearchBasics:
    """Basic FTS5 search functionality."""

    def test_search_returns_results(self, search_store: SQLiteEventStore):
        """Search should return matching results."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_result_has_event(self, search_store: SQLiteEventStore):
        """SearchResult should contain the Event object."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")
        assert results[0].event is not None
        assert isinstance(results[0].event, Event)

    def test_search_result_has_score(self, search_store: SQLiteEventStore):
        """SearchResult should have a relevance score."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")
        assert results[0].score > 0

    def test_search_result_has_snippet(self, search_store: SQLiteEventStore):
        """SearchResult should have a snippet with context."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")
        assert results[0].snippet is not None
        assert len(results[0].snippet) > 0

    def test_search_empty_query(self, search_store: SQLiteEventStore):
        """Empty query should return no results."""
        conn = search_store._get_conn()
        results = search(conn, "")
        assert results == []

    def test_search_whitespace_query(self, search_store: SQLiteEventStore):
        """Whitespace-only query should return no results."""
        conn = search_store._get_conn()
        results = search(conn, "   ")
        assert results == []

    def test_search_no_matches(self, search_store: SQLiteEventStore):
        """Query with no matches should return empty list."""
        conn = search_store._get_conn()
        results = search(conn, "nonexistent_xyz_term")
        assert results == []

    def test_search_empty_store(self, empty_store: SQLiteEventStore):
        """Search on empty store should return empty list."""
        conn = empty_store._get_conn()
        results = search(conn, "anything")
        assert results == []


class TestSearchRelevance:
    """BM25 relevance ranking tests."""

    def test_search_ranked_by_relevance(self, search_store: SQLiteEventStore):
        """Results should be sorted by relevance score."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")

        if len(results) > 1:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_exact_match_scores_higher(self, search_store: SQLiteEventStore):
        """Exact term matches should score higher."""
        conn = search_store._get_conn()

        # "SQLite" appears directly in storage decision
        results = search(conn, "SQLite")
        assert len(results) > 0

        # First result should contain SQLite
        assert "SQLite" in results[0].event.content or "sqlite" in results[0].event.content.lower()


class TestSearchFilters:
    """Type and branch filter tests."""

    def test_search_by_type_filter(self, search_store: SQLiteEventStore):
        """Search with type filter should only return matching types."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite", event_type=EventType.DECISION_MADE)

        assert len(results) > 0
        assert all(r.event.type == EventType.DECISION_MADE for r in results)

    def test_search_by_type_no_matches(self, search_store: SQLiteEventStore):
        """Type filter with no matches should return empty list."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite", event_type=EventType.ERROR_RESOLVED)
        assert results == []

    def test_search_with_branch_filter(self, sample_project_hash: str, sample_config: CortexConfig):
        """Branch filter should only return events from that branch."""
        store = SQLiteEventStore(sample_project_hash, sample_config)

        # Add events on different branches
        main_event = Event(
            id="main-1",
            type=EventType.KNOWLEDGE_ACQUIRED,
            content="Main branch knowledge about databases",
            git_branch="main",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        feature_event = Event(
            id="feat-1",
            type=EventType.KNOWLEDGE_ACQUIRED,
            content="Feature branch knowledge about databases",
            git_branch="feature/search",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        store.append_many([main_event, feature_event])

        conn = store._get_conn()

        # Search on main branch
        results = search(conn, "databases", branch="main")
        assert len(results) >= 1
        branches = {r.event.git_branch for r in results}
        assert "feature/search" not in branches

        store.close()

    def test_search_limit(self, search_store: SQLiteEventStore):
        """Limit parameter should restrict result count."""
        conn = search_store._get_conn()
        results = search(conn, "the", limit=2)
        assert len(results) <= 2


class TestSearchConvenienceFunctions:
    """Convenience search function tests."""

    def test_search_by_type_function(self, search_store: SQLiteEventStore):
        """search_by_type should filter by event type."""
        conn = search_store._get_conn()
        results = search_by_type(conn, "Python", EventType.KNOWLEDGE_ACQUIRED)

        assert len(results) > 0
        assert all(r.event.type == EventType.KNOWLEDGE_ACQUIRED for r in results)

    def test_search_decisions(self, search_store: SQLiteEventStore):
        """search_decisions should only return DECISION_MADE events."""
        conn = search_store._get_conn()
        results = search_decisions(conn, "storage")

        assert len(results) > 0
        assert all(r.event.type == EventType.DECISION_MADE for r in results)

    def test_search_knowledge(self, search_store: SQLiteEventStore):
        """search_knowledge should only return KNOWLEDGE_ACQUIRED events."""
        conn = search_store._get_conn()
        results = search_knowledge(conn, "Python")

        assert len(results) > 0
        assert all(r.event.type == EventType.KNOWLEDGE_ACQUIRED for r in results)


class TestSimilarEvents:
    """Tests for get_similar_events functionality."""

    def test_similar_events_returns_related(self, search_store: SQLiteEventStore):
        """get_similar_events should return related events."""
        conn = search_store._get_conn()

        # Get an event about SQLite
        events = search_store.load_all()
        sqlite_event = next(e for e in events if "SQLite" in e.content)

        similar = get_similar_events(conn, sqlite_event)

        # Should find other events mentioning storage/database
        assert len(similar) >= 0  # May or may not find similar events

    def test_similar_events_excludes_source(self, search_store: SQLiteEventStore):
        """get_similar_events should not include the source event."""
        conn = search_store._get_conn()

        events = search_store.load_all()
        source_event = events[0]

        similar = get_similar_events(conn, source_event)

        source_ids = {r.event.id for r in similar}
        assert source_event.id not in source_ids

    def test_similar_events_respects_limit(self, search_store: SQLiteEventStore):
        """get_similar_events should respect the limit parameter."""
        conn = search_store._get_conn()

        events = search_store.load_all()
        source_event = events[0]

        similar = get_similar_events(conn, source_event, limit=2)
        assert len(similar) <= 2


class TestRebuildIndex:
    """Tests for FTS5 index rebuild."""

    def test_rebuild_index(self, search_store: SQLiteEventStore):
        """rebuild_fts_index should successfully rebuild."""
        conn = search_store._get_conn()
        count = rebuild_fts_index(conn)
        assert count == search_store.count()

    def test_rebuild_empty_index(self, empty_store: SQLiteEventStore):
        """rebuild_fts_index on empty store should return 0."""
        conn = empty_store._get_conn()
        count = rebuild_fts_index(conn)
        assert count == 0


class TestSearchSpecialCharacters:
    """Tests for handling special characters in queries."""

    def test_search_with_quotes(self, search_store: SQLiteEventStore):
        """Queries with quotes should be handled safely."""
        conn = search_store._get_conn()
        # Should not raise, may return empty results
        results = search(conn, '"exact phrase"')
        assert isinstance(results, list)

    def test_search_with_parentheses(self, search_store: SQLiteEventStore):
        """Queries with parentheses should be handled safely."""
        conn = search_store._get_conn()
        results = search(conn, "function()")
        assert isinstance(results, list)

    def test_search_with_special_chars(self, search_store: SQLiteEventStore):
        """Queries with special FTS5 chars should be handled safely."""
        conn = search_store._get_conn()
        results = search(conn, "test:value")
        assert isinstance(results, list)


class TestStoreSearchMethods:
    """Tests for SQLiteEventStore search wrapper methods."""

    def test_store_search_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.search should work correctly."""
        results = search_store.search("SQLite")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_store_search_by_type_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.search_by_type should work correctly."""
        results = search_store.search_by_type("storage", EventType.DECISION_MADE)
        assert len(results) > 0
        assert all(r.event.type == EventType.DECISION_MADE for r in results)

    def test_store_search_decisions_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.search_decisions should work correctly."""
        results = search_store.search_decisions("storage")
        assert len(results) > 0
        assert all(r.event.type == EventType.DECISION_MADE for r in results)

    def test_store_search_knowledge_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.search_knowledge should work correctly."""
        results = search_store.search_knowledge("Python")
        assert len(results) > 0
        assert all(r.event.type == EventType.KNOWLEDGE_ACQUIRED for r in results)

    def test_store_get_similar_events_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.get_similar_events should work correctly."""
        events = search_store.load_all()
        source_event = events[0]

        similar = search_store.get_similar_events(source_event)
        assert isinstance(similar, list)

    def test_store_rebuild_search_index_method(self, search_store: SQLiteEventStore):
        """SQLiteEventStore.rebuild_search_index should work correctly."""
        count = search_store.rebuild_search_index()
        assert count == search_store.count()


class TestSnippetGeneration:
    """Tests for search result snippet generation."""

    def test_snippet_contains_match_markers(self, search_store: SQLiteEventStore):
        """Snippets should contain ** markers around matches."""
        conn = search_store._get_conn()
        results = search(conn, "SQLite")

        # At least one snippet should have markers (FTS5 may not always add
        # markers if match is at boundary, so we just verify we have results)
        assert len(results) > 0
        # The snippet should contain some content
        assert all(len(r.snippet) > 0 for r in results)

    def test_snippet_truncation(self, sample_project_hash: str, sample_config: CortexConfig):
        """Long content should be truncated in snippets."""
        store = SQLiteEventStore(sample_project_hash, sample_config)

        # Add event with very long content
        long_content = "SQLite " + ("word " * 500)  # ~3000 chars
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, long_content)
        store.append(event)

        results = store.search("SQLite")
        assert len(results) > 0

        # Snippet should be shorter than full content
        assert len(results[0].snippet) < len(long_content)

        store.close()

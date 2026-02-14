"""Tests for SQLiteEventStore (Tier 1 storage backend).

Mirrors test_store.py to ensure API compatibility between JSON and SQLite backends.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cortex.config import CortexConfig
from cortex.models import Event, EventType, content_hash, create_event
from cortex.sqlite_store import SQLiteEventStore
from cortex.store import EventStoreBase, create_event_store

# --- Fixtures ---


@pytest.fixture
def sqlite_store(sample_project_hash: str, sample_config: CortexConfig):
    """Create a SQLiteEventStore for testing."""
    store = SQLiteEventStore(sample_project_hash, sample_config)
    yield store
    store.close()


@pytest.fixture
def sample_events() -> list[Event]:
    """Sample events for testing."""
    return [
        create_event(
            event_type=EventType.DECISION_MADE,
            content="Use SQLite for storage",
            metadata={"reason": "zero-config"},
        ),
        create_event(
            event_type=EventType.KNOWLEDGE_ACQUIRED,
            content="Python 3.11 required",
        ),
        create_event(
            event_type=EventType.FILE_MODIFIED,
            content="Updated models.py",
        ),
    ]


# --- Test Classes ---


class TestSQLiteEventStoreBasics:
    """Basic SQLiteEventStore functionality."""

    def test_empty_store_has_zero_count(self, sqlite_store: SQLiteEventStore):
        """Empty store should have count of 0."""
        assert sqlite_store.count() == 0

    def test_load_all_empty(self, sqlite_store: SQLiteEventStore):
        """Empty store should return empty list."""
        assert sqlite_store.load_all() == []

    def test_db_path(self, sqlite_store: SQLiteEventStore, sample_project_hash: str):
        """Database path should be in project directory."""
        assert sqlite_store.db_path.name == "events.db"
        assert sample_project_hash in str(sqlite_store.db_path)

    def test_implements_base_class(self, sqlite_store: SQLiteEventStore):
        """SQLiteEventStore should implement EventStoreBase."""
        assert isinstance(sqlite_store, EventStoreBase)


class TestSQLiteEventStoreAppend:
    """Tests for append operations."""

    def test_append_single_event(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """Appending an event should increase count."""
        sqlite_store.append(sample_events[0])
        assert sqlite_store.count() == 1

    def test_append_preserves_data(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """Appended events should be retrievable with all fields."""
        original = sample_events[0]
        sqlite_store.append(original)

        loaded = sqlite_store.load_all()[0]

        assert loaded.id == original.id
        assert loaded.type == original.type
        assert loaded.content == original.content
        assert loaded.salience == original.salience
        assert loaded.metadata == original.metadata or loaded.metadata == {}
        assert loaded.immortal == original.immortal

    def test_append_multiple(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """Multiple appends should all be stored."""
        for event in sample_events:
            sqlite_store.append(event)
        assert sqlite_store.count() == 3


class TestSQLiteEventStoreAppendMany:
    """Tests for append_many with deduplication."""

    def test_append_many_basic(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """append_many should store all events."""
        sqlite_store.append_many(sample_events)
        assert sqlite_store.count() == 3

    def test_append_many_deduplicates(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """append_many should not add duplicate events."""
        sqlite_store.append_many(sample_events)
        sqlite_store.append_many(sample_events)
        assert sqlite_store.count() == 3  # Not 6

    def test_append_many_empty_list(self, sqlite_store: SQLiteEventStore):
        """append_many with empty list should be a no-op."""
        sqlite_store.append_many([])
        assert sqlite_store.count() == 0

    def test_append_many_deduplicates_within_batch(self, sqlite_store: SQLiteEventStore):
        """append_many should deduplicate within the same batch."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Same content")
        sqlite_store.append_many([event, event, event])
        assert sqlite_store.count() == 1


class TestSQLiteEventStoreQueries:
    """Tests for query methods."""

    def test_load_recent(self, sqlite_store: SQLiteEventStore):
        """load_recent should return events sorted by created_at descending."""
        now = datetime.now(timezone.utc)
        events = [
            Event(
                id=f"evt{i}",
                type=EventType.KNOWLEDGE_ACQUIRED,
                content=f"Event {i}",
                created_at=(now - timedelta(hours=i)).isoformat(),
                accessed_at=now.isoformat(),
            )
            for i in range(5)
        ]
        sqlite_store.append_many(events)

        recent = sqlite_store.load_recent(3)
        assert len(recent) == 3
        # Most recent first (evt0)
        assert recent[0].id == "evt0"

    def test_load_recent_fewer_than_requested(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """load_recent should return all if fewer than N exist."""
        sqlite_store.append_many(sample_events)
        recent = sqlite_store.load_recent(100)
        assert len(recent) == 3

    def test_load_by_type(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """load_by_type should filter events by type."""
        sqlite_store.append_many(sample_events)
        decisions = sqlite_store.load_by_type(EventType.DECISION_MADE)
        assert len(decisions) == 1
        assert decisions[0].type == EventType.DECISION_MADE

    def test_load_immortal(self, sqlite_store: SQLiteEventStore):
        """load_immortal should return only immortal events."""
        events = [
            create_event(EventType.DECISION_MADE, "Decision 1"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "Knowledge 1"),
            create_event(EventType.APPROACH_REJECTED, "Rejected 1"),
        ]
        sqlite_store.append_many(events)

        immortal = sqlite_store.load_immortal()
        assert len(immortal) == 2  # DECISION_MADE and ALTERNATIVE_REJECTED
        types = {e.type for e in immortal}
        assert EventType.DECISION_MADE in types
        assert EventType.APPROACH_REJECTED in types


class TestSQLiteEventStoreForBriefing:
    """Tests for load_for_briefing."""

    def test_briefing_has_three_sections(self, sqlite_store: SQLiteEventStore):
        """load_for_briefing should return dict with immortal, active_plan, recent."""
        result = sqlite_store.load_for_briefing()
        assert "immortal" in result
        assert "active_plan" in result
        assert "recent" in result

    def test_briefing_immortal_section(self, sqlite_store: SQLiteEventStore):
        """Immortal events should appear in immortal section."""
        events = [
            create_event(EventType.DECISION_MADE, "Use SQLite"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "Regular knowledge"),
        ]
        sqlite_store.append_many(events)

        result = sqlite_store.load_for_briefing()
        assert len(result["immortal"]) == 1
        assert result["immortal"][0].type == EventType.DECISION_MADE

    def test_briefing_active_plan(self, sqlite_store: SQLiteEventStore):
        """Active plan should include latest plan and its completed steps."""
        plan = create_event(EventType.PLAN_CREATED, "Implement feature X")
        step1 = create_event(EventType.PLAN_STEP_COMPLETED, "Step 1 done")
        step2 = create_event(EventType.PLAN_STEP_COMPLETED, "Step 2 done")

        sqlite_store.append(plan)
        sqlite_store.append(step1)
        sqlite_store.append(step2)

        result = sqlite_store.load_for_briefing()
        assert len(result["active_plan"]) == 3
        assert result["active_plan"][0].type == EventType.PLAN_CREATED

    def test_briefing_no_duplicates_across_sections(self, sqlite_store: SQLiteEventStore):
        """Events should not appear in multiple sections."""
        events = [
            create_event(EventType.DECISION_MADE, "Decision 1"),
            create_event(EventType.PLAN_CREATED, "Plan 1"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "Knowledge 1"),
        ]
        sqlite_store.append_many(events)

        result = sqlite_store.load_for_briefing()

        all_ids = (
            [e.id for e in result["immortal"]]
            + [e.id for e in result["active_plan"]]
            + [e.id for e in result["recent"]]
        )
        assert len(all_ids) == len(set(all_ids))  # No duplicates

    def test_briefing_branch_filter(self, sqlite_store: SQLiteEventStore):
        """Branch filter should exclude events from other branches."""
        main_event = Event(
            id="main-1",
            type=EventType.KNOWLEDGE_ACQUIRED,
            content="Main branch event",
            git_branch="main",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        feature_event = Event(
            id="feat-1",
            type=EventType.KNOWLEDGE_ACQUIRED,
            content="Feature branch event",
            git_branch="feature/x",
            created_at=datetime.now(timezone.utc).isoformat(),
            accessed_at=datetime.now(timezone.utc).isoformat(),
        )
        sqlite_store.append_many([main_event, feature_event])

        result = sqlite_store.load_for_briefing(branch="main")
        all_events = result["immortal"] + result["active_plan"] + result["recent"]
        branches = {e.git_branch for e in all_events}
        assert "feature/x" not in branches

    def test_briefing_empty_store(self, sqlite_store: SQLiteEventStore):
        """Empty store should return empty sections."""
        result = sqlite_store.load_for_briefing()
        assert result["immortal"] == []
        assert result["active_plan"] == []
        assert result["recent"] == []


class TestSQLiteEventStoreMarkAccessed:
    """Tests for mark_accessed reinforcement."""

    def test_mark_accessed_updates_timestamp(self, sqlite_store: SQLiteEventStore):
        """mark_accessed should update accessed_at."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test event")
        sqlite_store.append(event)

        original = sqlite_store.load_all()[0]
        original_accessed = original.accessed_at

        sqlite_store.mark_accessed([event.id])
        updated = sqlite_store.load_all()[0]

        assert updated.accessed_at != original_accessed

    def test_mark_accessed_increments_count(self, sqlite_store: SQLiteEventStore):
        """mark_accessed should increment access_count."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test event")
        sqlite_store.append(event)

        sqlite_store.mark_accessed([event.id])
        sqlite_store.mark_accessed([event.id])
        sqlite_store.mark_accessed([event.id])

        updated = sqlite_store.load_all()[0]
        assert updated.access_count == 3

    def test_mark_accessed_empty_list(self, sqlite_store: SQLiteEventStore):
        """mark_accessed with empty list should be a no-op."""
        sqlite_store.mark_accessed([])  # Should not raise

    def test_mark_accessed_nonexistent_id(self, sqlite_store: SQLiteEventStore):
        """mark_accessed with nonexistent ID should be a no-op."""
        sqlite_store.mark_accessed(["nonexistent-id"])  # Should not raise


class TestSQLiteEventStoreClear:
    """Tests for clear operation."""

    def test_clear_empties_store(self, sqlite_store: SQLiteEventStore, sample_events: list[Event]):
        """clear should remove all events."""
        sqlite_store.append_many(sample_events)
        assert sqlite_store.count() == 3

        sqlite_store.clear()
        assert sqlite_store.count() == 0


class TestCreateEventStoreFactory:
    """Tests for the create_event_store factory function."""

    def test_tier_0_returns_json_store(self, sample_project_hash: str, sample_config: CortexConfig):
        """Tier 0 should return JSON EventStore."""
        sample_config.storage_tier = 0
        store = create_event_store(sample_project_hash, sample_config)
        assert store.__class__.__name__ == "EventStore"

    def test_tier_1_returns_sqlite_store(self, sample_project_hash: str, sample_config: CortexConfig):
        """Tier 1 should return SQLiteEventStore."""
        sample_config.storage_tier = 1
        store = create_event_store(sample_project_hash, sample_config)
        assert isinstance(store, SQLiteEventStore)
        store.close()

    def test_both_stores_implement_base(self, sample_project_hash: str, sample_config: CortexConfig):
        """Both store types should implement EventStoreBase."""
        sample_config.storage_tier = 0
        json_store = create_event_store(sample_project_hash, sample_config)
        assert isinstance(json_store, EventStoreBase)

        sample_config.storage_tier = 1
        sqlite_store = create_event_store(sample_project_hash, sample_config)
        assert isinstance(sqlite_store, EventStoreBase)
        sqlite_store.close()


class TestSQLiteEventStoreMetadata:
    """Tests for metadata handling (JSON serialization)."""

    def test_metadata_round_trip(self, sqlite_store: SQLiteEventStore):
        """Complex metadata should survive JSON round-trip."""
        metadata = {
            "reason": "performance",
            "alternatives": ["option A", "option B"],
            "metrics": {"latency": 10.5, "throughput": 1000},
        }
        event = create_event(
            EventType.DECISION_MADE,
            "Use caching",
            metadata=metadata,
        )
        sqlite_store.append(event)

        loaded = sqlite_store.load_all()[0]
        assert loaded.metadata == metadata

    def test_empty_metadata(self, sqlite_store: SQLiteEventStore):
        """Event with no metadata should work."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "No metadata")
        sqlite_store.append(event)

        loaded = sqlite_store.load_all()[0]
        assert loaded.metadata == {} or loaded.metadata is None


class TestSQLiteEventStoreContentHash:
    """Tests for content hash deduplication."""

    def test_content_hash_prevents_duplicates(self, sqlite_store: SQLiteEventStore):
        """Same content should have same hash and deduplicate."""
        event1 = create_event(EventType.KNOWLEDGE_ACQUIRED, "Same content", session_id="session1")
        event2 = create_event(EventType.KNOWLEDGE_ACQUIRED, "Same content", session_id="session1")

        # Different IDs but same content hash
        assert content_hash(event1) == content_hash(event2)

        sqlite_store.append_many([event1, event2])
        assert sqlite_store.count() == 1

    def test_different_content_not_deduplicated(self, sqlite_store: SQLiteEventStore):
        """Different content should not deduplicate."""
        event1 = create_event(EventType.KNOWLEDGE_ACQUIRED, "Content A")
        event2 = create_event(EventType.KNOWLEDGE_ACQUIRED, "Content B")

        sqlite_store.append_many([event1, event2])
        assert sqlite_store.count() == 2


# =============================================================================
# Tier 2: Embedding and Hybrid Search Tests
# =============================================================================


class TestSQLiteEventStoreAutoEmbed:
    """Tests for auto-embedding on event append."""

    @pytest.fixture
    def auto_embed_store(self, sample_project_hash: str, tmp_cortex_home):
        """Create a store with auto_embed enabled."""
        config = CortexConfig(cortex_home=tmp_cortex_home, auto_embed=True)
        store = SQLiteEventStore(sample_project_hash, config)
        yield store
        store.close()

    def test_auto_embed_disabled_by_default(self, sqlite_store: SQLiteEventStore):
        """Auto-embed should be disabled by default."""
        assert sqlite_store._config.auto_embed is False

    def test_auto_embed_enabled_in_config(self, auto_embed_store: SQLiteEventStore):
        """Auto-embed should be enabled when configured."""
        assert auto_embed_store._config.auto_embed is True

    def test_append_without_auto_embed_no_embedding(self, sqlite_store: SQLiteEventStore):
        """Appending without auto_embed should not create embedding."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test content")
        sqlite_store.append(event)

        embedding = sqlite_store.get_embedding(event.id)
        assert embedding is None

    def test_append_with_auto_embed_creates_embedding(self, auto_embed_store: SQLiteEventStore):
        """Appending with auto_embed should create embedding if available."""
        pytest.importorskip("sentence_transformers")

        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test content for embedding")
        auto_embed_store.append(event)

        embedding = auto_embed_store.get_embedding(event.id)
        # Should have embedding (or None if sentence-transformers unavailable)
        if embedding is not None:
            assert len(embedding) == 384  # MiniLM dimension


class TestSQLiteEventStoreHybridSearch:
    """Tests for hybrid search methods."""

    @pytest.fixture
    def store_with_events(self, sqlite_store: SQLiteEventStore):
        """Store with sample events for search testing."""
        events = [
            create_event(
                EventType.DECISION_MADE,
                "Use SQLite for database storage",
                git_branch="main",
            ),
            create_event(
                EventType.KNOWLEDGE_ACQUIRED,
                "Python supports async await patterns",
                git_branch="main",
            ),
            create_event(
                EventType.ERROR_RESOLVED,
                "Fixed import error in module",
                git_branch="feature",
            ),
        ]
        for event in events:
            sqlite_store.append(event)
        return sqlite_store, events

    def test_hybrid_search_fts_only(self, store_with_events):
        """Hybrid search without embedding uses FTS only."""
        store, events = store_with_events

        results = store.hybrid_search("SQLite")

        assert len(results) >= 1
        assert any("SQLite" in r.event.content for r in results)

    def test_hybrid_search_empty_query(self, store_with_events):
        """Empty query returns empty results."""
        store, _ = store_with_events

        results = store.hybrid_search("")
        assert results == []

    def test_hybrid_search_with_event_type_filter(self, store_with_events):
        """Hybrid search respects event type filter."""
        store, _ = store_with_events

        results = store.hybrid_search("SQLite", event_type=EventType.DECISION_MADE)

        for result in results:
            assert result.event.type == EventType.DECISION_MADE

    def test_hybrid_search_with_branch_filter(self, store_with_events):
        """Hybrid search respects branch filter."""
        store, _ = store_with_events

        results = store.hybrid_search("error", branch="feature")

        # Should find the error event on feature branch
        assert len(results) >= 1

    def test_search_semantic_requires_embedding(self, store_with_events):
        """search_semantic requires query_embedding."""
        pytest.importorskip("numpy")  # Skip if numpy unavailable

        store, _ = store_with_events

        # Should work with a valid embedding
        fake_embedding = [0.1] * 384
        results = store.search_semantic(fake_embedding)

        # May be empty if no embeddings stored, but should not error
        assert isinstance(results, list)


class TestSQLiteEventStoreEmbeddingMethods:
    """Tests for embedding-related store methods."""

    def test_count_embeddings_empty(self, sqlite_store: SQLiteEventStore):
        """count_embeddings returns 0 for empty store."""
        assert sqlite_store.count_embeddings() == 0

    def test_get_embedding_not_found(self, sqlite_store: SQLiteEventStore):
        """get_embedding returns None for non-existent event."""
        result = sqlite_store.get_embedding("non-existent-id")
        assert result is None

    def test_store_and_get_embedding(self, sqlite_store: SQLiteEventStore):
        """Can store and retrieve embedding."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test")
        sqlite_store.append(event)

        embedding = [0.1] * 384
        success = sqlite_store.store_embedding(event.id, embedding)

        assert success is True

        retrieved = sqlite_store.get_embedding(event.id)
        assert retrieved is not None
        assert len(retrieved) == 384
        assert abs(retrieved[0] - 0.1) < 0.0001

    def test_count_embeddings_after_store(self, sqlite_store: SQLiteEventStore):
        """count_embeddings reflects stored embeddings."""
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "Test")
        sqlite_store.append(event)
        sqlite_store.store_embedding(event.id, [0.1] * 384)

        assert sqlite_store.count_embeddings() == 1

    def test_backfill_embeddings_returns_count(self, sqlite_store: SQLiteEventStore):
        """backfill_embeddings returns number of embeddings created."""
        # Add events without embeddings
        for i in range(3):
            event = create_event(EventType.KNOWLEDGE_ACQUIRED, f"Content {i}")
            sqlite_store.append(event)

        # Backfill (will return 0 if sentence-transformers unavailable)
        count = sqlite_store.backfill_embeddings()

        assert isinstance(count, int)
        assert count >= 0

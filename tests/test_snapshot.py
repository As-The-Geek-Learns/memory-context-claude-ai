"""Tests for snapshot caching functionality."""

from datetime import datetime, timedelta, timezone

import pytest

from cortex.config import CortexConfig
from cortex.models import EventType, create_event
from cortex.snapshot import (
    Snapshot,
    cleanup_expired_snapshots,
    get_snapshot_stats,
    get_valid_snapshot,
    invalidate_snapshots,
    save_snapshot,
)
from cortex.sqlite_store import SQLiteEventStore

# --- Fixtures ---


@pytest.fixture
def snapshot_store(sample_project_hash: str, sample_config: CortexConfig):
    """Create a SQLiteEventStore for snapshot testing."""
    store = SQLiteEventStore(sample_project_hash, sample_config)
    yield store
    store.close()


# --- Test Classes ---


class TestSaveSnapshot:
    """Tests for save_snapshot function."""

    def test_save_snapshot_returns_id(self, snapshot_store: SQLiteEventStore):
        """save_snapshot should return a valid row ID."""
        conn = snapshot_store._get_conn()
        row_id = save_snapshot(
            conn=conn,
            branch="main",
            markdown="# Test Briefing",
            event_ids=["event-1", "event-2"],
            last_event_id="event-1",
        )
        assert row_id > 0

    def test_save_snapshot_stores_markdown(self, snapshot_store: SQLiteEventStore):
        """Saved snapshot should store the markdown content."""
        conn = snapshot_store._get_conn()
        markdown = "# Decisions\n\n- Use SQLite"
        save_snapshot(
            conn=conn,
            branch="main",
            markdown=markdown,
            event_ids=["event-1"],
            last_event_id="event-1",
        )

        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is not None
        assert snapshot.briefing_markdown == markdown

    def test_save_snapshot_stores_event_ids(self, snapshot_store: SQLiteEventStore):
        """Saved snapshot should store the event IDs as JSON."""
        conn = snapshot_store._get_conn()
        event_ids = ["id-1", "id-2", "id-3"]
        save_snapshot(
            conn=conn,
            branch="main",
            markdown="# Test",
            event_ids=event_ids,
            last_event_id="id-1",
        )

        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is not None
        assert snapshot.event_ids == event_ids

    def test_save_snapshot_replaces_existing(self, snapshot_store: SQLiteEventStore):
        """save_snapshot should replace existing snapshot for same branch."""
        conn = snapshot_store._get_conn()

        # Save first snapshot
        save_snapshot(conn, "main", "# First", ["e1"], "e1")

        # Save second snapshot for same branch
        save_snapshot(conn, "main", "# Second", ["e2"], "e2")

        # Should only have one snapshot for main
        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is not None
        assert snapshot.briefing_markdown == "# Second"

    def test_save_snapshot_different_branches(self, snapshot_store: SQLiteEventStore):
        """Snapshots for different branches should coexist."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "main", "# Main", ["e1"], "e1")
        save_snapshot(conn, "feature", "# Feature", ["e2"], "e2")

        main_snapshot = get_valid_snapshot(conn, "main")
        feature_snapshot = get_valid_snapshot(conn, "feature")

        assert main_snapshot is not None
        assert feature_snapshot is not None
        assert main_snapshot.briefing_markdown == "# Main"
        assert feature_snapshot.briefing_markdown == "# Feature"

    def test_save_snapshot_custom_ttl(self, snapshot_store: SQLiteEventStore):
        """save_snapshot should respect custom TTL."""
        conn = snapshot_store._get_conn()

        # Save with 2 hour TTL
        save_snapshot(conn, "main", "# Test", ["e1"], "e1", ttl_hours=2.0)

        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is not None

        # Verify expires_at is approximately 2 hours from now
        expires = datetime.fromisoformat(snapshot.expires_at)
        now = datetime.now(timezone.utc)
        delta = expires - now
        assert 1.9 < delta.total_seconds() / 3600 < 2.1


class TestGetValidSnapshot:
    """Tests for get_valid_snapshot function."""

    def test_get_valid_snapshot_returns_snapshot(self, snapshot_store: SQLiteEventStore):
        """get_valid_snapshot should return a Snapshot object."""
        conn = snapshot_store._get_conn()
        save_snapshot(conn, "main", "# Test", ["e1"], "e1")

        snapshot = get_valid_snapshot(conn, "main")
        assert isinstance(snapshot, Snapshot)

    def test_get_valid_snapshot_returns_none_for_missing(self, snapshot_store: SQLiteEventStore):
        """get_valid_snapshot should return None if no snapshot exists."""
        conn = snapshot_store._get_conn()
        snapshot = get_valid_snapshot(conn, "nonexistent")
        assert snapshot is None

    def test_get_valid_snapshot_returns_none_for_expired(self, snapshot_store: SQLiteEventStore):
        """get_valid_snapshot should return None if snapshot is expired."""
        conn = snapshot_store._get_conn()

        # Save with very short TTL (negative = already expired)
        save_snapshot(conn, "main", "# Test", ["e1"], "e1", ttl_hours=-1.0)

        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is None

    def test_get_valid_snapshot_empty_branch(self, snapshot_store: SQLiteEventStore):
        """get_valid_snapshot should work with empty branch (all branches)."""
        conn = snapshot_store._get_conn()
        save_snapshot(conn, "", "# All Branches", ["e1"], "e1")

        snapshot = get_valid_snapshot(conn, "")
        assert snapshot is not None
        assert snapshot.briefing_markdown == "# All Branches"


class TestInvalidateSnapshots:
    """Tests for invalidate_snapshots function."""

    def test_invalidate_snapshots_by_branch(self, snapshot_store: SQLiteEventStore):
        """invalidate_snapshots should delete snapshot for specific branch."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "main", "# Main", ["e1"], "e1")
        save_snapshot(conn, "feature", "# Feature", ["e2"], "e2")

        count = invalidate_snapshots(conn, "main")
        assert count >= 1

        # main should be gone
        assert get_valid_snapshot(conn, "main") is None
        # feature should remain
        assert get_valid_snapshot(conn, "feature") is not None

    def test_invalidate_snapshots_all(self, snapshot_store: SQLiteEventStore):
        """invalidate_snapshots(None) should delete all snapshots."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "main", "# Main", ["e1"], "e1")
        save_snapshot(conn, "feature", "# Feature", ["e2"], "e2")

        count = invalidate_snapshots(conn, None)
        assert count >= 2

        assert get_valid_snapshot(conn, "main") is None
        assert get_valid_snapshot(conn, "feature") is None

    def test_invalidate_snapshots_also_invalidates_global(self, snapshot_store: SQLiteEventStore):
        """invalidate_snapshots should also invalidate the '' (all branches) snapshot."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "", "# Global", ["e0"], "e0")
        save_snapshot(conn, "main", "# Main", ["e1"], "e1")

        # Invalidating main should also invalidate global
        invalidate_snapshots(conn, "main")

        assert get_valid_snapshot(conn, "main") is None
        assert get_valid_snapshot(conn, "") is None


class TestCleanupExpiredSnapshots:
    """Tests for cleanup_expired_snapshots function."""

    def test_cleanup_removes_expired(self, snapshot_store: SQLiteEventStore):
        """cleanup_expired_snapshots should remove expired snapshots."""
        conn = snapshot_store._get_conn()

        # Save expired snapshot
        save_snapshot(conn, "old", "# Old", ["e1"], "e1", ttl_hours=-1.0)
        # Save valid snapshot
        save_snapshot(conn, "new", "# New", ["e2"], "e2", ttl_hours=1.0)

        count = cleanup_expired_snapshots(conn)
        assert count >= 1

        assert get_valid_snapshot(conn, "old") is None
        assert get_valid_snapshot(conn, "new") is not None

    def test_cleanup_returns_zero_if_none_expired(self, snapshot_store: SQLiteEventStore):
        """cleanup_expired_snapshots should return 0 if no expired snapshots."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "valid", "# Valid", ["e1"], "e1", ttl_hours=1.0)

        count = cleanup_expired_snapshots(conn)
        assert count == 0


class TestGetSnapshotStats:
    """Tests for get_snapshot_stats function."""

    def test_stats_empty_database(self, snapshot_store: SQLiteEventStore):
        """get_snapshot_stats should return zeros for empty database."""
        conn = snapshot_store._get_conn()
        stats = get_snapshot_stats(conn)

        assert stats["total_count"] == 0
        assert stats["valid_count"] == 0
        assert stats["branches"] == []

    def test_stats_with_snapshots(self, snapshot_store: SQLiteEventStore):
        """get_snapshot_stats should return correct counts."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "main", "# Main", ["e1"], "e1")
        save_snapshot(conn, "feature", "# Feature", ["e2"], "e2")

        stats = get_snapshot_stats(conn)

        assert stats["total_count"] == 2
        assert stats["valid_count"] == 2
        assert set(stats["branches"]) == {"main", "feature"}

    def test_stats_excludes_expired(self, snapshot_store: SQLiteEventStore):
        """get_snapshot_stats valid_count should exclude expired snapshots."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "valid", "# Valid", ["e1"], "e1", ttl_hours=1.0)
        save_snapshot(conn, "expired", "# Expired", ["e2"], "e2", ttl_hours=-1.0)

        stats = get_snapshot_stats(conn)

        assert stats["total_count"] == 2
        assert stats["valid_count"] == 1
        assert stats["branches"] == ["valid"]


class TestSnapshotDataclass:
    """Tests for Snapshot dataclass."""

    def test_is_expired_false_for_valid(self, snapshot_store: SQLiteEventStore):
        """Snapshot.is_expired should return False for valid snapshot."""
        conn = snapshot_store._get_conn()
        save_snapshot(conn, "main", "# Test", ["e1"], "e1", ttl_hours=1.0)

        snapshot = get_valid_snapshot(conn, "main")
        assert snapshot is not None
        assert snapshot.is_expired is False

    def test_is_expired_true_for_expired(self):
        """Snapshot.is_expired should return True for expired snapshot."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        snapshot = Snapshot(
            id=1,
            git_branch="main",
            briefing_markdown="# Test",
            event_ids=["e1"],
            last_event_id="e1",
            created_at=(past - timedelta(hours=1)).isoformat(),
            expires_at=past.isoformat(),
        )
        assert snapshot.is_expired is True


class TestStoreSnapshotInvalidation:
    """Tests for SQLiteEventStore snapshot invalidation on append."""

    def test_append_invalidates_snapshot(self, snapshot_store: SQLiteEventStore):
        """Appending an event should invalidate snapshots."""
        conn = snapshot_store._get_conn()

        # Create a snapshot
        save_snapshot(conn, "main", "# Old Briefing", ["e1"], "e1")
        assert get_valid_snapshot(conn, "main") is not None

        # Append an event
        event = create_event(EventType.KNOWLEDGE_ACQUIRED, "New knowledge", git_branch="main")
        snapshot_store.append(event)

        # Snapshot should be invalidated
        assert get_valid_snapshot(conn, "main") is None

    def test_append_many_invalidates_snapshots(self, snapshot_store: SQLiteEventStore):
        """Appending multiple events should invalidate snapshots."""
        conn = snapshot_store._get_conn()

        save_snapshot(conn, "main", "# Main", ["e1"], "e1")
        save_snapshot(conn, "feature", "# Feature", ["e2"], "e2")

        events = [
            create_event(EventType.KNOWLEDGE_ACQUIRED, "Knowledge 1", git_branch="main"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "Knowledge 2", git_branch="feature"),
        ]
        snapshot_store.append_many(events)

        # Both snapshots should be invalidated
        assert get_valid_snapshot(conn, "main") is None
        assert get_valid_snapshot(conn, "feature") is None


class TestBriefingCacheIntegration:
    """Integration tests for briefing caching."""

    def test_briefing_caches_on_first_call(self, sample_project_hash: str, sample_config: CortexConfig):
        """generate_briefing should cache the result for Tier 1."""
        from cortex.briefing import generate_briefing

        # Set to Tier 1
        sample_config.storage_tier = 1

        store = SQLiteEventStore(sample_project_hash, sample_config)
        conn = store._get_conn()

        # Add some events
        events = [
            create_event(EventType.DECISION_MADE, "Use SQLite for storage"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "WAL mode is fast"),
        ]
        store.append_many(events)

        # Clear any snapshots from append
        invalidate_snapshots(conn, None)

        # Generate briefing (should cache)
        briefing1 = generate_briefing(project_hash=sample_project_hash, config=sample_config)

        # Verify snapshot was created
        snapshot = get_valid_snapshot(conn, "")
        assert snapshot is not None
        assert snapshot.briefing_markdown == briefing1

        store.close()

    def test_briefing_returns_cached_on_second_call(self, sample_project_hash: str, sample_config: CortexConfig):
        """generate_briefing should return cached result on second call."""
        from cortex.briefing import generate_briefing

        sample_config.storage_tier = 1

        store = SQLiteEventStore(sample_project_hash, sample_config)
        conn = store._get_conn()

        # Add events
        store.append(create_event(EventType.DECISION_MADE, "Test decision"))

        # Clear snapshots
        invalidate_snapshots(conn, None)

        # First call (to populate cache)
        generate_briefing(project_hash=sample_project_hash, config=sample_config)

        # Manually modify the cached markdown to detect if it's used
        conn.execute(
            "UPDATE snapshots SET briefing_markdown = ? WHERE git_branch = ?",
            ("# CACHED", ""),
        )
        conn.commit()

        # Second call should use cache
        briefing2 = generate_briefing(project_hash=sample_project_hash, config=sample_config)
        assert briefing2 == "# CACHED"

        store.close()

    def test_briefing_regenerates_after_new_event(self, sample_project_hash: str, sample_config: CortexConfig):
        """generate_briefing should regenerate after new events are added."""
        from cortex.briefing import generate_briefing

        sample_config.storage_tier = 1

        store = SQLiteEventStore(sample_project_hash, sample_config)

        # Add initial event and generate
        store.append(create_event(EventType.DECISION_MADE, "Initial decision"))
        briefing1 = generate_briefing(project_hash=sample_project_hash, config=sample_config)

        # Add new event (invalidates cache)
        store.append(create_event(EventType.DECISION_MADE, "New decision"))

        # Generate again (should include new event)
        briefing2 = generate_briefing(project_hash=sample_project_hash, config=sample_config)

        assert "New decision" in briefing2
        assert briefing1 != briefing2

        store.close()

    def test_briefing_use_cache_false_skips_cache(self, sample_project_hash: str, sample_config: CortexConfig):
        """generate_briefing with use_cache=False should skip cache."""
        from cortex.briefing import generate_briefing

        sample_config.storage_tier = 1

        store = SQLiteEventStore(sample_project_hash, sample_config)
        conn = store._get_conn()

        store.append(create_event(EventType.DECISION_MADE, "Test decision"))
        invalidate_snapshots(conn, None)

        # First call to cache
        generate_briefing(project_hash=sample_project_hash, config=sample_config)

        # Modify cache
        conn.execute(
            "UPDATE snapshots SET briefing_markdown = ? WHERE git_branch = ?",
            ("# STALE CACHE", ""),
        )
        conn.commit()

        # Call with use_cache=False
        briefing = generate_briefing(project_hash=sample_project_hash, config=sample_config, use_cache=False)

        # Should NOT return cached value
        assert briefing != "# STALE CACHE"
        assert "Test decision" in briefing

        store.close()

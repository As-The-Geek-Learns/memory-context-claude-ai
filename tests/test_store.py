"""Tests for the Cortex EventStore and HookState."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_context_claude_ai.models import Event, EventType, create_event
from memory_context_claude_ai.store import EventStore, HookState


class TestEventStoreBasics:
    """Tests for basic EventStore operations."""

    def test_empty_store_has_zero_count(self, event_store: EventStore) -> None:
        """A new store has zero events."""
        assert event_store.count() == 0

    def test_load_all_empty(self, event_store: EventStore) -> None:
        """load_all returns empty list for new store."""
        assert event_store.load_all() == []

    def test_events_path(self, event_store: EventStore) -> None:
        """events_path points to events.json in the project directory."""
        assert event_store.events_path.name == "events.json"


class TestEventStoreAppend:
    """Tests for appending events."""

    def test_append_single_event(self, event_store: EventStore) -> None:
        """Appending one event increases count to 1."""
        e = create_event(EventType.DECISION_MADE, "chose X")
        event_store.append(e)
        assert event_store.count() == 1

    def test_append_preserves_data(self, event_store: EventStore) -> None:
        """Appended event can be loaded back with all fields intact."""
        e = create_event(
            EventType.KNOWLEDGE_ACQUIRED,
            "learned X",
            session_id="s1",
            project="p1",
            git_branch="main",
            metadata={"key": "value"},
        )
        event_store.append(e)
        loaded = event_store.load_all()
        assert len(loaded) == 1
        assert loaded[0].id == e.id
        assert loaded[0].content == "learned X"
        assert loaded[0].session_id == "s1"
        assert loaded[0].metadata == {"key": "value"}

    def test_append_multiple(self, event_store: EventStore) -> None:
        """Multiple appends accumulate events."""
        for i in range(5):
            event_store.append(create_event(EventType.COMMAND_RUN, f"cmd {i}"))
        assert event_store.count() == 5


class TestEventStoreAppendMany:
    """Tests for batch append with deduplication."""

    def test_append_many_basic(self, event_store: EventStore) -> None:
        """append_many adds all events at once."""
        events = [
            create_event(EventType.DECISION_MADE, "chose X"),
            create_event(EventType.KNOWLEDGE_ACQUIRED, "learned Y"),
        ]
        event_store.append_many(events)
        assert event_store.count() == 2

    def test_append_many_deduplicates(self, event_store: EventStore) -> None:
        """append_many skips events already in the store (by content hash)."""
        e1 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        event_store.append(e1)

        # Create a new event with same type, content, and session_id
        # (different id but same content hash)
        e2 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        e3 = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned Y", session_id="s1")
        event_store.append_many([e2, e3])

        # e2 should be deduplicated, only e3 is new
        assert event_store.count() == 2

    def test_append_many_empty_list(self, event_store: EventStore) -> None:
        """append_many with empty list is a no-op."""
        event_store.append_many([])
        assert event_store.count() == 0

    def test_append_many_deduplicates_within_batch(self, event_store: EventStore) -> None:
        """append_many deduplicates events within the batch itself."""
        e1 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        event_store.append_many([e1, e2])
        assert event_store.count() == 1


class TestEventStoreQueries:
    """Tests for query operations."""

    def test_load_recent(self, event_store: EventStore) -> None:
        """load_recent returns events sorted by created_at descending."""
        events = []
        for i in range(10):
            e = create_event(EventType.COMMAND_RUN, f"cmd {i}")
            events.append(e)
            event_store.append(e)

        recent = event_store.load_recent(5)
        assert len(recent) == 5
        # Most recent first
        for j in range(len(recent) - 1):
            assert recent[j].created_at >= recent[j + 1].created_at

    def test_load_recent_fewer_than_requested(self, event_store: EventStore) -> None:
        """load_recent returns all events if fewer than N exist."""
        event_store.append(create_event(EventType.COMMAND_RUN, "cmd 1"))
        recent = event_store.load_recent(50)
        assert len(recent) == 1

    def test_load_by_type(self, event_store: EventStore, sample_events: list) -> None:
        """load_by_type filters correctly."""
        event_store.append_many(sample_events)
        decisions = event_store.load_by_type(EventType.DECISION_MADE)
        assert len(decisions) == 1
        assert all(e.type == EventType.DECISION_MADE for e in decisions)

    def test_load_immortal(self, event_store: EventStore, sample_events: list) -> None:
        """load_immortal returns only immortal events."""
        event_store.append_many(sample_events)
        immortal = event_store.load_immortal()
        # sample_events has 1 DECISION_MADE and 1 APPROACH_REJECTED
        assert len(immortal) == 2
        assert all(e.immortal for e in immortal)


class TestEventStoreForBriefing:
    """Tests for the briefing-oriented query."""

    def test_briefing_has_three_sections(self, event_store: EventStore, sample_events: list) -> None:
        """load_for_briefing returns immortal, active_plan, and recent."""
        event_store.append_many(sample_events)
        briefing = event_store.load_for_briefing()
        assert "immortal" in briefing
        assert "active_plan" in briefing
        assert "recent" in briefing

    def test_briefing_immortal_section(self, event_store: EventStore, sample_events: list) -> None:
        """Immortal section contains decisions and rejections."""
        event_store.append_many(sample_events)
        briefing = event_store.load_for_briefing()
        assert len(briefing["immortal"]) == 2
        types = {e.type for e in briefing["immortal"]}
        assert types == {EventType.DECISION_MADE, EventType.APPROACH_REJECTED}

    def test_briefing_active_plan(self, event_store: EventStore, sample_events: list) -> None:
        """Active plan section contains the latest plan and its steps."""
        event_store.append_many(sample_events)
        briefing = event_store.load_for_briefing()
        assert len(briefing["active_plan"]) >= 1
        assert briefing["active_plan"][0].type == EventType.PLAN_CREATED

    def test_briefing_no_duplicates_across_sections(
        self, event_store: EventStore, sample_events: list
    ) -> None:
        """Events in immortal or active_plan don't appear in recent."""
        event_store.append_many(sample_events)
        briefing = event_store.load_for_briefing()

        immortal_ids = {e.id for e in briefing["immortal"]}
        plan_ids = {e.id for e in briefing["active_plan"]}
        recent_ids = {e.id for e in briefing["recent"]}

        assert immortal_ids.isdisjoint(recent_ids)
        assert plan_ids.isdisjoint(recent_ids)

    def test_briefing_branch_filter(self, event_store: EventStore) -> None:
        """Branch filter excludes events from other branches."""
        e_main = create_event(EventType.DECISION_MADE, "main decision", git_branch="main")
        e_feature = create_event(EventType.DECISION_MADE, "feature decision", git_branch="feature/x")
        event_store.append(e_main)
        event_store.append(e_feature)

        briefing = event_store.load_for_briefing(branch="main")
        all_events = briefing["immortal"] + briefing["active_plan"] + briefing["recent"]
        branches = {e.git_branch for e in all_events}
        assert "feature/x" not in branches

    def test_briefing_empty_store(self, event_store: EventStore) -> None:
        """Briefing from empty store returns empty sections."""
        briefing = event_store.load_for_briefing()
        assert briefing["immortal"] == []
        assert briefing["active_plan"] == []
        assert briefing["recent"] == []


class TestEventStoreMarkAccessed:
    """Tests for access tracking / reinforcement."""

    def test_mark_accessed_updates_timestamp(self, event_store: EventStore) -> None:
        """mark_accessed updates the accessed_at field."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        original_accessed = e.accessed_at
        event_store.append(e)

        event_store.mark_accessed([e.id])
        loaded = event_store.load_all()
        assert loaded[0].accessed_at >= original_accessed

    def test_mark_accessed_increments_count(self, event_store: EventStore) -> None:
        """mark_accessed increments access_count."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        event_store.append(e)

        event_store.mark_accessed([e.id])
        loaded = event_store.load_all()
        assert loaded[0].access_count == 1

        event_store.mark_accessed([e.id])
        loaded = event_store.load_all()
        assert loaded[0].access_count == 2

    def test_mark_accessed_empty_list(self, event_store: EventStore) -> None:
        """mark_accessed with empty list is a no-op."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        event_store.append(e)
        event_store.mark_accessed([])
        loaded = event_store.load_all()
        assert loaded[0].access_count == 0

    def test_mark_accessed_nonexistent_id(self, event_store: EventStore) -> None:
        """mark_accessed with unknown IDs doesn't crash."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        event_store.append(e)
        event_store.mark_accessed(["nonexistent-id"])
        loaded = event_store.load_all()
        assert loaded[0].access_count == 0


class TestEventStoreClear:
    """Tests for clearing the store."""

    def test_clear_empties_store(self, event_store: EventStore) -> None:
        """clear() removes all events."""
        event_store.append(create_event(EventType.DECISION_MADE, "chose X"))
        event_store.append(create_event(EventType.KNOWLEDGE_ACQUIRED, "learned Y"))
        assert event_store.count() == 2

        event_store.clear()
        assert event_store.count() == 0
        assert event_store.load_all() == []


class TestEventStoreFileHandling:
    """Tests for file I/O edge cases."""

    def test_handles_missing_file(self, event_store: EventStore) -> None:
        """Store works correctly when events.json doesn't exist yet."""
        assert event_store.load_all() == []
        assert event_store.count() == 0

    def test_handles_empty_file(self, event_store: EventStore) -> None:
        """Store handles an empty events.json file."""
        event_store.events_path.parent.mkdir(parents=True, exist_ok=True)
        event_store.events_path.write_text("")
        assert event_store.load_all() == []

    def test_handles_corrupted_json(self, event_store: EventStore) -> None:
        """Store handles corrupted JSON gracefully."""
        event_store.events_path.parent.mkdir(parents=True, exist_ok=True)
        event_store.events_path.write_text("{not valid json")
        assert event_store.load_all() == []

    def test_atomic_write_no_temp_file(self, event_store: EventStore) -> None:
        """After write, no .tmp file should remain."""
        event_store.append(create_event(EventType.COMMAND_RUN, "test"))
        tmp_path = event_store.events_path.with_suffix(".json.tmp")
        assert not tmp_path.exists()

    def test_valid_json_on_disk(self, event_store: EventStore) -> None:
        """Events are stored as valid JSON on disk."""
        event_store.append(create_event(EventType.DECISION_MADE, "chose X"))
        content = event_store.events_path.read_text()
        data = json.loads(content)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["type"] == "decision_made"


# ─── HookState Tests ───────────────────────────────────────────────


class TestHookStateDefaults:
    """Tests for HookState default values."""

    def test_load_returns_defaults(self, hook_state: HookState) -> None:
        """Loading from nonexistent state returns defaults."""
        state = hook_state.load()
        assert state["last_transcript_position"] == 0
        assert state["last_transcript_path"] == ""
        assert state["last_session_id"] == ""
        assert state["session_count"] == 0
        assert state["last_extraction_time"] == ""

    def test_state_path(self, hook_state: HookState) -> None:
        """state_path points to state.json in the project directory."""
        assert hook_state.state_path.name == "state.json"


class TestHookStateSaveLoad:
    """Tests for saving and loading hook state."""

    def test_round_trip(self, hook_state: HookState) -> None:
        """Save then load preserves all values."""
        state = {
            "last_transcript_position": 1024,
            "last_transcript_path": "/tmp/transcript.jsonl",
            "last_session_id": "session-001",
            "session_count": 5,
            "last_extraction_time": "2025-01-15T10:30:00+00:00",
        }
        hook_state.save(state)
        loaded = hook_state.load()

        assert loaded["last_transcript_position"] == 1024
        assert loaded["last_transcript_path"] == "/tmp/transcript.jsonl"
        assert loaded["last_session_id"] == "session-001"
        assert loaded["session_count"] == 5

    def test_update_merges_keys(self, hook_state: HookState) -> None:
        """update() merges new keys into existing state."""
        hook_state.save({"last_transcript_position": 0, "session_count": 0})
        hook_state.update(last_transcript_position=512, session_count=1)

        state = hook_state.load()
        assert state["last_transcript_position"] == 512
        assert state["session_count"] == 1

    def test_update_preserves_existing(self, hook_state: HookState) -> None:
        """update() doesn't clobber keys not in the update."""
        hook_state.save({"last_session_id": "s1", "session_count": 3})
        hook_state.update(session_count=4)

        state = hook_state.load()
        assert state["last_session_id"] == "s1"
        assert state["session_count"] == 4


class TestHookStateFileHandling:
    """Tests for HookState file I/O edge cases."""

    def test_handles_corrupted_json(self, hook_state: HookState) -> None:
        """Returns defaults if state.json is corrupted."""
        hook_state.state_path.parent.mkdir(parents=True, exist_ok=True)
        hook_state.state_path.write_text("{bad json")
        state = hook_state.load()
        assert state["last_transcript_position"] == 0

    def test_atomic_write_no_temp_file(self, hook_state: HookState) -> None:
        """After save, no .tmp file should remain."""
        hook_state.save({"session_count": 1})
        tmp_path = hook_state.state_path.with_suffix(".json.tmp")
        assert not tmp_path.exists()

    def test_fills_missing_defaults(self, hook_state: HookState) -> None:
        """load() fills in defaults for any missing keys."""
        hook_state.state_path.parent.mkdir(parents=True, exist_ok=True)
        hook_state.state_path.write_text(json.dumps({"session_count": 10}))
        state = hook_state.load()
        assert state["session_count"] == 10
        assert state["last_transcript_position"] == 0  # default filled in
        assert state["last_session_id"] == ""  # default filled in

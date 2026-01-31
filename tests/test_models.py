"""Tests for the Cortex event model, serialization, and salience calculations."""

from datetime import datetime, timedelta, timezone

from memory_context_claude_ai.models import (
    DEFAULT_SALIENCE,
    IMMORTAL_TYPES,
    Event,
    EventType,
    content_hash,
    create_event,
    effective_salience,
    reinforce_event,
)


class TestEventType:
    """Tests for the EventType enum."""

    def test_all_eleven_types_exist(self) -> None:
        """All 11 event types from the Cortex spec are defined."""
        assert len(EventType) == 11

    def test_event_type_values(self) -> None:
        """Each enum member has the expected string value."""
        assert EventType.DECISION_MADE.value == "decision_made"
        assert EventType.APPROACH_REJECTED.value == "approach_rejected"
        assert EventType.PLAN_CREATED.value == "plan_created"
        assert EventType.PLAN_STEP_COMPLETED.value == "plan_step_completed"
        assert EventType.KNOWLEDGE_ACQUIRED.value == "knowledge_acquired"
        assert EventType.ERROR_RESOLVED.value == "error_resolved"
        assert EventType.PREFERENCE_NOTED.value == "preference_noted"
        assert EventType.TASK_COMPLETED.value == "task_completed"
        assert EventType.FILE_MODIFIED.value == "file_modified"
        assert EventType.FILE_EXPLORED.value == "file_explored"
        assert EventType.COMMAND_RUN.value == "command_run"


class TestDefaultSalience:
    """Tests for the default salience mapping."""

    def test_all_types_have_default_salience(self) -> None:
        """Every EventType has an entry in DEFAULT_SALIENCE."""
        for event_type in EventType:
            assert event_type in DEFAULT_SALIENCE, f"{event_type} missing from DEFAULT_SALIENCE"

    def test_decisions_have_highest_salience(self) -> None:
        """DECISION_MADE and APPROACH_REJECTED have salience 0.9."""
        assert DEFAULT_SALIENCE[EventType.DECISION_MADE] == 0.9
        assert DEFAULT_SALIENCE[EventType.APPROACH_REJECTED] == 0.9

    def test_commands_have_lowest_salience(self) -> None:
        """COMMAND_RUN has the lowest default salience (0.2)."""
        assert DEFAULT_SALIENCE[EventType.COMMAND_RUN] == 0.2

    def test_all_salience_values_in_valid_range(self) -> None:
        """All default salience values are between 0.0 and 1.0."""
        for event_type, salience in DEFAULT_SALIENCE.items():
            assert 0.0 <= salience <= 1.0, f"{event_type} has invalid salience {salience}"


class TestImmortalTypes:
    """Tests for the immortality set."""

    def test_only_decisions_and_rejections_are_immortal(self) -> None:
        """Only DECISION_MADE and APPROACH_REJECTED are immortal."""
        assert IMMORTAL_TYPES == {EventType.DECISION_MADE, EventType.APPROACH_REJECTED}

    def test_non_immortal_types(self) -> None:
        """Other types are NOT immortal."""
        for event_type in EventType:
            if event_type not in {EventType.DECISION_MADE, EventType.APPROACH_REJECTED}:
                assert event_type not in IMMORTAL_TYPES


class TestCreateEvent:
    """Tests for the create_event factory function."""

    def test_auto_generates_uuid(self) -> None:
        """Each event gets a unique UUID."""
        e1 = create_event(EventType.DECISION_MADE, "test 1")
        e2 = create_event(EventType.DECISION_MADE, "test 2")
        assert e1.id != e2.id
        assert len(e1.id) == 36  # UUID4 format

    def test_sets_default_salience_from_type(self) -> None:
        """Factory uses DEFAULT_SALIENCE for the event type."""
        e = create_event(EventType.FILE_EXPLORED, "Explored foo.py")
        assert e.salience == 0.3  # FILE_EXPLORED default

    def test_sets_immortality_from_type(self) -> None:
        """Factory sets immortal=True for decision types."""
        decision = create_event(EventType.DECISION_MADE, "chose X")
        rejected = create_event(EventType.APPROACH_REJECTED, "rejected Y")
        knowledge = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned Z")

        assert decision.immortal is True
        assert rejected.immortal is True
        assert knowledge.immortal is False

    def test_sets_timestamps(self) -> None:
        """Factory sets created_at and accessed_at to current UTC time."""
        e = create_event(EventType.COMMAND_RUN, "ran something")
        assert e.created_at != ""
        assert e.accessed_at != ""
        # Should be parseable as ISO datetime
        datetime.fromisoformat(e.created_at)
        datetime.fromisoformat(e.accessed_at)

    def test_preserves_all_arguments(self) -> None:
        """All provided arguments are correctly stored."""
        e = create_event(
            event_type=EventType.KNOWLEDGE_ACQUIRED,
            content="test content",
            session_id="sess-1",
            project="proj-hash",
            git_branch="feature/test",
            metadata={"key": "value"},
            confidence=0.85,
            provenance="layer2:keyword:test",
        )
        assert e.content == "test content"
        assert e.session_id == "sess-1"
        assert e.project == "proj-hash"
        assert e.git_branch == "feature/test"
        assert e.metadata == {"key": "value"}
        assert e.confidence == 0.85
        assert e.provenance == "layer2:keyword:test"

    def test_access_count_starts_at_zero(self) -> None:
        """New events have access_count=0."""
        e = create_event(EventType.DECISION_MADE, "chose X")
        assert e.access_count == 0


class TestEventSerialization:
    """Tests for Event.to_dict() and Event.from_dict()."""

    def test_round_trip(self) -> None:
        """Serializing then deserializing produces an equivalent event."""
        original = create_event(
            event_type=EventType.DECISION_MADE,
            content="chose SQLite",
            session_id="s1",
            project="p1",
            git_branch="main",
            metadata={"reason": "zero-config"},
            confidence=0.95,
            provenance="layer3:MEMORY_TAG",
        )
        data = original.to_dict()
        restored = Event.from_dict(data)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.content == original.content
        assert restored.session_id == original.session_id
        assert restored.project == original.project
        assert restored.git_branch == original.git_branch
        assert restored.metadata == original.metadata
        assert restored.salience == original.salience
        assert restored.confidence == original.confidence
        assert restored.immortal == original.immortal
        assert restored.provenance == original.provenance

    def test_to_dict_type_is_string(self) -> None:
        """to_dict converts EventType enum to its string value."""
        e = create_event(EventType.FILE_MODIFIED, "modified foo.py")
        d = e.to_dict()
        assert d["type"] == "file_modified"
        assert isinstance(d["type"], str)

    def test_from_dict_handles_missing_fields(self) -> None:
        """from_dict provides defaults for missing keys."""
        minimal = {"type": "command_run", "content": "ran something"}
        e = Event.from_dict(minimal)
        assert e.type == EventType.COMMAND_RUN
        assert e.content == "ran something"
        assert e.session_id == ""
        assert e.salience == 0.5  # default
        assert e.immortal is False

    def test_from_dict_handles_missing_type(self) -> None:
        """from_dict defaults to KNOWLEDGE_ACQUIRED if type is missing."""
        e = Event.from_dict({"content": "something"})
        assert e.type == EventType.KNOWLEDGE_ACQUIRED


class TestEffectiveSalience:
    """Tests for the decay calculation."""

    def test_immortal_events_never_decay(self) -> None:
        """Immortal events return their raw salience regardless of age."""
        e = create_event(EventType.DECISION_MADE, "chose X")
        old_time = datetime.now(timezone.utc) - timedelta(days=365)
        e.accessed_at = old_time.isoformat()

        now = datetime.now(timezone.utc)
        assert effective_salience(e, now) == e.salience

    def test_recent_event_has_full_salience(self) -> None:
        """A just-created non-immortal event has nearly full salience."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        now = datetime.now(timezone.utc)
        result = effective_salience(e, now)
        # Should be very close to original (maybe a few seconds of decay)
        assert result > e.salience * 0.99

    def test_48_hour_decay(self) -> None:
        """After 48 hours, salience drops to ~78.6% of original."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        e.salience = 0.7
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        e.accessed_at = old_time.isoformat()

        now = datetime.now(timezone.utc)
        result = effective_salience(e, now)
        expected = 0.7 * (0.995**48)  # ~0.55
        assert abs(result - expected) < 0.01

    def test_7_day_decay(self) -> None:
        """After 7 days (168 hours), salience drops to ~43% of original."""
        e = create_event(EventType.FILE_EXPLORED, "explored foo.py")
        e.salience = 0.7
        old_time = datetime.now(timezone.utc) - timedelta(days=7)
        e.accessed_at = old_time.isoformat()

        now = datetime.now(timezone.utc)
        result = effective_salience(e, now)
        expected = 0.7 * (0.995**168)  # ~0.30
        assert abs(result - expected) < 0.01

    def test_bad_timestamp_returns_raw_salience(self) -> None:
        """If accessed_at is invalid, return raw salience (defensive)."""
        e = create_event(EventType.COMMAND_RUN, "ran something")
        e.accessed_at = "not-a-timestamp"
        assert effective_salience(e) == e.salience

    def test_empty_accessed_at_returns_raw_salience(self) -> None:
        """If accessed_at is empty, return raw salience."""
        e = create_event(EventType.COMMAND_RUN, "ran something")
        e.accessed_at = ""
        assert effective_salience(e) == e.salience


class TestReinforceEvent:
    """Tests for the reinforcement function."""

    def test_boosts_salience(self) -> None:
        """Reinforcement increases salience by 1.2x."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        e.salience = 0.7
        reinforced = reinforce_event(e)
        assert reinforced.salience == 0.7 * 1.2

    def test_caps_at_one(self) -> None:
        """Reinforcement does not exceed 1.0."""
        e = create_event(EventType.DECISION_MADE, "chose X")
        e.salience = 0.9
        reinforced = reinforce_event(e)
        assert reinforced.salience == 1.0

    def test_increments_access_count(self) -> None:
        """Reinforcement increments access_count."""
        e = create_event(EventType.FILE_MODIFIED, "modified foo.py")
        assert e.access_count == 0
        reinforced = reinforce_event(e)
        assert reinforced.access_count == 1

    def test_updates_accessed_at(self) -> None:
        """Reinforcement updates accessed_at timestamp."""
        e = create_event(EventType.FILE_MODIFIED, "modified foo.py")
        original_accessed = e.accessed_at
        reinforced = reinforce_event(e)
        assert reinforced.accessed_at >= original_accessed

    def test_does_not_mutate_original(self) -> None:
        """Reinforcement returns a new event, does not mutate the original."""
        e = create_event(EventType.KNOWLEDGE_ACQUIRED, "learned X")
        e.salience = 0.5
        original_salience = e.salience
        reinforce_event(e)
        assert e.salience == original_salience


class TestContentHash:
    """Tests for the deduplication hash function."""

    def test_deterministic(self) -> None:
        """Same event produces same hash."""
        e = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        assert content_hash(e) == content_hash(e)

    def test_different_content_different_hash(self) -> None:
        """Different content produces different hash."""
        e1 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "chose Y", session_id="s1")
        assert content_hash(e1) != content_hash(e2)

    def test_different_type_different_hash(self) -> None:
        """Different types produce different hash even with same content."""
        e1 = create_event(EventType.DECISION_MADE, "chose X", session_id="s1")
        e2 = create_event(EventType.KNOWLEDGE_ACQUIRED, "chose X", session_id="s1")
        assert content_hash(e1) != content_hash(e2)

    def test_hash_length(self) -> None:
        """Hash is 16 hex characters."""
        e = create_event(EventType.COMMAND_RUN, "ran something")
        h = content_hash(e)
        assert len(h) == 16
        int(h, 16)  # Should be valid hex

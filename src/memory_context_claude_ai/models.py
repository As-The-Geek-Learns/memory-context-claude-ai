"""Core data models for the Cortex event-sourced memory system.

Defines the Event dataclass, EventType enum, default salience mappings,
and decay/reinforcement calculations. This is the foundation module —
everything else in Cortex depends on these types.
"""

import enum
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class EventType(enum.Enum):
    """Typed categories of events captured by Cortex.

    Each type has a default salience score and immortality flag.
    See DEFAULT_SALIENCE and IMMORTAL_TYPES for the mappings.
    """

    DECISION_MADE = "decision_made"
    APPROACH_REJECTED = "approach_rejected"
    PLAN_CREATED = "plan_created"
    PLAN_STEP_COMPLETED = "plan_step_completed"
    KNOWLEDGE_ACQUIRED = "knowledge_acquired"
    ERROR_RESOLVED = "error_resolved"
    PREFERENCE_NOTED = "preference_noted"
    TASK_COMPLETED = "task_completed"
    FILE_MODIFIED = "file_modified"
    FILE_EXPLORED = "file_explored"
    COMMAND_RUN = "command_run"


# WHAT: Default salience scores per event type (0.0-1.0).
# WHY: Higher-salience events persist longer in briefings before decay
# removes them. Decisions are most important; commands are least.
DEFAULT_SALIENCE: dict[EventType, float] = {
    EventType.DECISION_MADE: 0.9,
    EventType.APPROACH_REJECTED: 0.9,
    EventType.PLAN_CREATED: 0.85,
    EventType.PLAN_STEP_COMPLETED: 0.7,
    EventType.KNOWLEDGE_ACQUIRED: 0.7,
    EventType.ERROR_RESOLVED: 0.75,
    EventType.PREFERENCE_NOTED: 0.8,
    EventType.TASK_COMPLETED: 0.6,
    EventType.FILE_MODIFIED: 0.4,
    EventType.FILE_EXPLORED: 0.3,
    EventType.COMMAND_RUN: 0.2,
}

# WHAT: Event types that never decay.
# WHY: "Why did we choose X?" can arise at any point in a project's lifetime.
# Decisions and rejections are permanently retained in the event store.
IMMORTAL_TYPES: set[EventType] = {
    EventType.DECISION_MADE,
    EventType.APPROACH_REJECTED,
}

# WHAT: Default decay rate applied per hour to non-immortal events.
# WHY: 0.995/hour means a salience-0.7 event is ~0.55 after 48 hours,
# ~0.30 after 7 days. These are initial estimates — calibrated from
# real session data during the evaluation phase (see paper §11.4).
DEFAULT_DECAY_RATE = 0.995

# WHAT: Multiplier applied when an event is accessed (retrieved for briefing).
# WHY: Frequently useful memories should survive longer. Reinforcement
# boosts salience by 20%, capped at 1.0.
DEFAULT_REINFORCEMENT_MULTIPLIER = 1.2


@dataclass
class Event:
    """A single captured event in the Cortex memory system.

    Events are immutable facts extracted from Claude Code sessions.
    They are stored in the event store and projected into briefings.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    project: str = ""
    git_branch: str = ""
    type: EventType = EventType.KNOWLEDGE_ACQUIRED
    content: str = ""
    metadata: dict = field(default_factory=dict)
    salience: float = 0.5
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    immortal: bool = False
    provenance: str = ""

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "project": self.project,
            "git_branch": self.git_branch,
            "type": self.type.value,
            "content": self.content,
            "metadata": self.metadata,
            "salience": self.salience,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "immortal": self.immortal,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        """Deserialize from a dictionary (e.g., loaded from JSON)."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            project=data.get("project", ""),
            git_branch=data.get("git_branch", ""),
            type=EventType(data["type"]) if "type" in data else EventType.KNOWLEDGE_ACQUIRED,
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            salience=data.get("salience", 0.5),
            confidence=data.get("confidence", 1.0),
            created_at=data.get("created_at", ""),
            accessed_at=data.get("accessed_at", ""),
            access_count=data.get("access_count", 0),
            immortal=data.get("immortal", False),
            provenance=data.get("provenance", ""),
        )


def create_event(
    event_type: EventType,
    content: str,
    session_id: str = "",
    project: str = "",
    git_branch: str = "",
    metadata: dict | None = None,
    confidence: float = 1.0,
    provenance: str = "",
) -> Event:
    """Factory function to create an Event with sensible defaults.

    Automatically sets:
    - UUID id
    - Default salience from the event type
    - Immortality flag from IMMORTAL_TYPES
    - Timestamps to current UTC time
    """
    now = datetime.now(timezone.utc).isoformat()
    return Event(
        id=str(uuid.uuid4()),
        session_id=session_id,
        project=project,
        git_branch=git_branch,
        type=event_type,
        content=content,
        metadata=metadata or {},
        salience=DEFAULT_SALIENCE.get(event_type, 0.5),
        confidence=confidence,
        created_at=now,
        accessed_at=now,
        access_count=0,
        immortal=event_type in IMMORTAL_TYPES,
        provenance=provenance,
    )


def effective_salience(event: Event, now: datetime | None = None) -> float:
    """Calculate the effective salience of an event after decay.

    Formula: salience * (decay_rate ^ hours_since_last_access)
    Immortal events always return their raw salience (no decay).

    Args:
        event: The event to calculate salience for.
        now: Current time. Defaults to UTC now if not provided.

    Returns:
        Effective salience as a float between 0.0 and 1.0.
    """
    if event.immortal:
        return event.salience

    if now is None:
        now = datetime.now(timezone.utc)

    if not event.accessed_at:
        return event.salience

    try:
        last_accessed = datetime.fromisoformat(event.accessed_at)
        # WHAT: Ensure timezone-aware comparison
        # WHY: fromisoformat may return naive datetime from older data
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        hours_elapsed = max(0, (now - last_accessed).total_seconds() / 3600)
        return event.salience * (DEFAULT_DECAY_RATE**hours_elapsed)
    except (ValueError, TypeError):
        # WHAT: If timestamp parsing fails, return raw salience
        # WHY: Defensive — don't let bad data crash the system
        return event.salience


def reinforce_event(event: Event) -> Event:
    """Reinforce an event's salience when it is accessed/retrieved.

    Boosts salience by the reinforcement multiplier (default 1.2x),
    capped at 1.0. Updates accessed_at and increments access_count.

    Returns a new Event with updated fields (does not mutate in place).
    """
    now = datetime.now(timezone.utc).isoformat()
    new_salience = min(1.0, event.salience * DEFAULT_REINFORCEMENT_MULTIPLIER)
    return Event(
        id=event.id,
        session_id=event.session_id,
        project=event.project,
        git_branch=event.git_branch,
        type=event.type,
        content=event.content,
        metadata=event.metadata,
        salience=new_salience,
        confidence=event.confidence,
        created_at=event.created_at,
        accessed_at=now,
        access_count=event.access_count + 1,
        immortal=event.immortal,
        provenance=event.provenance,
    )


def content_hash(event: Event) -> str:
    """Generate a deduplication hash for an event.

    Uses type + content + session_id to detect duplicate events
    across Stop and PreCompact hook extractions.

    Returns a 16-character hex string.
    """
    raw = f"{event.type.value}:{event.content}:{event.session_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

"""JSON-backed event store for Cortex Tier 0.

Provides append-only event storage in a JSON file per project.
Supports querying by type, recency, immortality, and briefing needs.
Uses atomic writes (temp file + rename) for crash safety.

Storage location: ~/.cortex/projects/<hash>/events.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from memory_context_claude_ai.config import CortexConfig, get_project_dir
from memory_context_claude_ai.models import (
    Event,
    EventType,
    content_hash,
    effective_salience,
)


class EventStore:
    """JSON-file-backed event store for a single project.

    Events are stored as a JSON array in events.json. The entire file
    is read/written atomically. This is acceptable for Tier 0 where
    event counts are in the hundreds, not thousands.
    """

    def __init__(self, project_hash: str, config: CortexConfig | None = None):
        self._project_hash = project_hash
        self._config = config or CortexConfig()
        self._project_dir = get_project_dir(project_hash, self._config)
        self._events_path = self._project_dir / "events.json"

    @property
    def events_path(self) -> Path:
        """Path to the events.json file."""
        return self._events_path

    def append(self, event: Event) -> None:
        """Append a single event to the store."""
        events = self._load_raw()
        events.append(event.to_dict())
        self._save_raw(events)

    def append_many(self, events: list[Event]) -> None:
        """Append multiple events to the store.

        Events are deduplicated against existing store contents
        using content hashes. This prevents duplicates when the
        Stop hook and PreCompact hook both extract from the same
        transcript content.
        """
        if not events:
            return

        existing = self._load_raw()
        existing_hashes = {content_hash(Event.from_dict(e)) for e in existing}

        new_events = []
        for event in events:
            h = content_hash(event)
            if h not in existing_hashes:
                new_events.append(event.to_dict())
                existing_hashes.add(h)

        if new_events:
            existing.extend(new_events)
            self._save_raw(existing)

    def load_all(self) -> list[Event]:
        """Load all events from the store."""
        return [Event.from_dict(d) for d in self._load_raw()]

    def load_recent(self, n: int = 50) -> list[Event]:
        """Load the N most recent events, sorted by created_at descending."""
        events = self.load_all()
        events.sort(key=lambda e: e.created_at, reverse=True)
        return events[:n]

    def load_by_type(self, event_type: EventType) -> list[Event]:
        """Load all events of a specific type."""
        return [e for e in self.load_all() if e.type == event_type]

    def load_immortal(self) -> list[Event]:
        """Load all immortal events (decisions and rejections)."""
        return [e for e in self.load_all() if e.immortal]

    def load_for_briefing(self, branch: str | None = None) -> dict:
        """Load events structured for briefing generation.

        Returns a dict with three keys:
        - "immortal": Immortal events sorted by created_at
        - "active_plan": Most recent PLAN_CREATED + its completed steps
        - "recent": Top N events by effective salience (excluding
          immortal and plan events already included)

        Args:
            branch: Optional git branch filter. If provided, only
                    events from this branch are included.

        Returns:
            Dict with "immortal", "active_plan", and "recent" keys.
        """
        all_events = self.load_all()

        if branch:
            all_events = [e for e in all_events if e.git_branch == branch or not e.git_branch]

        now = datetime.now(timezone.utc)

        # Immortal events (decisions, rejections) sorted by recency
        immortal = sorted(
            [e for e in all_events if e.immortal],
            key=lambda e: e.created_at,
            reverse=True,
        )

        # Active plan: most recent PLAN_CREATED + its PLAN_STEP_COMPLETED events
        plan_events = sorted(
            [e for e in all_events if e.type == EventType.PLAN_CREATED],
            key=lambda e: e.created_at,
            reverse=True,
        )
        active_plan: list[Event] = []
        if plan_events:
            latest_plan = plan_events[0]
            # Find completed steps that came after this plan was created
            completed_steps = [
                e
                for e in all_events
                if e.type == EventType.PLAN_STEP_COMPLETED and e.created_at >= latest_plan.created_at
            ]
            active_plan = [latest_plan, *sorted(completed_steps, key=lambda e: e.created_at)]

        # Recent events: top by effective salience, excluding already-included events
        included_ids = {e.id for e in immortal} | {e.id for e in active_plan}
        remaining = [e for e in all_events if e.id not in included_ids]
        remaining.sort(key=lambda e: effective_salience(e, now), reverse=True)
        recent = remaining[:30]  # Top 30 by effective salience

        return {
            "immortal": immortal,
            "active_plan": active_plan,
            "recent": recent,
        }

    def mark_accessed(self, event_ids: list[str]) -> None:
        """Update accessed_at and access_count for specified events.

        Used for reinforcement — events that are retrieved for
        briefings get boosted salience.
        """
        if not event_ids:
            return

        now = datetime.now(timezone.utc).isoformat()
        id_set = set(event_ids)
        raw = self._load_raw()
        modified = False

        for entry in raw:
            if entry.get("id") in id_set:
                entry["accessed_at"] = now
                entry["access_count"] = entry.get("access_count", 0) + 1
                modified = True

        if modified:
            self._save_raw(raw)

    def clear(self) -> None:
        """Remove all events from the store."""
        self._save_raw([])

    def count(self) -> int:
        """Return the number of events in the store."""
        return len(self._load_raw())

    def _load_raw(self) -> list[dict]:
        """Load raw event dictionaries from the JSON file."""
        if not self._events_path.exists():
            return []
        try:
            content = self._events_path.read_text(encoding="utf-8")
            if not content.strip():
                return []
            data = json.loads(content)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_raw(self, events: list[dict]) -> None:
        """Save raw event dictionaries to the JSON file atomically.

        Uses temp file + rename for crash safety. The rename is atomic
        on POSIX systems (macOS, Linux) for same-filesystem operations.
        """
        self._project_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._events_path.with_suffix(".json.tmp")
        try:
            content = json.dumps(events, indent=2, ensure_ascii=False)
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.rename(self._events_path)
        except OSError:
            if tmp_path.exists():
                tmp_path.unlink()
            raise


class HookState:
    """Tracks hook execution state between invocations.

    Stored in ~/.cortex/projects/<hash>/state.json.
    Primarily used for incremental transcript parsing —
    the Stop hook needs to know where it left off.
    """

    def __init__(self, project_hash: str, config: CortexConfig | None = None):
        self._config = config or CortexConfig()
        self._project_dir = get_project_dir(project_hash, self._config)
        self._state_path = self._project_dir / "state.json"

    @property
    def state_path(self) -> Path:
        """Path to the state.json file."""
        return self._state_path

    def load(self) -> dict:
        """Load the current hook state.

        Returns a dict with at least these keys (with defaults):
        - last_transcript_position: int (byte offset, default 0)
        - last_transcript_path: str (path to last transcript, default "")
        - last_session_id: str (default "")
        - session_count: int (default 0)
        - last_extraction_time: str (ISO timestamp, default "")
        """
        defaults = {
            "last_transcript_position": 0,
            "last_transcript_path": "",
            "last_session_id": "",
            "session_count": 0,
            "last_extraction_time": "",
        }

        if not self._state_path.exists():
            return defaults

        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            for key, default_val in defaults.items():
                data.setdefault(key, default_val)
            return data
        except (json.JSONDecodeError, OSError):
            return defaults

    def save(self, state: dict) -> None:
        """Save the hook state atomically."""
        self._project_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(".json.tmp")
        try:
            content = json.dumps(state, indent=2)
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.rename(self._state_path)
        except OSError:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def update(self, **kwargs) -> None:
        """Load, update specific keys, and save the state."""
        state = self.load()
        state.update(kwargs)
        self.save(state)

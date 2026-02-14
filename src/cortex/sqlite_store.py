"""SQLite-backed event store for Cortex Tier 1.

Provides SQLiteEventStore implementing EventStoreBase with:
- Persistent SQLite storage via db.py
- Content-hash deduplication
- Salience-ranked queries with decay
- FTS5-ready schema (search in Phase 3)
"""

import json
import sqlite3
from datetime import datetime, timezone

from cortex.config import CortexConfig
from cortex.db import connect, get_db_path, initialize_schema
from cortex.models import (
    Event,
    EventType,
    content_hash,
    effective_salience,
)
from cortex.store import EventStoreBase


class SQLiteEventStore(EventStoreBase):
    """SQLite-backed event store for Tier 1+.

    Events are stored in a SQLite database with WAL mode for concurrent
    reads during writes. This supports 100K+ events with fast queries
    via indexes and FTS5 full-text search.
    """

    def __init__(self, project_hash: str, config: CortexConfig | None = None):
        self._project_hash = project_hash
        self._config = config or CortexConfig()
        self._db_path = get_db_path(project_hash, self._config)
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self):
        """Path to the SQLite database file."""
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a database connection.

        Lazily initializes the connection and schema on first access.
        """
        if self._conn is None:
            self._conn = connect(self._project_hash, self._config)
            initialize_schema(self._conn)
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def append(self, event: Event) -> None:
        """Append a single event to the store."""
        conn = self._get_conn()
        self._insert_event(conn, event)
        conn.commit()

    def append_many(self, events: list[Event]) -> None:
        """Append multiple events with deduplication.

        Events are deduplicated against existing store contents
        using content hashes.
        """
        if not events:
            return

        conn = self._get_conn()

        # Load existing content hashes for deduplication
        existing_hashes = self._load_content_hashes(conn)

        # Filter to new events only
        new_events = []
        for event in events:
            h = content_hash(event)
            if h not in existing_hashes:
                new_events.append(event)
                existing_hashes.add(h)

        # Batch insert new events
        for event in new_events:
            self._insert_event(conn, event)

        conn.commit()

    def _insert_event(self, conn, event: Event) -> None:
        """Insert a single event into the database."""
        conn.execute(
            """
            INSERT INTO events (
                id, session_id, project, git_branch, type, content, metadata,
                salience, confidence, created_at, accessed_at, access_count,
                immortal, provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.session_id,
                event.project,
                event.git_branch,
                event.type.value,
                event.content,
                json.dumps(event.metadata) if event.metadata else "{}",
                event.salience,
                event.confidence,
                event.created_at,  # Already ISO string from Event dataclass
                event.accessed_at,  # Already ISO string from Event dataclass
                event.access_count,
                1 if event.immortal else 0,
                event.provenance,
            ),
        )

    def _load_content_hashes(self, conn) -> set[str]:
        """Load all content hashes for deduplication."""
        # WHAT: Compute hashes in Python, not SQL.
        # WHY: content_hash() uses the full Event; SQL can't replicate.
        events = self._rows_to_events(conn.execute("SELECT * FROM events").fetchall())
        return {content_hash(e) for e in events}

    def _row_to_event(self, row) -> Event:
        """Convert a database row to an Event object."""
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata else {}

        return Event(
            id=row["id"],
            session_id=row["session_id"] or "",
            project=row["project"] or "",
            git_branch=row["git_branch"] or "",
            type=EventType(row["type"]),
            content=row["content"] or "",
            metadata=metadata,
            salience=row["salience"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"],
            immortal=bool(row["immortal"]),
            provenance=row["provenance"] or "",
        )

    def _rows_to_events(self, rows) -> list[Event]:
        """Convert multiple database rows to Event objects."""
        return [self._row_to_event(row) for row in rows]

    def load_all(self) -> list[Event]:
        """Load all events from the store."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM events ORDER BY created_at")
        return self._rows_to_events(cursor.fetchall())

    def load_recent(self, n: int = 50) -> list[Event]:
        """Load the N most recent events by created_at descending."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
            (n,),
        )
        return self._rows_to_events(cursor.fetchall())

    def load_by_type(self, event_type: EventType) -> list[Event]:
        """Load all events of a specific type."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM events WHERE type = ? ORDER BY created_at",
            (event_type.value,),
        )
        return self._rows_to_events(cursor.fetchall())

    def load_immortal(self) -> list[Event]:
        """Load all immortal events (decisions and rejections)."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM events WHERE immortal = 1 ORDER BY created_at")
        return self._rows_to_events(cursor.fetchall())

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
        conn = self._get_conn()

        # Build base query with optional branch filter
        if branch:
            base_clause = "WHERE (git_branch = ? OR git_branch = '' OR git_branch IS NULL)"
            base_params: tuple = (branch,)
        else:
            base_clause = ""
            base_params = ()

        # Load all matching events (we need them for salience calculation)
        query = f"SELECT * FROM events {base_clause}"
        cursor = conn.execute(query, base_params)
        all_events = self._rows_to_events(cursor.fetchall())

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
            active_plan = [
                latest_plan,
                *sorted(completed_steps, key=lambda e: e.created_at),
            ]

        # Recent events: top by effective salience, excluding already-included
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

        Used for reinforcement - events that are retrieved for
        briefings get boosted salience.
        """
        if not event_ids:
            return

        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        # Update each event's access metadata
        for event_id in event_ids:
            conn.execute(
                """
                UPDATE events
                SET accessed_at = ?,
                    access_count = access_count + 1
                WHERE id = ?
                """,
                (now, event_id),
            )

        conn.commit()

    def clear(self) -> None:
        """Remove all events from the store."""
        conn = self._get_conn()
        conn.execute("DELETE FROM events")
        conn.commit()

    def count(self) -> int:
        """Return the number of events in the store."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM events")
        return cursor.fetchone()[0]

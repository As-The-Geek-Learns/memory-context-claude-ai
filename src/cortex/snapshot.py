"""Snapshot caching for briefing generation.

Provides fast briefing retrieval by caching generated markdown in SQLite.
Snapshots are branch-specific and expire after a configurable TTL.

Tier 1+ only — requires SQLite storage backend.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# WHAT: Default snapshot TTL in hours.
# WHY: 1 hour balances freshness with performance; tunable via config.
DEFAULT_SNAPSHOT_TTL_HOURS = 1


@dataclass
class Snapshot:
    """A cached briefing snapshot.

    Attributes:
        id: Database row ID.
        git_branch: Branch this snapshot was generated for (empty = all branches).
        briefing_markdown: The cached markdown content.
        event_ids: JSON list of event IDs included in the briefing.
        last_event_id: ID of the most recent event when snapshot was created.
        created_at: ISO timestamp when snapshot was created.
        expires_at: ISO timestamp when snapshot expires.
    """

    id: int
    git_branch: str
    briefing_markdown: str
    event_ids: list[str]
    last_event_id: str
    created_at: str
    expires_at: str

    @property
    def is_expired(self) -> bool:
        """Check if the snapshot has expired."""
        expires = datetime.fromisoformat(self.expires_at)
        now = datetime.now(timezone.utc)
        return now >= expires


def save_snapshot(
    conn: sqlite3.Connection,
    branch: str,
    markdown: str,
    event_ids: list[str],
    last_event_id: str,
    ttl_hours: float = DEFAULT_SNAPSHOT_TTL_HOURS,
) -> int:
    """Save a briefing snapshot to the database.

    Replaces any existing snapshot for the same branch.

    Args:
        conn: SQLite connection with initialized schema.
        branch: Git branch this snapshot is for (empty string for all branches).
        markdown: The generated briefing markdown.
        event_ids: List of event IDs included in this briefing.
        last_event_id: ID of the most recent event when snapshot was created.
        ttl_hours: Hours until this snapshot expires (default: 1).

    Returns:
        The row ID of the saved snapshot.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    # WHAT: Delete existing snapshots for this branch before inserting.
    # WHY: Only one valid snapshot per branch at a time.
    conn.execute("DELETE FROM snapshots WHERE git_branch = ?", (branch,))

    cursor = conn.execute(
        """
        INSERT INTO snapshots (
            git_branch, briefing_markdown, event_ids, last_event_id,
            created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            branch,
            markdown,
            json.dumps(event_ids),
            last_event_id,
            now.isoformat(),
            expires.isoformat(),
        ),
    )
    conn.commit()
    return cursor.lastrowid or 0


def get_valid_snapshot(
    conn: sqlite3.Connection,
    branch: str,
) -> Snapshot | None:
    """Get a valid (non-expired) snapshot for the given branch.

    Args:
        conn: SQLite connection with initialized schema.
        branch: Git branch to get snapshot for (empty string for all branches).

    Returns:
        Snapshot object if a valid one exists, None otherwise.
    """
    now = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        """
        SELECT id, git_branch, briefing_markdown, event_ids, last_event_id,
               created_at, expires_at
        FROM snapshots
        WHERE git_branch = ? AND expires_at > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (branch, now),
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Snapshot(
        id=row["id"],
        git_branch=row["git_branch"],
        briefing_markdown=row["briefing_markdown"],
        event_ids=json.loads(row["event_ids"]),
        last_event_id=row["last_event_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def invalidate_snapshots(
    conn: sqlite3.Connection,
    branch: str | None = None,
) -> int:
    """Invalidate (delete) snapshots for a branch or all branches.

    Called when events are appended to ensure stale snapshots aren't served.

    Args:
        conn: SQLite connection with initialized schema.
        branch: Branch to invalidate. If None, invalidates all snapshots.

    Returns:
        Number of snapshots deleted.
    """
    if branch is None:
        cursor = conn.execute("DELETE FROM snapshots")
    else:
        # WHAT: Invalidate both the specific branch and the "all branches" snapshot.
        # WHY: New events on a branch affect both branch-specific and global briefings.
        cursor = conn.execute(
            "DELETE FROM snapshots WHERE git_branch = ? OR git_branch = ''",
            (branch,),
        )
    conn.commit()
    return cursor.rowcount


def cleanup_expired_snapshots(conn: sqlite3.Connection) -> int:
    """Remove all expired snapshots from the database.

    Called periodically to prevent unbounded growth.

    Args:
        conn: SQLite connection with initialized schema.

    Returns:
        Number of expired snapshots deleted.
    """
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute("DELETE FROM snapshots WHERE expires_at <= ?", (now,))
    conn.commit()
    return cursor.rowcount


def get_snapshot_stats(conn: sqlite3.Connection) -> dict:
    """Get statistics about cached snapshots.

    Useful for cortex status output.

    Args:
        conn: SQLite connection.

    Returns:
        Dict with total_count, valid_count, branches list.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Total count
    cursor = conn.execute("SELECT COUNT(*) FROM snapshots")
    total = cursor.fetchone()[0]

    # Valid (non-expired) count
    cursor = conn.execute("SELECT COUNT(*) FROM snapshots WHERE expires_at > ?", (now,))
    valid = cursor.fetchone()[0]

    # List of branches with valid snapshots
    cursor = conn.execute(
        "SELECT DISTINCT git_branch FROM snapshots WHERE expires_at > ?",
        (now,),
    )
    branches = [row["git_branch"] for row in cursor.fetchall()]

    return {
        "total_count": total,
        "valid_count": valid,
        "branches": branches,
    }

"""SQLite database management for Cortex.

Provides connection management, schema creation, and migrations for the
SQLite-backed event store. Uses WAL mode for concurrent reads during writes
(important for hooks that may overlap).

Schema version is tracked for migrations:
- Version 1: Tier 1 (events, FTS5, snapshots, hook_state)
- Version 2: Tier 2 (adds embedding column for vector search)
"""

import sqlite3
from pathlib import Path

from cortex.config import CortexConfig, get_project_dir

# WHAT: Current schema version for migration tracking.
# WHY: Enables safe schema upgrades between tiers.
SCHEMA_VERSION = 2


def get_db_path(project_hash: str, config: CortexConfig | None = None) -> Path:
    """Return path to project's SQLite database.

    Args:
        project_hash: 16-character hex hash identifying the project.
        config: Optional config override.

    Returns:
        Path to ~/.cortex/projects/<hash>/events.db
    """
    return get_project_dir(project_hash, config) / "events.db"


def connect(project_hash: str, config: CortexConfig | None = None) -> sqlite3.Connection:
    """Open a connection to the project's SQLite database.

    Configures:
    - WAL mode for concurrent reads during writes
    - NORMAL synchronous mode (safe with WAL, faster than FULL)
    - Row factory for dict-like access

    Args:
        project_hash: 16-character hex hash identifying the project.
        config: Optional config override.

    Returns:
        sqlite3.Connection configured for Cortex use.
    """
    db_path = get_db_path(project_hash, config)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # WHAT: WAL mode allows concurrent readers during writes.
    # WHY: Hooks (stop, precompact, session-start) may overlap; WAL prevents locks.
    conn.execute("PRAGMA journal_mode=WAL")

    # WHAT: NORMAL synchronous is safe with WAL and faster than FULL.
    # WHY: WAL guarantees durability; NORMAL avoids extra fsync per commit.
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist.

    Idempotent — safe to call on every connection. Uses IF NOT EXISTS
    for all DDL statements.

    Args:
        conn: SQLite connection to initialize.
    """
    # WHAT: Events table with all 14 Event dataclass fields.
    # WHY: Direct mapping from Event model for simple serialization.
    conn.executescript("""
        -- Main events table
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            git_branch TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            salience REAL NOT NULL DEFAULT 0.5,
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            accessed_at TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            immortal INTEGER NOT NULL DEFAULT 0,
            provenance TEXT NOT NULL DEFAULT '',
            embedding BLOB DEFAULT NULL
        );

        -- Indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
        CREATE INDEX IF NOT EXISTS idx_events_immortal ON events(immortal) WHERE immortal = 1;
        CREATE INDEX IF NOT EXISTS idx_events_git_branch ON events(git_branch);
        CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_salience ON events(salience DESC);

        -- Content hash index for deduplication
        CREATE INDEX IF NOT EXISTS idx_events_content_hash
            ON events(type, substr(content, 1, 100), session_id);

        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );

        -- Briefing snapshot cache
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            git_branch TEXT NOT NULL DEFAULT '',
            briefing_markdown TEXT NOT NULL,
            event_ids TEXT NOT NULL,
            last_event_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_branch
            ON snapshots(git_branch, created_at DESC);

        -- Hook state (replaces state.json in Tier 0)
        CREATE TABLE IF NOT EXISTS hook_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)

    # Initialize FTS5 if not exists
    _initialize_fts5(conn)

    # Run schema migrations
    _run_migrations(conn)

    # Record schema version if not already present
    _record_schema_version(conn)

    conn.commit()


def _initialize_fts5(conn: sqlite3.Connection) -> None:
    """Create FTS5 virtual table and sync triggers.

    FTS5 provides BM25 full-text search on event content.
    Triggers keep the FTS index in sync with the events table.

    Args:
        conn: SQLite connection.
    """
    # WHAT: Check if FTS5 table already exists.
    # WHY: CREATE VIRTUAL TABLE doesn't support IF NOT EXISTS cleanly.
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'")
    if cursor.fetchone() is not None:
        return

    # WHAT: FTS5 external content table linked to events.
    # WHY: Avoids storing content twice; FTS5 reads from events table.
    conn.executescript("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            content,
            content='events',
            content_rowid='rowid'
        );

        -- Trigger: keep FTS in sync on INSERT
        CREATE TRIGGER events_fts_ai AFTER INSERT ON events BEGIN
            INSERT INTO events_fts(rowid, content) VALUES (new.rowid, new.content);
        END;

        -- Trigger: keep FTS in sync on DELETE
        CREATE TRIGGER events_fts_ad AFTER DELETE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
        END;

        -- Trigger: keep FTS in sync on UPDATE
        CREATE TRIGGER events_fts_au AFTER UPDATE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
            INSERT INTO events_fts(rowid, content) VALUES (new.rowid, new.content);
        END;
    """)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run schema migrations to bring database up to current version.

    Migrations are idempotent and safe to run multiple times.

    Args:
        conn: SQLite connection.
    """
    current_version = get_schema_version(conn)

    # Migration 1 -> 2: Add embedding column for Tier 2
    if current_version < 2:
        _migrate_v1_to_v2(conn)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Migrate from schema v1 to v2: add embedding column.

    Args:
        conn: SQLite connection.
    """
    from datetime import datetime, timezone

    # Check if embedding column already exists
    cursor = conn.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cursor.fetchall()}
    if "embedding" in columns:
        return

    # Add embedding column
    conn.execute("ALTER TABLE events ADD COLUMN embedding BLOB DEFAULT NULL")

    # Record migration
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
        (2, now, "Tier 2: Added embedding column for vector search"),
    )


def _record_schema_version(conn: sqlite3.Connection) -> None:
    """Record the current schema version if not already present.

    Args:
        conn: SQLite connection.
    """
    from datetime import datetime, timezone

    cursor = conn.execute(
        "SELECT version FROM schema_version WHERE version = ?",
        (SCHEMA_VERSION,),
    )
    if cursor.fetchone() is not None:
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
        (SCHEMA_VERSION, now, "Tier 2 schema: events, FTS5, snapshots, hook_state, embedding"),
    )


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return current schema version, or 0 if not initialized.

    Args:
        conn: SQLite connection.

    Returns:
        Schema version number (1 for Tier 1, 0 if uninitialized).
    """
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        # Table doesn't exist — uninitialized database
        return 0


def check_fts5_available() -> bool:
    """Check if FTS5 is available in this Python's SQLite.

    FTS5 requires SQLite 3.9.0+ and must be compiled with FTS5 enabled.
    Python 3.11+ typically includes FTS5.

    Returns:
        True if FTS5 is available, False otherwise.
    """
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def check_vec_available() -> bool:
    """Check if sqlite-vec extension is available.

    sqlite-vec provides vector similarity search for embeddings.

    Returns:
        True if sqlite-vec is available, False otherwise.
    """
    conn = None
    try:
        import sqlite_vec

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except (ImportError, sqlite3.OperationalError, AttributeError):
        return False
    finally:
        if conn is not None:
            try:
                conn.enable_load_extension(False)
            except (sqlite3.OperationalError, AttributeError):
                pass
            conn.close()


def load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec extension into a connection.

    Args:
        conn: SQLite connection.

    Returns:
        True if loaded successfully, False otherwise.
    """
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except (ImportError, sqlite3.OperationalError, AttributeError):
        return False
    finally:
        try:
            conn.enable_load_extension(False)
        except (sqlite3.OperationalError, AttributeError):
            pass


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Reclaim space and optimize the database.

    Should be called periodically (e.g., after migration or bulk deletes).
    Note: VACUUM requires exclusive access and may be slow on large DBs.

    Args:
        conn: SQLite connection.
    """
    conn.execute("VACUUM")


def get_database_stats(conn: sqlite3.Connection) -> dict:
    """Return statistics about the database.

    Useful for cortex status output.

    Args:
        conn: SQLite connection.

    Returns:
        Dict with event_count, schema_version, fts_enabled, embedding stats.
    """
    stats = {}

    # Event count
    cursor = conn.execute("SELECT COUNT(*) FROM events")
    stats["event_count"] = cursor.fetchone()[0]

    # Schema version
    stats["schema_version"] = get_schema_version(conn)

    # FTS5 enabled check
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'")
    stats["fts_enabled"] = cursor.fetchone() is not None

    # Snapshot count
    cursor = conn.execute("SELECT COUNT(*) FROM snapshots")
    stats["snapshot_count"] = cursor.fetchone()[0]

    # Embedding stats (Tier 2)
    cursor = conn.execute("SELECT COUNT(*) FROM events WHERE embedding IS NOT NULL")
    stats["events_with_embeddings"] = cursor.fetchone()[0]

    # Vec extension availability
    stats["vec_available"] = check_vec_available()

    return stats

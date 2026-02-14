"""Tests for the SQLite database module (db.py).

Covers connection management, schema creation, FTS5 initialization,
and database utilities.
"""

from cortex.config import CortexConfig
from cortex.db import (
    SCHEMA_VERSION,
    check_fts5_available,
    connect,
    get_database_stats,
    get_db_path,
    get_schema_version,
    initialize_schema,
    vacuum_database,
)


class TestGetDbPath:
    """Tests for get_db_path()."""

    def test_returns_path_in_project_dir(self, sample_project_hash: str, sample_config: CortexConfig):
        """Path should be ~/.cortex/projects/<hash>/events.db."""
        path = get_db_path(sample_project_hash, sample_config)
        assert path.name == "events.db"
        assert path.parent.name == sample_project_hash
        assert path.parent.parent.name == "projects"

    def test_uses_config_cortex_home(self, tmp_cortex_home, sample_project_hash: str):
        """Should use cortex_home from config."""
        config = CortexConfig(cortex_home=tmp_cortex_home)
        path = get_db_path(sample_project_hash, config)
        assert str(tmp_cortex_home) in str(path)


class TestConnect:
    """Tests for connect()."""

    def test_creates_database_file(self, sample_project_hash: str, sample_config: CortexConfig):
        """Connection should create the database file."""
        db_path = get_db_path(sample_project_hash, sample_config)
        assert not db_path.exists()

        conn = connect(sample_project_hash, sample_config)
        conn.close()

        assert db_path.exists()

    def test_enables_wal_mode(self, sample_project_hash: str, sample_config: CortexConfig):
        """Connection should use WAL journal mode."""
        conn = connect(sample_project_hash, sample_config)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()

        assert mode.lower() == "wal"

    def test_row_factory_returns_row_objects(self, sample_project_hash: str, sample_config: CortexConfig):
        """Rows should be accessible like dicts."""
        conn = connect(sample_project_hash, sample_config)
        conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'foo')")

        cursor = conn.execute("SELECT * FROM test")
        row = cursor.fetchone()
        conn.close()

        # sqlite3.Row supports both index and key access
        assert row["id"] == 1
        assert row["name"] == "foo"
        assert row[0] == 1

    def test_multiple_connections_allowed(self, sample_project_hash: str, sample_config: CortexConfig):
        """Multiple connections should work (WAL allows concurrent readers)."""
        conn1 = connect(sample_project_hash, sample_config)
        conn2 = connect(sample_project_hash, sample_config)

        # Both can read
        initialize_schema(conn1)
        cursor = conn2.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 0

        conn1.close()
        conn2.close()


class TestInitializeSchema:
    """Tests for initialize_schema()."""

    def test_creates_events_table(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create the events table with all columns."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("PRAGMA table_info(events)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id",
            "session_id",
            "project",
            "git_branch",
            "type",
            "content",
            "metadata",
            "salience",
            "confidence",
            "created_at",
            "accessed_at",
            "access_count",
            "immortal",
            "provenance",
        }
        assert columns == expected

    def test_creates_indexes(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create all expected indexes."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row["name"] for row in cursor.fetchall()}
        conn.close()

        # Check key indexes exist (some may be auto-generated)
        assert "idx_events_created_at" in indexes
        assert "idx_events_type" in indexes
        assert "idx_events_immortal" in indexes
        assert "idx_events_git_branch" in indexes

    def test_creates_snapshots_table(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create the snapshots table."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("PRAGMA table_info(snapshots)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id",
            "git_branch",
            "briefing_markdown",
            "event_ids",
            "last_event_id",
            "created_at",
            "expires_at",
        }
        assert columns == expected

    def test_creates_hook_state_table(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create the hook_state table."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("PRAGMA table_info(hook_state)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()

        assert columns == {"key", "value"}

    def test_creates_schema_version_table(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create schema_version with current version."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("SELECT version, description FROM schema_version")
        row = cursor.fetchone()
        conn.close()

        assert row["version"] == SCHEMA_VERSION
        assert "Tier 1" in row["description"]

    def test_idempotent(self, sample_project_hash: str, sample_config: CortexConfig):
        """Calling initialize_schema multiple times should be safe."""
        conn = connect(sample_project_hash, sample_config)

        # Call multiple times
        initialize_schema(conn)
        initialize_schema(conn)
        initialize_schema(conn)

        # Should still work
        cursor = conn.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 0
        conn.close()


class TestFts5:
    """Tests for FTS5 full-text search support."""

    def test_fts5_available(self):
        """FTS5 should be available in Python 3.11+."""
        assert check_fts5_available() is True

    def test_creates_fts_virtual_table(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should create the events_fts virtual table."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row["name"] == "events_fts"

    def test_fts_trigger_on_insert(self, sample_project_hash: str, sample_config: CortexConfig):
        """Inserting into events should populate FTS index."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        # Insert an event
        conn.execute("""
            INSERT INTO events (id, type, content, created_at, accessed_at)
            VALUES ('evt1', 'decision_made', 'Use SQLite for storage', '2026-01-01', '2026-01-01')
        """)
        conn.commit()

        # Search via FTS
        cursor = conn.execute("SELECT * FROM events_fts WHERE events_fts MATCH 'SQLite'")
        results = cursor.fetchall()
        conn.close()

        assert len(results) == 1

    def test_fts_trigger_on_delete(self, sample_project_hash: str, sample_config: CortexConfig):
        """Deleting from events should update FTS index."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        # Insert and then delete
        conn.execute("""
            INSERT INTO events (id, type, content, created_at, accessed_at)
            VALUES ('evt1', 'decision_made', 'Use SQLite for storage', '2026-01-01', '2026-01-01')
        """)
        conn.commit()

        conn.execute("DELETE FROM events WHERE id = 'evt1'")
        conn.commit()

        # FTS should be empty
        cursor = conn.execute("SELECT * FROM events_fts WHERE events_fts MATCH 'SQLite'")
        results = cursor.fetchall()
        conn.close()

        assert len(results) == 0

    def test_fts_bm25_ranking(self, sample_project_hash: str, sample_config: CortexConfig):
        """FTS5 should support BM25 relevance ranking."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        # Insert events with varying relevance
        conn.execute("""
            INSERT INTO events (id, type, content, created_at, accessed_at) VALUES
            ('evt1', 'knowledge', 'SQLite is a database', '2026-01-01', '2026-01-01'),
            ('evt2', 'knowledge', 'SQLite SQLite SQLite', '2026-01-01', '2026-01-01'),
            ('evt3', 'knowledge', 'PostgreSQL is a database', '2026-01-01', '2026-01-01')
        """)
        conn.commit()

        # Search with BM25 ranking (lower score = more relevant)
        cursor = conn.execute("""
            SELECT e.id, bm25(events_fts) as score
            FROM events e
            JOIN events_fts fts ON e.rowid = fts.rowid
            WHERE events_fts MATCH 'SQLite'
            ORDER BY bm25(events_fts)
        """)
        results = cursor.fetchall()
        conn.close()

        assert len(results) == 2
        # evt2 should rank higher (more mentions)
        assert results[0]["id"] == "evt2"


class TestGetSchemaVersion:
    """Tests for get_schema_version()."""

    def test_returns_zero_for_uninitialized(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should return 0 if schema_version table doesn't exist."""
        conn = connect(sample_project_hash, sample_config)
        # Don't initialize schema
        version = get_schema_version(conn)
        conn.close()

        assert version == 0

    def test_returns_current_version(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should return SCHEMA_VERSION after initialization."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        version = get_schema_version(conn)
        conn.close()

        assert version == SCHEMA_VERSION


class TestGetDatabaseStats:
    """Tests for get_database_stats()."""

    def test_returns_stats_dict(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should return a dict with expected keys."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        stats = get_database_stats(conn)
        conn.close()

        assert "event_count" in stats
        assert "schema_version" in stats
        assert "fts_enabled" in stats
        assert "snapshot_count" in stats

    def test_event_count_accurate(self, sample_project_hash: str, sample_config: CortexConfig):
        """Event count should reflect inserted events."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        # Insert some events
        for i in range(5):
            conn.execute(f"""
                INSERT INTO events (id, type, content, created_at, accessed_at)
                VALUES ('evt{i}', 'knowledge', 'Test event {i}', '2026-01-01', '2026-01-01')
            """)
        conn.commit()

        stats = get_database_stats(conn)
        conn.close()

        assert stats["event_count"] == 5

    def test_fts_enabled_true(self, sample_project_hash: str, sample_config: CortexConfig):
        """FTS enabled should be True after initialization."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        stats = get_database_stats(conn)
        conn.close()

        assert stats["fts_enabled"] is True


class TestVacuumDatabase:
    """Tests for vacuum_database()."""

    def test_vacuum_succeeds(self, sample_project_hash: str, sample_config: CortexConfig):
        """Vacuum should complete without error."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        # Insert and delete to create fragmentation
        for i in range(100):
            conn.execute(f"""
                INSERT INTO events (id, type, content, created_at, accessed_at)
                VALUES ('evt{i}', 'knowledge', 'Test event {i}', '2026-01-01', '2026-01-01')
            """)
        conn.commit()

        conn.execute("DELETE FROM events WHERE id LIKE 'evt%'")
        conn.commit()

        # Vacuum should work
        vacuum_database(conn)
        conn.close()


class TestSchemaIntegrity:
    """Tests for overall schema integrity."""

    def test_event_insert_with_all_fields(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should be able to insert an event with all fields."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        conn.execute("""
            INSERT INTO events (
                id, session_id, project, git_branch, type, content, metadata,
                salience, confidence, created_at, accessed_at, access_count,
                immortal, provenance
            ) VALUES (
                'test-uuid', 'session-001', 'proj-hash', 'main', 'decision_made',
                'Chose SQLite', '{"reason": "zero-config"}', 0.9, 1.0,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 1, 'layer3:MEMORY_TAG'
            )
        """)
        conn.commit()

        cursor = conn.execute("SELECT * FROM events WHERE id = 'test-uuid'")
        row = cursor.fetchone()
        conn.close()

        assert row["id"] == "test-uuid"
        assert row["type"] == "decision_made"
        assert row["immortal"] == 1
        assert row["salience"] == 0.9

    def test_snapshot_insert(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should be able to insert and retrieve snapshots."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        conn.execute("""
            INSERT INTO snapshots (
                git_branch, briefing_markdown, event_ids, last_event_id,
                created_at, expires_at
            ) VALUES (
                'main', '# Briefing\n\nDecisions...', '["evt1", "evt2"]', 'evt2',
                '2026-01-01T00:00:00Z', '2026-01-01T01:00:00Z'
            )
        """)
        conn.commit()

        cursor = conn.execute("SELECT * FROM snapshots WHERE git_branch = 'main'")
        row = cursor.fetchone()
        conn.close()

        assert row["briefing_markdown"].startswith("# Briefing")
        assert "evt1" in row["event_ids"]

    def test_hook_state_insert(self, sample_project_hash: str, sample_config: CortexConfig):
        """Should be able to store hook state."""
        conn = connect(sample_project_hash, sample_config)
        initialize_schema(conn)

        conn.execute(
            "INSERT INTO hook_state (key, value) VALUES (?, ?)",
            ("last_transcript_position", "12345"),
        )
        conn.commit()

        cursor = conn.execute("SELECT value FROM hook_state WHERE key = ?", ("last_transcript_position",))
        row = cursor.fetchone()
        conn.close()

        assert row["value"] == "12345"

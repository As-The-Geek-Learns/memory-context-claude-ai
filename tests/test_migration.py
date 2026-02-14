"""Tests for Tier 0 → Tier 1 migration functionality."""

import json
from pathlib import Path

import pytest

from cortex.config import CortexConfig
from cortex.migration import (
    MigrationResult,
    archive_tier0_files,
    create_backup,
    detect_tier,
    get_migration_status,
    load_tier0_events,
    load_tier0_hook_state,
    migrate_events_to_sqlite,
    migrate_hook_state_to_sqlite,
    rollback,
    upgrade,
)
from cortex.models import EventType, create_event
from cortex.sqlite_store import SQLiteEventStore
from cortex.store import EventStore, HookState

# --- Fixtures ---


@pytest.fixture
def tier0_project(sample_project_hash: str, sample_config: CortexConfig) -> tuple[str, CortexConfig]:
    """Create a Tier 0 project with events and hook state.

    Uses the shared sample_config fixture which has a proper temp cortex_home.
    Returns tuple of (project_hash, config).
    """
    # Create some events in JSON store
    store = EventStore(sample_project_hash, sample_config)
    events = [
        create_event(EventType.DECISION_MADE, "Use SQLite for storage"),
        create_event(EventType.KNOWLEDGE_ACQUIRED, "WAL mode is fast"),
        create_event(EventType.FILE_MODIFIED, "Updated config.py"),
    ]
    for event in events:
        store.append(event)

    # Create hook state (uses Tier 0 keys)
    state = HookState(sample_project_hash, sample_config)
    state.save(
        {
            "last_transcript_position": 12345,
            "last_session_id": "session-abc",
        }
    )

    return sample_project_hash, sample_config


@pytest.fixture
def empty_project(sample_project_hash: str, sample_config: CortexConfig) -> tuple[str, CortexConfig]:
    """Create an empty project directory (no storage).

    Uses the shared sample_config fixture which has a proper temp cortex_home.
    Returns tuple of (project_hash, config).
    """
    return sample_project_hash, sample_config


# --- Test Classes ---


class TestDetectTier:
    """Tests for detect_tier function."""

    def test_detect_tier_0(self, tier0_project: tuple[str, CortexConfig]):
        """detect_tier should return 0 for JSON-based storage."""
        project_hash, config = tier0_project
        assert detect_tier(project_hash, config) == 0

    def test_detect_tier_1(self, tier0_project: tuple[str, CortexConfig]):
        """detect_tier should return 1 for SQLite-based storage."""
        project_hash, config = tier0_project

        # Create SQLite database
        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        store = SQLiteEventStore(project_hash, sqlite_config)
        store.append(create_event(EventType.DECISION_MADE, "Test"))
        store.close()

        assert detect_tier(project_hash, sqlite_config) == 1

    def test_detect_tier_none(self, empty_project: tuple[str, CortexConfig]):
        """detect_tier should return -1 when no storage exists."""
        project_hash, config = empty_project
        assert detect_tier(project_hash, config) == -1


class TestGetMigrationStatus:
    """Tests for get_migration_status function."""

    def test_status_tier0_ready(self, tier0_project: tuple[str, CortexConfig]):
        """get_migration_status should show ready to upgrade for Tier 0."""
        project_hash, config = tier0_project
        status = get_migration_status(project_hash, config)

        assert status["current_tier"] == 0
        assert status["can_upgrade"] is True
        assert status["events_count"] == 3
        assert status["has_hook_state"] is True
        assert "Ready to upgrade" in status["details"]

    def test_status_no_storage(self, empty_project: tuple[str, CortexConfig]):
        """get_migration_status should show not initialized for empty project."""
        project_hash, config = empty_project
        status = get_migration_status(project_hash, config)

        assert status["current_tier"] == -1
        assert status["can_upgrade"] is False
        assert "not initialized" in status["details"]

    def test_status_already_tier1(self, tier0_project: tuple[str, CortexConfig]):
        """get_migration_status should show already on Tier 1."""
        project_hash, config = tier0_project

        # Create SQLite database (both exist now)
        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        store = SQLiteEventStore(project_hash, sqlite_config)
        # Force database file creation by accessing connection
        store.append(create_event(EventType.DECISION_MADE, "Test"))
        store.close()

        # detect_tier will return 1 since SQLite exists
        status = get_migration_status(project_hash, sqlite_config)
        assert status["current_tier"] == 1


class TestCreateBackup:
    """Tests for create_backup function."""

    def test_backup_creates_directory(self, tier0_project: tuple[str, CortexConfig]):
        """create_backup should create timestamped backup directory."""
        project_hash, config = tier0_project
        backup_path = create_backup(project_hash, config)

        assert backup_path.exists()
        assert "tier0_" in backup_path.name
        assert "backups" in str(backup_path)

    def test_backup_copies_events_json(self, tier0_project: tuple[str, CortexConfig]):
        """create_backup should copy events.json."""
        project_hash, config = tier0_project
        backup_path = create_backup(project_hash, config)

        events_backup = backup_path / "events.json"
        assert events_backup.exists()

        with open(events_backup) as f:
            events = json.load(f)
        assert len(events) == 3

    def test_backup_copies_state_json(self, tier0_project: tuple[str, CortexConfig]):
        """create_backup should copy state.json."""
        project_hash, config = tier0_project
        backup_path = create_backup(project_hash, config)

        state_backup = backup_path / "state.json"
        assert state_backup.exists()

        with open(state_backup) as f:
            state = json.load(f)
        assert state["last_transcript_position"] == 12345


class TestLoadTier0Events:
    """Tests for load_tier0_events function."""

    def test_load_events(self, tier0_project: tuple[str, CortexConfig]):
        """load_tier0_events should return all events from JSON store."""
        project_hash, config = tier0_project
        events = load_tier0_events(project_hash, config)

        assert len(events) == 3
        assert events[0].type == EventType.DECISION_MADE
        assert events[1].type == EventType.KNOWLEDGE_ACQUIRED


class TestLoadTier0HookState:
    """Tests for load_tier0_hook_state function."""

    def test_load_hook_state(self, tier0_project: tuple[str, CortexConfig]):
        """load_tier0_hook_state should return dict from JSON."""
        project_hash, config = tier0_project
        state = load_tier0_hook_state(project_hash, config)

        assert state is not None
        assert state["last_transcript_position"] == 12345
        assert state["last_session_id"] == "session-abc"

    def test_load_hook_state_missing(self, empty_project: tuple[str, CortexConfig]):
        """load_tier0_hook_state should return None if no state file."""
        project_hash, config = empty_project
        state = load_tier0_hook_state(project_hash, config)
        assert state is None


class TestMigrateEventsToSqlite:
    """Tests for migrate_events_to_sqlite function."""

    def test_migrate_events(self, tier0_project: tuple[str, CortexConfig]):
        """migrate_events_to_sqlite should insert events into SQLite."""
        project_hash, config = tier0_project
        events = load_tier0_events(project_hash, config)

        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        count = migrate_events_to_sqlite(events, project_hash, sqlite_config)

        assert count == 3

        # Verify events are in SQLite
        store = SQLiteEventStore(project_hash, sqlite_config)
        assert store.count() == 3
        store.close()

    def test_migrate_empty_events(self, empty_project: tuple[str, CortexConfig]):
        """migrate_events_to_sqlite should handle empty list."""
        project_hash, config = empty_project

        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        count = migrate_events_to_sqlite([], project_hash, sqlite_config)

        assert count == 0


class TestMigrateHookStateToSqlite:
    """Tests for migrate_hook_state_to_sqlite function."""

    def test_migrate_hook_state(self, tier0_project: tuple[str, CortexConfig]):
        """migrate_hook_state_to_sqlite should insert state into SQLite."""
        project_hash, config = tier0_project
        state = load_tier0_hook_state(project_hash, config)
        assert state is not None

        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        success = migrate_hook_state_to_sqlite(state, project_hash, sqlite_config)

        assert success is True


class TestArchiveTier0Files:
    """Tests for archive_tier0_files function."""

    def test_archive_moves_files(self, tier0_project: tuple[str, CortexConfig]):
        """archive_tier0_files should move JSON files to archive/."""
        project_hash, config = tier0_project

        cortex_home = Path(config.cortex_home)
        project_dir = cortex_home / "projects" / project_hash

        # Verify files exist before archive
        assert (project_dir / "events.json").exists()
        assert (project_dir / "state.json").exists()

        archive_tier0_files(project_hash, config)

        # Verify files moved to archive
        assert not (project_dir / "events.json").exists()
        assert not (project_dir / "state.json").exists()
        assert (project_dir / "archive" / "events.json").exists()
        assert (project_dir / "archive" / "state.json").exists()


class TestUpgrade:
    """Tests for upgrade function."""

    def test_upgrade_success(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade should migrate Tier 0 to Tier 1 successfully."""
        project_hash, config = tier0_project
        result = upgrade(project_hash, config)

        assert result.success is True
        assert result.events_migrated == 3
        assert result.hook_state_migrated is True
        assert result.backup_path is not None
        assert result.error is None
        assert result.dry_run is False

    def test_upgrade_creates_backup(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade should create backup before migration."""
        project_hash, config = tier0_project
        result = upgrade(project_hash, config)

        assert result.backup_path is not None
        assert result.backup_path.exists()
        assert (result.backup_path / "events.json").exists()

    def test_upgrade_archives_json(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade should archive JSON files after migration."""
        project_hash, config = tier0_project
        upgrade(project_hash, config)

        cortex_home = Path(config.cortex_home)
        project_dir = cortex_home / "projects" / project_hash

        assert not (project_dir / "events.json").exists()
        assert (project_dir / "archive" / "events.json").exists()

    def test_upgrade_dry_run(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade with dry_run should not make changes."""
        project_hash, config = tier0_project
        result = upgrade(project_hash, config, dry_run=True)

        assert result.success is True
        assert result.dry_run is True
        assert result.events_migrated == 3  # Reports what would be migrated
        assert result.backup_path is None  # No actual backup

        # Verify no changes made
        cortex_home = Path(config.cortex_home)
        project_dir = cortex_home / "projects" / project_hash
        assert (project_dir / "events.json").exists()
        assert not (project_dir / "events.db").exists()

    def test_upgrade_already_tier1(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade should fail if already on Tier 1."""
        project_hash, config = tier0_project

        # First upgrade
        upgrade(project_hash, config)

        # Second upgrade should fail
        result = upgrade(project_hash, config)
        assert result.success is False
        assert "Already on Tier 1" in result.error

    def test_upgrade_no_storage(self, empty_project: tuple[str, CortexConfig]):
        """upgrade should fail if no storage exists."""
        project_hash, config = empty_project
        result = upgrade(project_hash, config)

        assert result.success is False
        assert "not initialized" in result.error

    def test_upgrade_force_overwrites(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade with force should overwrite existing SQLite."""
        project_hash, config = tier0_project

        # Create existing SQLite with different content
        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        store = SQLiteEventStore(project_hash, sqlite_config)
        store.append(create_event(EventType.DECISION_MADE, "Old content"))
        store.close()

        # Force upgrade should overwrite
        result = upgrade(project_hash, config, force=True)
        assert result.success is True
        assert result.events_migrated == 3

        # Verify new content
        store = SQLiteEventStore(project_hash, sqlite_config)
        assert store.count() == 3  # From Tier 0, not 1 old event
        store.close()


class TestRollback:
    """Tests for rollback function."""

    def test_rollback_restores_files(self, tier0_project: tuple[str, CortexConfig]):
        """rollback should restore JSON files from backup."""
        project_hash, config = tier0_project

        # Create backup
        backup_path = create_backup(project_hash, config)

        # Simulate migration (archive files + create SQLite)
        archive_tier0_files(project_hash, config)
        sqlite_config = CortexConfig(cortex_home=config.cortex_home, storage_tier=1)
        store = SQLiteEventStore(project_hash, sqlite_config)
        # Force database file creation by accessing connection
        store.append(create_event(EventType.DECISION_MADE, "Migrated event"))
        store.close()

        cortex_home = Path(config.cortex_home)
        project_dir = cortex_home / "projects" / project_hash

        # Verify migration state
        assert not (project_dir / "events.json").exists()
        assert (project_dir / "events.db").exists()

        # Rollback
        success = rollback(project_hash, backup_path, config)
        assert success is True

        # Verify rollback state
        assert (project_dir / "events.json").exists()
        assert not (project_dir / "events.db").exists()

    def test_rollback_missing_backup(self, tier0_project: tuple[str, CortexConfig]):
        """rollback should return False if backup doesn't exist."""
        project_hash, config = tier0_project
        fake_path = Path("/nonexistent/backup")

        success = rollback(project_hash, fake_path, config)
        assert success is False


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_success_result(self):
        """MigrationResult should store success fields."""
        result = MigrationResult(
            success=True,
            events_migrated=100,
            hook_state_migrated=True,
            backup_path=Path("/tmp/backup"),
            error=None,
            dry_run=False,
        )
        assert result.success is True
        assert result.events_migrated == 100
        assert result.hook_state_migrated is True

    def test_failure_result(self):
        """MigrationResult should store failure fields."""
        result = MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            backup_path=None,
            error="Something went wrong",
            dry_run=False,
        )
        assert result.success is False
        assert result.error == "Something went wrong"


class TestCLIUpgrade:
    """Tests for CLI upgrade command."""

    def test_cmd_upgrade_import(self):
        """cmd_upgrade should be importable from cli module."""
        from cortex.cli import cmd_upgrade

        assert callable(cmd_upgrade)

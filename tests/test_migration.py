"""Tests for storage tier migration functionality (Tier 0 → 1 → 2)."""

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
    upgrade_to_tier2,
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

    def test_upgrade_already_tier1_no_tier2(self, tier0_project: tuple[str, CortexConfig], monkeypatch):
        """upgrade should fail if already on Tier 1 and Tier 2 not available."""
        project_hash, config = tier0_project

        # First upgrade
        upgrade(project_hash, config)

        # Mock sentence-transformers as unavailable for Tier 2 upgrade
        # Must patch in cortex.embeddings where the function is defined
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: False,
        )

        # Second upgrade should fail (Tier 2 not available)
        result = upgrade(project_hash, config)
        assert result.success is False
        # Error message should mention sentence-transformers requirement
        assert result.error is not None
        assert "sentence-transformers" in result.error.lower()

    def test_upgrade_no_storage(self, empty_project: tuple[str, CortexConfig]):
        """upgrade should fail if no storage exists."""
        project_hash, config = empty_project
        result = upgrade(project_hash, config)

        assert result.success is False
        assert "not initialized" in result.error

    def test_upgrade_already_at_tier2(self, tier0_project: tuple[str, CortexConfig]):
        """upgrade should fail if already at maximum tier (Tier 2)."""
        pytest.importorskip("sentence_transformers")

        project_hash, config = tier0_project

        # First upgrade to Tier 1
        result1 = upgrade(project_hash, config)
        assert result1.success is True
        assert result1.to_tier == 1

        # Second upgrade to Tier 2
        result2 = upgrade(project_hash, config)
        assert result2.success is True
        assert result2.to_tier == 2
        assert result2.embeddings_generated == 3

        # Third upgrade to Tier 3 (MCP + projections)
        result3 = upgrade(project_hash, config)
        assert result3.success is True
        assert result3.to_tier == 3

        # Fourth upgrade should fail (already at max tier)
        result4 = upgrade(project_hash, config)
        assert result4.success is False
        assert "Already on Tier 3" in result4.error


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
            embeddings_generated=0,
            backup_path=Path("/tmp/backup"),
            error=None,
            dry_run=False,
            from_tier=0,
            to_tier=1,
        )
        assert result.success is True
        assert result.events_migrated == 100
        assert result.hook_state_migrated is True
        assert result.embeddings_generated == 0
        assert result.from_tier == 0
        assert result.to_tier == 1

    def test_failure_result(self):
        """MigrationResult should store failure fields."""
        result = MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error="Something went wrong",
            dry_run=False,
            from_tier=0,
            to_tier=1,
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_tier2_result(self):
        """MigrationResult should store Tier 2 upgrade fields."""
        result = MigrationResult(
            success=True,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=50,
            backup_path=None,
            error=None,
            dry_run=False,
            from_tier=1,
            to_tier=2,
        )
        assert result.success is True
        assert result.embeddings_generated == 50
        assert result.from_tier == 1
        assert result.to_tier == 2


class TestCLIUpgrade:
    """Tests for CLI upgrade command."""

    def test_cmd_upgrade_import(self):
        """cmd_upgrade should be importable from cli module."""
        from cortex.cli import cmd_upgrade

        assert callable(cmd_upgrade)


# --- Tier 2 Migration Tests ---


@pytest.fixture
def tier1_project(sample_project_hash: str, sample_config: CortexConfig) -> tuple[str, CortexConfig]:
    """Create a Tier 1 project with events in SQLite.

    Returns tuple of (project_hash, config).
    """
    sqlite_config = CortexConfig(cortex_home=sample_config.cortex_home, storage_tier=1)

    # Create events in SQLite store
    store = SQLiteEventStore(sample_project_hash, sqlite_config)
    events = [
        create_event(EventType.DECISION_MADE, "Use SQLite for storage"),
        create_event(EventType.KNOWLEDGE_ACQUIRED, "WAL mode is fast"),
        create_event(EventType.FILE_MODIFIED, "Updated config.py"),
    ]
    for event in events:
        store.append(event)
    store.close()

    return sample_project_hash, sqlite_config


class TestDetectTier2:
    """Tests for detect_tier with Tier 2."""

    def test_detect_tier_2_with_embeddings(self, tier1_project: tuple[str, CortexConfig], monkeypatch):
        """detect_tier should return 2 when embeddings are populated."""
        project_hash, config = tier1_project

        # Mock config with storage_tier=2
        tier2_config = CortexConfig(
            cortex_home=config.cortex_home,
            storage_tier=2,
        )

        # Should detect Tier 2 based on config
        tier = detect_tier(project_hash, tier2_config)
        assert tier == 2

    def test_detect_tier_1_without_embeddings(self, tier1_project: tuple[str, CortexConfig]):
        """detect_tier should return 1 when no embeddings exist."""
        project_hash, config = tier1_project

        tier = detect_tier(project_hash, config)
        assert tier == 1


class TestGetMigrationStatusTier2:
    """Tests for get_migration_status with Tier 2."""

    def test_status_tier1_can_upgrade_to_tier2(self, tier1_project: tuple[str, CortexConfig], monkeypatch):
        """get_migration_status should show ready for Tier 2 upgrade."""
        project_hash, config = tier1_project

        # Mock sentence-transformers as available
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: True,
        )

        status = get_migration_status(project_hash, config)

        assert status["current_tier"] == 1
        assert status["can_upgrade"] is True
        assert status["target_tier"] == 2
        assert status["sentence_transformers_available"] is True
        assert "Tier 2" in status["details"]

    def test_status_tier1_no_upgrade_without_sentence_transformers(
        self, tier1_project: tuple[str, CortexConfig], monkeypatch
    ):
        """get_migration_status should not allow upgrade without sentence-transformers."""
        project_hash, config = tier1_project

        # Mock sentence-transformers as unavailable
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: False,
        )

        status = get_migration_status(project_hash, config)

        assert status["current_tier"] == 1
        assert status["can_upgrade"] is False
        assert status["sentence_transformers_available"] is False
        assert "sentence-transformers" in status["details"]


class TestUpgradeTier2:
    """Tests for upgrade_to_tier2 function."""

    def test_upgrade_to_tier2_success(self, tier1_project: tuple[str, CortexConfig]):
        """upgrade_to_tier2 should generate embeddings for all events."""
        pytest.importorskip("sentence_transformers")

        project_hash, config = tier1_project
        result = upgrade_to_tier2(project_hash, config)

        assert result.success is True
        assert result.embeddings_generated == 3
        assert result.from_tier == 1
        assert result.to_tier == 2

        # Verify embeddings exist
        store = SQLiteEventStore(project_hash, config)
        assert store.count_embeddings() == 3
        store.close()

    def test_upgrade_to_tier2_no_sentence_transformers(self, tier1_project: tuple[str, CortexConfig], monkeypatch):
        """upgrade_to_tier2 should fail without sentence-transformers."""
        project_hash, config = tier1_project

        # Mock sentence-transformers as unavailable
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: False,
        )

        result = upgrade_to_tier2(project_hash, config)

        assert result.success is False
        assert "sentence-transformers" in result.error

    def test_upgrade_via_main_function(self, tier1_project: tuple[str, CortexConfig]):
        """upgrade() should route Tier 1→2 to upgrade_to_tier2."""
        pytest.importorskip("sentence_transformers")

        project_hash, config = tier1_project
        result = upgrade(project_hash, config)

        assert result.success is True
        assert result.from_tier == 1
        assert result.to_tier == 2
        assert result.embeddings_generated == 3

    def test_upgrade_tier2_dry_run(self, tier1_project: tuple[str, CortexConfig], monkeypatch):
        """upgrade dry_run should report what would be done for Tier 2."""
        project_hash, config = tier1_project

        # Mock sentence-transformers as available
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: True,
        )

        result = upgrade(project_hash, config, dry_run=True)

        assert result.success is True
        assert result.dry_run is True
        assert result.embeddings_generated == 3
        assert result.from_tier == 1
        assert result.to_tier == 2

        # Verify no embeddings actually created
        store = SQLiteEventStore(project_hash, config)
        assert store.count_embeddings() == 0
        store.close()

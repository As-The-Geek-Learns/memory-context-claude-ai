"""Migration utilities for upgrading Cortex storage tiers.

Provides the upgrade command to migrate from Tier 0 (JSON) to Tier 1 (SQLite)
with backup, batch processing, and rollback capabilities.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cortex.config import CortexConfig, load_config
from cortex.db import connect, get_db_path, initialize_schema
from cortex.models import Event
from cortex.sqlite_store import SQLiteEventStore
from cortex.store import EventStore, HookState

# WHAT: Batch size for event insertion.
# WHY: 1000 balances memory usage with transaction efficiency.
BATCH_SIZE = 1000


@dataclass
class MigrationResult:
    """Result of a migration operation.

    Attributes:
        success: Whether the migration completed successfully.
        events_migrated: Number of events migrated.
        hook_state_migrated: Whether HookState was migrated.
        backup_path: Path to the backup directory.
        error: Error message if migration failed.
        dry_run: Whether this was a dry run (no changes made).
    """

    success: bool
    events_migrated: int
    hook_state_migrated: bool
    backup_path: Path | None
    error: str | None
    dry_run: bool


def detect_tier(project_hash: str, config: CortexConfig) -> int:
    """Detect the current storage tier for a project.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        0 if JSON storage exists, 1 if SQLite exists, -1 if no storage found.
    """
    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash

    events_json = project_dir / "events.json"
    events_db = project_dir / "events.db"

    if events_db.exists():
        return 1
    if events_json.exists():
        return 0
    return -1


def get_migration_status(project_hash: str, config: CortexConfig) -> dict:
    """Get detailed migration status for a project.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        Dict with current_tier, can_upgrade, events_count, and details.
    """
    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash

    events_json = project_dir / "events.json"
    events_db = project_dir / "events.db"
    state_json = project_dir / "state.json"

    current_tier = detect_tier(project_hash, config)

    result = {
        "current_tier": current_tier,
        "config_tier": config.storage_tier,
        "can_upgrade": False,
        "events_count": 0,
        "has_hook_state": False,
        "details": "",
    }

    if current_tier == -1:
        result["details"] = "No storage found — project not initialized"
        return result

    if current_tier == 1:
        result["details"] = "Already on Tier 1 (SQLite)"
        # Count events in SQLite
        try:
            store = SQLiteEventStore(project_hash, config)
            result["events_count"] = store.count()
            store.close()
        except Exception:
            pass
        return result

    # Tier 0 — can upgrade
    result["can_upgrade"] = True

    # Count events in JSON
    if events_json.exists():
        try:
            with open(events_json) as f:
                events = json.load(f)
                result["events_count"] = len(events)
        except Exception:
            result["events_count"] = 0

    # Check for HookState
    result["has_hook_state"] = state_json.exists()

    if events_db.exists():
        result["details"] = "Both JSON and SQLite exist — use --force to overwrite"
        result["can_upgrade"] = False
    else:
        result["details"] = f"Ready to upgrade: {result['events_count']} events"

    return result


def create_backup(project_hash: str, config: CortexConfig) -> Path:
    """Create a backup of Tier 0 files before migration.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        Path to the backup directory.

    Raises:
        FileNotFoundError: If no files to backup.
    """
    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash

    # Create timestamped backup directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = project_dir / "backups" / f"tier0_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Backup events.json
    events_json = project_dir / "events.json"
    if events_json.exists():
        shutil.copy2(events_json, backup_dir / "events.json")

    # Backup state.json (HookState)
    state_json = project_dir / "state.json"
    if state_json.exists():
        shutil.copy2(state_json, backup_dir / "state.json")

    # Backup config.json
    config_json = project_dir / "config.json"
    if config_json.exists():
        shutil.copy2(config_json, backup_dir / "config.json")

    return backup_dir


def load_tier0_events(project_hash: str, config: CortexConfig) -> list[Event]:
    """Load events from Tier 0 JSON storage.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        List of Event objects.
    """
    store = EventStore(project_hash, config)
    return store.load_all()


def load_tier0_hook_state(project_hash: str, config: CortexConfig) -> dict | None:
    """Load HookState dict from Tier 0 JSON storage.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        Dict with hook state if state.json exists, None otherwise.
    """
    # Use the HookState class to load, as it handles defaults
    state = HookState(project_hash, config)
    if not state.state_path.exists():
        return None

    return state.load()


def migrate_events_to_sqlite(
    events: list[Event],
    project_hash: str,
    config: CortexConfig,
) -> int:
    """Migrate events to SQLite storage in batches.

    Args:
        events: List of events to migrate.
        project_hash: Project identifier hash.
        config: Cortex configuration with storage_tier=1.

    Returns:
        Number of events migrated.
    """
    if not events:
        return 0

    # Create SQLite store (initializes schema)
    store = SQLiteEventStore(project_hash, config)

    # Insert events in batches
    migrated = 0
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i : i + BATCH_SIZE]
        store.append_many(batch)
        migrated += len(batch)

    store.close()
    return migrated


def migrate_hook_state_to_sqlite(
    hook_state_dict: dict,
    project_hash: str,
    config: CortexConfig,
) -> bool:
    """Migrate HookState dict to SQLite storage.

    The hook_state table uses key-value pairs (key TEXT, value TEXT),
    so we store each dict key as a separate row.

    Args:
        hook_state_dict: Dict with hook state keys from Tier 0.
        project_hash: Project identifier hash.
        config: Cortex configuration with storage_tier=1.

    Returns:
        True if migrated successfully.
    """
    conn = connect(project_hash, config)
    initialize_schema(conn)

    # Store each state key as a row in the key-value table
    for key, value in hook_state_dict.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO hook_state (key, value)
            VALUES (?, ?)
            """,
            (key, json.dumps(value)),
        )
    conn.commit()
    conn.close()
    return True


def archive_tier0_files(project_hash: str, config: CortexConfig) -> None:
    """Archive Tier 0 JSON files after successful migration.

    Moves events.json and state.json to archive/ subdirectory.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.
    """
    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash
    archive_dir = project_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Archive events.json
    events_json = project_dir / "events.json"
    if events_json.exists():
        shutil.move(str(events_json), str(archive_dir / "events.json"))

    # Archive state.json
    state_json = project_dir / "state.json"
    if state_json.exists():
        shutil.move(str(state_json), str(archive_dir / "state.json"))


def upgrade(
    project_hash: str,
    config: CortexConfig | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> MigrationResult:
    """Upgrade a project from Tier 0 (JSON) to Tier 1 (SQLite).

    Migration steps:
    1. Detect current tier and validate upgrade is possible
    2. Create backup of existing files
    3. Load events from JSON
    4. Create SQLite database and migrate events in batches
    5. Migrate HookState if present
    6. Update config to storage_tier=1
    7. Archive original JSON files

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration (loaded from project if None).
        dry_run: If True, report what would be done without making changes.
        force: If True, overwrite existing SQLite database.

    Returns:
        MigrationResult with details of the operation.
    """
    if config is None:
        config = load_config()

    # Check current state
    status = get_migration_status(project_hash, config)

    if status["current_tier"] == -1:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            backup_path=None,
            error="No storage found — project not initialized",
            dry_run=dry_run,
        )

    if status["current_tier"] == 1 and not force:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            backup_path=None,
            error="Already on Tier 1 (SQLite)",
            dry_run=dry_run,
        )

    if not status["can_upgrade"] and not force:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            backup_path=None,
            error=status["details"],
            dry_run=dry_run,
        )

    # Dry run — report what would happen
    if dry_run:
        return MigrationResult(
            success=True,
            events_migrated=status["events_count"],
            hook_state_migrated=status["has_hook_state"],
            backup_path=None,
            error=None,
            dry_run=True,
        )

    try:
        # Step 1: Create backup
        backup_path = create_backup(project_hash, config)

        # Step 2: Load existing events
        events = load_tier0_events(project_hash, config)

        # Step 3: Load HookState if present
        hook_state = load_tier0_hook_state(project_hash, config)

        # Step 4: If force, remove existing SQLite
        if force:
            db_path = get_db_path(project_hash, config)
            if db_path.exists():
                db_path.unlink()

        # Step 5: Create new config with Tier 1
        new_config = CortexConfig(
            cortex_home=config.cortex_home,
            storage_tier=1,
            snapshot_ttl_hours=config.snapshot_ttl_hours,
        )

        # Step 6: Migrate events to SQLite
        events_migrated = migrate_events_to_sqlite(events, project_hash, new_config)

        # Step 7: Migrate HookState if present
        hook_state_migrated = False
        if hook_state is not None:
            hook_state_migrated = migrate_hook_state_to_sqlite(hook_state, project_hash, new_config)

        # Step 8: Archive JSON files (tier detection is based on file presence)
        archive_tier0_files(project_hash, config)

        return MigrationResult(
            success=True,
            events_migrated=events_migrated,
            hook_state_migrated=hook_state_migrated,
            backup_path=backup_path,
            error=None,
            dry_run=False,
        )

    except Exception as e:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            backup_path=None,
            error=str(e),
            dry_run=dry_run,
        )


def rollback(project_hash: str, backup_path: Path, config: CortexConfig | None = None) -> bool:
    """Rollback a failed migration using a backup.

    Restores JSON files from backup and removes SQLite database.

    Args:
        project_hash: Project identifier hash.
        backup_path: Path to the backup directory.
        config: Cortex configuration.

    Returns:
        True if rollback successful.
    """
    if config is None:
        config = load_config()

    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash

    if not backup_path.exists():
        return False

    try:
        # Remove SQLite database if created
        db_path = get_db_path(project_hash, config)
        if db_path.exists():
            db_path.unlink()

        # Restore events.json
        backup_events = backup_path / "events.json"
        if backup_events.exists():
            shutil.copy2(backup_events, project_dir / "events.json")

        # Restore state.json
        backup_state = backup_path / "state.json"
        if backup_state.exists():
            shutil.copy2(backup_state, project_dir / "state.json")

        # Restore config.json
        backup_config = backup_path / "config.json"
        if backup_config.exists():
            shutil.copy2(backup_config, project_dir / "config.json")

        return True

    except Exception:
        return False

"""Migration utilities for upgrading Cortex storage tiers.

Provides the upgrade command to migrate between tiers:
- Tier 0 (JSON) → Tier 1 (SQLite + FTS5)
- Tier 1 (SQLite) → Tier 2 (SQLite + Embeddings)

Includes backup, batch processing, and rollback capabilities.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
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
        events_migrated: Number of events migrated (Tier 0→1).
        hook_state_migrated: Whether HookState was migrated (Tier 0→1).
        embeddings_generated: Number of embeddings backfilled (Tier 1→2).
        backup_path: Path to the backup directory.
        error: Error message if migration failed.
        dry_run: Whether this was a dry run (no changes made).
        from_tier: Source tier of migration.
        to_tier: Target tier of migration.
    """

    success: bool
    events_migrated: int
    hook_state_migrated: bool
    embeddings_generated: int
    backup_path: Path | None
    error: str | None
    dry_run: bool
    from_tier: int = 0
    to_tier: int = 1


def detect_tier(project_hash: str, config: CortexConfig) -> int:
    """Detect the current storage tier for a project.

    Detection logic:
    - -1: No storage found
    - 0: JSON storage exists (events.json)
    - 1: SQLite storage exists (events.db), no embeddings
    - 2: SQLite storage exists with embeddings populated

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.

    Returns:
        Detected tier (-1 to 2).
    """
    cortex_home = Path(config.cortex_home).expanduser()
    project_dir = cortex_home / "projects" / project_hash

    events_json = project_dir / "events.json"
    events_db = project_dir / "events.db"

    if events_db.exists():
        # Check if embeddings are populated → Tier 2
        try:
            store = SQLiteEventStore(project_hash, config)
            embedding_count = store.count_embeddings()
            total_count = store.count()
            store.close()

            # WHAT: Consider Tier 2 if config says so OR embeddings exist.
            # WHY: Config-based detection allows manual tier setting.
            if config.storage_tier >= 2 or (embedding_count > 0 and embedding_count >= total_count * 0.5):
                return 2
        except Exception:
            pass  # Fall through to Tier 1
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
        Dict with current_tier, can_upgrade, events_count, embedding info, and details.
    """
    from cortex.embeddings import check_sentence_transformers_available

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
        "target_tier": current_tier,  # Default: no upgrade available
        "events_count": 0,
        "has_hook_state": False,
        "embedding_count": 0,
        "sentence_transformers_available": check_sentence_transformers_available(),
        "details": "",
    }

    if current_tier == -1:
        result["details"] = "No storage found — project not initialized"
        return result

    if current_tier == 2:
        result["details"] = "Already on Tier 2 (SQLite + Embeddings)"
        try:
            store = SQLiteEventStore(project_hash, config)
            result["events_count"] = store.count()
            result["embedding_count"] = store.count_embeddings()
            store.close()
        except Exception:
            pass
        return result

    if current_tier == 1:
        # Tier 1 — check for Tier 2 upgrade
        events_count = 0
        embedding_count = 0
        try:
            store = SQLiteEventStore(project_hash, config)
            events_count = store.count()
            embedding_count = store.count_embeddings()
            result["events_count"] = events_count
            result["embedding_count"] = embedding_count
            store.close()
        except Exception:
            pass

        # Can upgrade to Tier 2 if sentence-transformers is available
        if result["sentence_transformers_available"]:
            events_without_embeddings = events_count - embedding_count
            if events_without_embeddings > 0:
                result["can_upgrade"] = True
                result["target_tier"] = 2
                result["details"] = f"Ready to upgrade to Tier 2: {events_without_embeddings} events need embeddings"
            else:
                result["details"] = "All events have embeddings — use 'cortex init' to enable Tier 2 hooks"
        else:
            result["details"] = "Tier 2 upgrade requires sentence-transformers: pip install sentence-transformers"
        return result

    # Tier 0 — can upgrade to Tier 1
    result["can_upgrade"] = True
    result["target_tier"] = 1

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
        result["details"] = f"Ready to upgrade to Tier 1: {result['events_count']} events"

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


def upgrade_to_tier2(
    project_hash: str,
    config: CortexConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MigrationResult:
    """Upgrade a project from Tier 1 (SQLite) to Tier 2 (SQLite + Embeddings).

    Backfills embeddings for all events using SentenceTransformers.

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration.
        progress_callback: Optional callback(done, total) for progress.

    Returns:
        MigrationResult with details of the operation.
    """
    from cortex.db import connect, initialize_schema
    from cortex.embeddings import check_sentence_transformers_available
    from cortex.vec import backfill_embeddings

    # Check prerequisites
    if not check_sentence_transformers_available():
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error="sentence-transformers not installed. Install with: pip install sentence-transformers",
            dry_run=False,
            from_tier=1,
            to_tier=2,
        )

    try:
        # Get event count
        store = SQLiteEventStore(project_hash, config)
        total_events = store.count()
        store.close()

        if total_events == 0:
            return MigrationResult(
                success=True,
                events_migrated=0,
                hook_state_migrated=False,
                embeddings_generated=0,
                backup_path=None,
                error=None,
                dry_run=False,
                from_tier=1,
                to_tier=2,
            )

        # Backfill embeddings
        conn = connect(project_hash, config)
        initialize_schema(conn)

        embeddings_generated = backfill_embeddings(
            conn,
            batch_size=32,
            progress_callback=progress_callback,
        )

        conn.close()

        return MigrationResult(
            success=True,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=embeddings_generated,
            backup_path=None,
            error=None,
            dry_run=False,
            from_tier=1,
            to_tier=2,
        )

    except Exception as e:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error=str(e),
            dry_run=False,
            from_tier=1,
            to_tier=2,
        )


def upgrade(
    project_hash: str,
    config: CortexConfig | None = None,
    dry_run: bool = False,
    force: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MigrationResult:
    """Upgrade a project to the next storage tier.

    Supports:
    - Tier 0 (JSON) → Tier 1 (SQLite + FTS5)
    - Tier 1 (SQLite) → Tier 2 (SQLite + Embeddings)

    Migration steps (Tier 0→1):
    1. Detect current tier and validate upgrade is possible
    2. Create backup of existing files
    3. Load events from JSON
    4. Create SQLite database and migrate events in batches
    5. Migrate HookState if present
    6. Archive original JSON files

    Migration steps (Tier 1→2):
    1. Check sentence-transformers is available
    2. Backfill embeddings for all events

    Args:
        project_hash: Project identifier hash.
        config: Cortex configuration (loaded from project if None).
        dry_run: If True, report what would be done without making changes.
        force: If True, force upgrade even if already at target tier.
        progress_callback: Optional callback(done, total) for Tier 2 embedding progress.

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
            embeddings_generated=0,
            backup_path=None,
            error="No storage found — project not initialized",
            dry_run=dry_run,
            from_tier=-1,
            to_tier=0,
        )

    # Handle Tier 2 (already at max)
    if status["current_tier"] == 2 and not force:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error="Already on Tier 2 (SQLite + Embeddings)",
            dry_run=dry_run,
            from_tier=2,
            to_tier=2,
        )

    # Handle Tier 1 → Tier 2 upgrade
    if status["current_tier"] == 1:
        if not status["can_upgrade"] and not force:
            return MigrationResult(
                success=False,
                events_migrated=0,
                hook_state_migrated=False,
                embeddings_generated=0,
                backup_path=None,
                error=status["details"],
                dry_run=dry_run,
                from_tier=1,
                to_tier=2,
            )

        # Dry run for Tier 1→2
        if dry_run:
            events_needing_embeddings = status["events_count"] - status["embedding_count"]
            return MigrationResult(
                success=True,
                events_migrated=0,
                hook_state_migrated=False,
                embeddings_generated=events_needing_embeddings,
                backup_path=None,
                error=None,
                dry_run=True,
                from_tier=1,
                to_tier=2,
            )

        # Perform Tier 1→2 upgrade
        return upgrade_to_tier2(project_hash, config, progress_callback)

    # Handle Tier 0 → Tier 1 upgrade
    if not status["can_upgrade"] and not force:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error=status["details"],
            dry_run=dry_run,
            from_tier=0,
            to_tier=1,
        )

    # Dry run for Tier 0→1
    if dry_run:
        return MigrationResult(
            success=True,
            events_migrated=status["events_count"],
            hook_state_migrated=status["has_hook_state"],
            embeddings_generated=0,
            backup_path=None,
            error=None,
            dry_run=True,
            from_tier=0,
            to_tier=1,
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
            embeddings_generated=0,
            backup_path=backup_path,
            error=None,
            dry_run=False,
            from_tier=0,
            to_tier=1,
        )

    except Exception as e:
        return MigrationResult(
            success=False,
            events_migrated=0,
            hook_state_migrated=False,
            embeddings_generated=0,
            backup_path=None,
            error=str(e),
            dry_run=dry_run,
            from_tier=0,
            to_tier=1,
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

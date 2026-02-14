"""CLI commands for Cortex: reset, status, init, upgrade.

Used by __main__.py. Reset clears event store and hook state for a project.
Status prints project identity and store counts. Init prints hook JSON for
Claude Code settings. Upgrade migrates from Tier 0 (JSON) to Tier 1 (SQLite).
"""

import json
import os
import sys

from cortex.config import load_config
from cortex.db import check_fts5_available, get_db_path
from cortex.migration import get_migration_status, upgrade
from cortex.project import identify_project
from cortex.store import EventStore, HookState, create_event_store

# Default state keys for clearing HookState (must match HookState.load() defaults).
_RESET_STATE = {
    "last_transcript_position": 0,
    "last_transcript_path": "",
    "last_session_id": "",
    "session_count": 0,
    "last_extraction_time": "",
}


def cmd_reset(cwd: str | None = None) -> int:
    """Clear event store and hook state for the project in cwd.

    Uses os.getcwd() if cwd is None. Prints one-line confirmation to stdout.
    Returns 0 on success, 1 on error (e.g. invalid path).
    """
    try:
        work_dir = (os.getcwd() if cwd is None else cwd).strip()
        if not work_dir:
            print("Cortex reset: no cwd.", file=sys.stderr)
            return 1
        identity = identify_project(work_dir)
        project_hash = identity["hash"]
        config = load_config()
        store = EventStore(project_hash, config)
        state = HookState(project_hash, config)
        store.clear()
        state.save(_RESET_STATE)
        print(f"Cortex memory reset for project {project_hash}.")
        return 0
    except Exception as e:
        print(f"Cortex reset error: {e}", file=sys.stderr)
        return 1


def cmd_status(cwd: str | None = None) -> int:
    """Print project identity, event count, storage tier, and last extraction time.

    Uses os.getcwd() if cwd is None. Returns 0 on success, 1 on error.
    """
    try:
        work_dir = (os.getcwd() if cwd is None else cwd).strip()
        if not work_dir:
            print("Cortex status: no cwd.", file=sys.stderr)
            return 1
        identity = identify_project(work_dir)
        project_hash = identity["hash"]
        config = load_config()

        # Use tier-aware store factory
        store = create_event_store(project_hash, config)
        state = HookState(project_hash, config)
        state_data = state.load()
        count = store.count()
        last_extraction = state_data.get("last_extraction_time") or "none"

        # Get migration status for tier info
        migration_status = get_migration_status(project_hash, config)

        print(f"project: {identity['path']}")
        print(f"hash: {project_hash}")
        print(
            f"storage_tier: {migration_status['current_tier']} ({'SQLite' if migration_status['current_tier'] == 1 else 'JSON'})"
        )
        print(f"events: {count}")
        print(f"last_extraction: {last_extraction}")

        # Show database size and FTS status for Tier 1
        if migration_status["current_tier"] == 1:
            db_path = get_db_path(project_hash, config)
            if db_path.exists():
                size_bytes = db_path.stat().st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                print(f"db_size: {size_str}")
            print(f"fts5_available: {'yes' if check_fts5_available() else 'no'}")

        # Show upgrade hint if on Tier 0
        if migration_status["can_upgrade"]:
            print("upgrade: run 'cortex upgrade' to migrate to SQLite")

        return 0
    except Exception as e:
        print(f"Cortex status error: {e}", file=sys.stderr)
        return 1


def cmd_upgrade(cwd: str | None = None, dry_run: bool = False, force: bool = False) -> int:
    """Upgrade project from Tier 0 (JSON) to Tier 1 (SQLite).

    Args:
        cwd: Working directory (uses os.getcwd() if None).
        dry_run: If True, report what would be done without making changes.
        force: If True, overwrite existing SQLite database.

    Returns:
        0 on success, 1 on error.
    """
    try:
        work_dir = (os.getcwd() if cwd is None else cwd).strip()
        if not work_dir:
            print("Cortex upgrade: no cwd.", file=sys.stderr)
            return 1

        identity = identify_project(work_dir)
        project_hash = identity["hash"]
        config = load_config()

        # Show pre-upgrade status
        status = get_migration_status(project_hash, config)
        print(f"project: {identity['path']}")
        print(f"current_tier: {status['current_tier']} ({'SQLite' if status['current_tier'] == 1 else 'JSON'})")
        print(f"events: {status['events_count']}")
        print(f"hook_state: {'yes' if status['has_hook_state'] else 'no'}")

        if not status["can_upgrade"] and not force:
            print(f"\n{status['details']}")
            return 1

        # Run migration
        if dry_run:
            print("\n[DRY RUN] Would perform the following:")
            print("  - Backup existing files")
            print(f"  - Migrate {status['events_count']} events to SQLite")
            if status["has_hook_state"]:
                print("  - Migrate hook state")
            print("  - Update config to storage_tier=1")
            print("  - Archive JSON files")
            return 0

        print("\nMigrating to Tier 1 (SQLite)...")
        result = upgrade(project_hash, config, dry_run=False, force=force)

        if result.success:
            print("\nMigration complete!")
            print(f"  events_migrated: {result.events_migrated}")
            print(f"  hook_state_migrated: {'yes' if result.hook_state_migrated else 'no'}")
            if result.backup_path:
                print(f"  backup: {result.backup_path}")
            return 0
        else:
            print(f"\nMigration failed: {result.error}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Cortex upgrade error: {e}", file=sys.stderr)
        return 1


def get_init_hook_json() -> str:
    """Return the hook configuration JSON for Claude Code settings.

    Format matches Claude Code expectations: hooks key with Stop, PreCompact,
    SessionStart entries. Commands use 'cortex' so they work when the package
    is installed (cortex on PATH).
    """
    config = {
        "hooks": {
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "cortex stop"}]}],
            "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "cortex precompact"}]}],
            "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "cortex session-start"}]}],
        }
    }
    return json.dumps(config, indent=2)


def cmd_init() -> int:
    """Print hook configuration JSON to stdout for copy-paste into Claude Code settings."""
    print(get_init_hook_json())
    return 0

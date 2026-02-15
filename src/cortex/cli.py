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
        tier_names = {0: "JSON", 1: "SQLite", 2: "SQLite + Embeddings", 3: "MCP + Projections"}
        tier_name = tier_names.get(migration_status["current_tier"], "Unknown")
        print(f"storage_tier: {migration_status['current_tier']} ({tier_name})")
        print(f"events: {count}")
        print(f"last_extraction: {last_extraction}")

        # Show database size and FTS status for Tier 1+
        if migration_status["current_tier"] >= 1:
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

        # Show Tier 2 status (embedding count, auto_embed)
        if migration_status["current_tier"] >= 2:
            from cortex.sqlite_store import SQLiteEventStore

            if isinstance(store, SQLiteEventStore):
                embedding_count = store.count_embeddings()
                print(f"embeddings: {embedding_count}/{count}")
                print(f"auto_embed: {'yes' if config.auto_embed else 'no'}")

        # Show Tier 3 status (MCP, projections)
        if migration_status["current_tier"] >= 3 or config.mcp_enabled or config.projections_enabled:
            from cortex.mcp.server import check_mcp_available

            print(f"mcp_enabled: {'yes' if config.mcp_enabled else 'no'}")
            print(f"mcp_available: {'yes' if check_mcp_available() else 'no'}")
            print(f"projections_enabled: {'yes' if config.projections_enabled else 'no'}")

        # Show upgrade hint if on Tier 0
        if migration_status["can_upgrade"]:
            print("upgrade: run 'cortex upgrade' to migrate to SQLite")

        return 0
    except Exception as e:
        print(f"Cortex status error: {e}", file=sys.stderr)
        return 1


def cmd_upgrade(cwd: str | None = None, dry_run: bool = False, force: bool = False) -> int:
    """Upgrade project to the next storage tier.

    Supports:
    - Tier 0 (JSON) → Tier 1 (SQLite + FTS5)
    - Tier 1 (SQLite) → Tier 2 (SQLite + Embeddings)

    Args:
        cwd: Working directory (uses os.getcwd() if None).
        dry_run: If True, report what would be done without making changes.
        force: If True, force upgrade even if at target tier.

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
        tier_names = {-1: "None", 0: "JSON", 1: "SQLite", 2: "SQLite + Embeddings", 3: "MCP + Projections"}
        print(f"project: {identity['path']}")
        print(f"current_tier: {status['current_tier']} ({tier_names.get(status['current_tier'], 'Unknown')})")
        print(f"events: {status['events_count']}")

        # Show tier-specific info
        if status["current_tier"] == 0:
            print(f"hook_state: {'yes' if status['has_hook_state'] else 'no'}")
        if status["current_tier"] >= 1:
            print(f"embeddings: {status.get('embedding_count', 0)}/{status['events_count']}")
            print(
                f"sentence_transformers: {'available' if status.get('sentence_transformers_available') else 'not installed'}"
            )

        if not status["can_upgrade"] and not force:
            print(f"\n{status['details']}")
            return 1

        target_tier = status.get("target_tier", status["current_tier"] + 1)

        # Run migration
        if dry_run:
            print(f"\n[DRY RUN] Would upgrade to Tier {target_tier} ({tier_names.get(target_tier, 'Unknown')}):")
            if status["current_tier"] == 0:
                print("  - Backup existing files")
                print(f"  - Migrate {status['events_count']} events to SQLite")
                if status["has_hook_state"]:
                    print("  - Migrate hook state")
                print("  - Archive JSON files")
            elif status["current_tier"] == 1:
                events_needing_embeddings = status["events_count"] - status.get("embedding_count", 0)
                print(f"  - Generate embeddings for {events_needing_embeddings} events")
                print("  - (After upgrade, run 'cortex init' to enable anticipatory retrieval)")
            elif status["current_tier"] == 2:
                print("  - Enable MCP server for mid-session memory queries")
                print("  - Enable git-tracked projections (.cortex/decisions.md, etc.)")
                print("  - (After upgrade, run 'cortex init' to configure MCP server)")
            return 0

        # Progress callback for Tier 2 embedding generation
        def progress_callback(done: int, total: int) -> None:
            print(f"  Generating embeddings: {done}/{total}", end="\r")

        print(f"\nUpgrading to Tier {target_tier} ({tier_names.get(target_tier, 'Unknown')})...")
        result = upgrade(project_hash, config, dry_run=False, force=force, progress_callback=progress_callback)

        if result.success:
            print("\nUpgrade complete!")
            if result.from_tier == 0:
                print(f"  events_migrated: {result.events_migrated}")
                print(f"  hook_state_migrated: {'yes' if result.hook_state_migrated else 'no'}")
                if result.backup_path:
                    print(f"  backup: {result.backup_path}")
            elif result.from_tier == 1:
                print(f"  embeddings_generated: {result.embeddings_generated}")
            elif result.from_tier == 2:
                print("  mcp_enabled: yes")
                print("  projections_enabled: yes")
            print(f"\nRun 'cortex init' to update your Claude Code hooks for Tier {result.to_tier}.")
            return 0
        else:
            print(f"\nUpgrade failed: {result.error}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Cortex upgrade error: {e}", file=sys.stderr)
        return 1


def get_init_hook_json(include_tier2: bool = False, include_tier3: bool = False) -> str:
    """Return the hook configuration JSON for Claude Code settings.

    Format matches Claude Code expectations: hooks key with Stop, PreCompact,
    SessionStart entries. Commands use 'cortex' so they work when the package
    is installed (cortex on PATH).

    Args:
        include_tier2: If True, include UserPromptSubmit hook for anticipatory
                       retrieval (requires Tier 2+).
        include_tier3: If True, include Stop hook for projection regeneration
                       (requires Tier 3).
    """
    # Base command for Stop hook
    stop_command = "cortex stop"

    # Tier 3: regenerate projections on Stop
    if include_tier3:
        stop_command = "cortex stop --regenerate-projections"

    hooks: dict = {
        "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": stop_command}]}],
        "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "cortex precompact"}]}],
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "cortex session-start"}]}],
    }

    if include_tier2:
        hooks["UserPromptSubmit"] = [
            {"matcher": "", "hooks": [{"type": "command", "command": "cortex user-prompt-submit"}]}
        ]

    return json.dumps({"hooks": hooks}, indent=2)


def cmd_init() -> int:
    """Print hook configuration JSON to stdout for copy-paste into Claude Code settings.

    If current project is Tier 2+, includes UserPromptSubmit hook for anticipatory retrieval.
    If Tier 3, includes projection regeneration and MCP server instructions.
    """
    config = load_config()
    include_tier2 = config.storage_tier >= 2 or config.auto_embed
    include_tier3 = config.storage_tier >= 3 or config.projections_enabled
    print(get_init_hook_json(include_tier2=include_tier2, include_tier3=include_tier3))

    if include_tier3:
        print("\n# Tier 3 detected: Projections regenerated on Stop", file=sys.stderr)
        print("# To enable MCP server, add to Claude Code settings:", file=sys.stderr)
        print("#   mcpServers: { cortex: { command: 'cortex', args: ['mcp-server'] } }", file=sys.stderr)
    elif include_tier2:
        print("\n# Tier 2+ detected: UserPromptSubmit hook included for anticipatory retrieval", file=sys.stderr)
    else:
        print("\n# Tip: Upgrade to Tier 2 and re-run 'cortex init' for anticipatory retrieval", file=sys.stderr)

    return 0

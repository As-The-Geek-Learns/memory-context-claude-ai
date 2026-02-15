"""CLI entry point for Cortex hook handlers and commands.

Usage:
    cortex stop                # JSON payload on stdin
    cortex precompact          # JSON payload on stdin
    cortex session-start       # JSON payload on stdin
    cortex user-prompt-submit  # JSON payload on stdin (Tier 2+ anticipatory)
    cortex reset               # clear store + state for current project
    cortex status              # show project hash, event count, storage tier
    cortex init                # print hook JSON for Claude Code settings
    cortex upgrade             # migrate from Tier 0 (JSON) to Tier 1 (SQLite)
    cortex upgrade --dry-run   # show what would be done without making changes
    cortex upgrade --force     # overwrite existing SQLite database
    cortex mcp-server          # start MCP server (Tier 3, stdio transport)

    python -m cortex stop      # same
"""

import sys

from cortex.cli import cmd_init, cmd_reset, cmd_status, cmd_upgrade
from cortex.hooks import (
    handle_precompact,
    handle_session_start,
    handle_stop,
    handle_user_prompt_submit,
    read_payload,
)

USAGE = "Usage: cortex <stop|precompact|session-start|user-prompt-submit|reset|status|init|upgrade|mcp-server>\n"


def main() -> None:
    """Parse command from argv, dispatch to handler or hook, exit with return code."""
    if len(sys.argv) < 2:
        sys.stderr.write(USAGE)
        sys.exit(1)

    arg = sys.argv[1].strip().lower()
    if arg in ("-h", "--help"):
        sys.stderr.write(USAGE)
        sys.exit(0)

    if arg == "reset":
        sys.exit(cmd_reset())
    if arg == "status":
        sys.exit(cmd_status())
    if arg == "init":
        sys.exit(cmd_init())
    if arg == "upgrade":
        # Parse --dry-run and --force flags
        dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
        force = "--force" in sys.argv or "-f" in sys.argv
        sys.exit(cmd_upgrade(dry_run=dry_run, force=force))
    if arg == "mcp-server":
        from cortex.mcp import run_server

        sys.exit(run_server())

    # Hook commands: require payload on stdin
    hook_name = arg
    if hook_name == "sessionstart":
        hook_name = "session-start"
    if hook_name == "userpromptsubmit":
        hook_name = "user-prompt-submit"

    if hook_name == "stop":
        regenerate_projections = "--regenerate-projections" in sys.argv
        code = handle_stop(read_payload(), regenerate_projections=regenerate_projections)
    elif hook_name == "precompact":
        code = handle_precompact(read_payload())
    elif hook_name == "session-start":
        code = handle_session_start(read_payload())
    elif hook_name == "user-prompt-submit":
        code = handle_user_prompt_submit(read_payload())
    else:
        sys.stderr.write(f"Unknown command: {arg}. {USAGE}")
        sys.exit(1)

    sys.exit(code)

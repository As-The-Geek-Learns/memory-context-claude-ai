"""Claude Code hook handlers for Cortex.

Stop, PreCompact, and SessionStart handlers read JSON payloads from stdin,
perform incremental transcript extraction and briefing generation, and always
exit 0 so Claude Code never blocks on hook failure.

Uses create_event_store() factory for tier-aware storage (JSON or SQLite).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cortex.briefing import write_briefing_to_file
from cortex.config import load_config
from cortex.extractors import extract_events
from cortex.project import identify_project
from cortex.store import HookState, create_event_store
from cortex.transcript import (
    TranscriptReader,
    find_latest_transcript,
    find_transcript_path,
)


def read_payload() -> dict:
    """Read JSON payload from stdin.

    On empty or invalid input returns {} and does not raise.
    Hooks must not crash the IDE.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def handle_stop(payload: dict) -> int:
    """Handle Stop hook: incremental transcript extraction and event storage.

    If stop_hook_active is true, returns 0 immediately to avoid recursion.
    Resolves project from cwd, loads HookState, reads new transcript lines
    since last_transcript_position, extracts events, appends to store,
    updates state. On any exception logs to stderr and returns 0.
    """
    try:
        if payload.get("stop_hook_active"):
            return 0

        cwd = payload.get("cwd")
        if not cwd:
            return 0

        identity = identify_project(cwd)
        project_hash = identity["hash"]
        git_branch = identity["git_branch"]
        session_id = payload.get("session_id", "")
        transcript_path_str = payload.get("transcript_path")

        if not transcript_path_str:
            return 0

        config = load_config()
        store = create_event_store(project_hash, config)
        state = HookState(project_hash, config)
        state_data = state.load()

        last_path = state_data.get("last_transcript_path", "")
        from_offset = state_data.get("last_transcript_position", 0)
        if transcript_path_str != last_path:
            from_offset = 0

        transcript_path = Path(transcript_path_str)
        if not transcript_path.exists():
            return 0

        reader = TranscriptReader(transcript_path)
        entries = reader.read_new(from_offset=from_offset)
        if not entries:
            state.update(
                last_transcript_position=reader.last_offset,
                last_transcript_path=transcript_path_str,
                last_session_id=session_id,
                last_extraction_time=datetime.now(timezone.utc).isoformat(),
            )
            return 0

        events = extract_events(
            entries,
            session_id=session_id,
            project=identity.get("path", cwd),
            git_branch=git_branch,
        )
        if events:
            store.append_many(events)

        state.update(
            last_transcript_position=reader.last_offset,
            last_transcript_path=transcript_path_str,
            last_session_id=session_id,
            session_count=state_data.get("session_count", 0) + 1,
            last_extraction_time=datetime.now(timezone.utc).isoformat(),
        )
        return 0
    except Exception as e:
        print(f"[Cortex] Stop hook error: {e}", file=sys.stderr)
        return 0


def handle_precompact(payload: dict) -> int:
    """Handle PreCompact hook: optional extraction then regenerate briefing.

    PreCompact does not provide transcript_path; discovers transcript via
    find_transcript_path(cwd) and find_latest_transcript. Performs same
    incremental extraction as Stop if transcript found, then writes
    .claude/rules/cortex-briefing.md. On exception logs to stderr and returns 0.
    """
    try:
        cwd = payload.get("cwd")
        if not cwd:
            return 0

        identity = identify_project(cwd)
        project_hash = identity["hash"]
        git_branch = identity["git_branch"]
        config = load_config()

        transcript_dir = find_transcript_path(cwd)
        transcript_path = find_latest_transcript(transcript_dir) if transcript_dir else None
        if transcript_path:
            store = create_event_store(project_hash, config)
            state = HookState(project_hash, config)
            state_data = state.load()
            last_path = state_data.get("last_transcript_path", "")
            from_offset = state_data.get("last_transcript_position", 0)
            if str(transcript_path) != last_path:
                from_offset = 0
            reader = TranscriptReader(transcript_path)
            entries = reader.read_new(from_offset=from_offset)
            if entries:
                session_id = state_data.get("last_session_id", "")
                events = extract_events(
                    entries,
                    session_id=session_id,
                    project=identity.get("path", cwd),
                    git_branch=git_branch,
                )
                if events:
                    store.append_many(events)
                state.update(
                    last_transcript_position=reader.last_offset,
                    last_transcript_path=str(transcript_path),
                    last_extraction_time=datetime.now(timezone.utc).isoformat(),
                )

        briefing_path = Path(cwd) / ".claude" / "rules" / "cortex-briefing.md"
        write_briefing_to_file(
            briefing_path,
            project_path=cwd,
            config=config,
            branch=git_branch or None,
        )
        return 0
    except Exception as e:
        print(f"[Cortex] PreCompact hook error: {e}", file=sys.stderr)
        return 0


def handle_session_start(payload: dict) -> int:
    """Handle SessionStart hook: generate and write briefing for new session.

    Writes .claude/rules/cortex-briefing.md so the session gets current
    context. On exception logs to stderr and returns 0.
    """
    try:
        cwd = payload.get("cwd")
        if not cwd:
            return 0

        identity = identify_project(cwd)
        git_branch = identity.get("git_branch") or None
        config = load_config()
        briefing_path = Path(cwd) / ".claude" / "rules" / "cortex-briefing.md"
        write_briefing_to_file(
            briefing_path,
            project_path=cwd,
            config=config,
            branch=git_branch,
        )
        return 0
    except Exception as e:
        print(f"[Cortex] SessionStart hook error: {e}", file=sys.stderr)
        return 0

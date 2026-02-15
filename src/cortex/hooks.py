"""Claude Code hook handlers for Cortex.

Stop, PreCompact, SessionStart, and UserPromptSubmit handlers read JSON
payloads from stdin, perform incremental transcript extraction, briefing
generation, and anticipatory retrieval. Always exit 0 so Claude Code
never blocks on hook failure.

Uses create_event_store() factory for tier-aware storage (JSON or SQLite).
Tier 2+ enables anticipatory retrieval via UserPromptSubmit hook.
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


def handle_stop(payload: dict, regenerate_projections: bool = False) -> int:
    """Handle Stop hook: incremental transcript extraction and event storage.

    If stop_hook_active is true, returns 0 immediately to avoid recursion.
    Resolves project from cwd, loads HookState, reads new transcript lines
    since last_transcript_position, extracts events, appends to store,
    updates state. On any exception logs to stderr and returns 0.

    Args:
        payload: JSON payload from Claude Code.
        regenerate_projections: If True, regenerate git-tracked projections (Tier 3).
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
            # Still regenerate projections even if no new entries
            if regenerate_projections:
                _regenerate_projections(store, cwd, git_branch)
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

        # Regenerate projections if enabled (Tier 3)
        if regenerate_projections:
            _regenerate_projections(store, cwd, git_branch)

        return 0
    except Exception as e:
        print(f"[Cortex] Stop hook error: {e}", file=sys.stderr)
        return 0


def _regenerate_projections(store, cwd: str, git_branch: str | None) -> None:
    """Regenerate git-tracked projections (.cortex/ directory).

    Called by handle_stop when --regenerate-projections is set.
    Writes decisions.md, decisions-archive.md, and active-plan.md.
    """
    try:
        from cortex.projections import regenerate_all

        stats = regenerate_all(store, cwd, branch=git_branch)
        if stats.files_written:
            print(f"[Cortex] Regenerated projections: {len(stats.files_written)} files", file=sys.stderr)
    except Exception as e:
        print(f"[Cortex] Projection regeneration error: {e}", file=sys.stderr)


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


def handle_user_prompt_submit(payload: dict) -> int:
    """Handle UserPromptSubmit hook: anticipatory retrieval for Tier 2+.

    Embeds the user's prompt and performs hybrid search to find relevant
    events. Writes results to .claude/rules/cortex-relevant-context.md
    so Claude has proactive context before processing the message.

    Requires Tier 2+ (storage_tier >= 2) and sentence-transformers.
    Silently skips if requirements not met (graceful degradation).

    On exception logs to stderr and returns 0.
    """
    try:
        cwd = payload.get("cwd")
        prompt = payload.get("prompt", "")

        if not cwd or not prompt:
            return 0

        # WHAT: Import here to avoid circular imports at module load.
        # WHY: anticipate module imports from store which imports config.
        from cortex.anticipate import write_relevant_context_to_file

        identity = identify_project(cwd)
        git_branch = identity.get("git_branch") or None
        config = load_config()

        # WHAT: Skip if not Tier 2+.
        # WHY: Anticipatory retrieval requires embeddings.
        if config.storage_tier < 2:
            return 0

        context_path = Path(cwd) / ".claude" / "rules" / "cortex-relevant-context.md"
        write_relevant_context_to_file(
            output_path=context_path,
            prompt=prompt,
            project_path=cwd,
            config=config,
            branch=git_branch,
        )
        return 0
    except Exception as e:
        print(f"[Cortex] UserPromptSubmit hook error: {e}", file=sys.stderr)
        return 0

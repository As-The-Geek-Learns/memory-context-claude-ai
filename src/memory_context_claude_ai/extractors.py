"""Three-layer event extraction pipeline for Cortex.

Converts parsed TranscriptEntries into Cortex Events using three layers:
- Layer 1 (Structural): Tool call observation — Write→FILE_MODIFIED, Bash→COMMAND_RUN, etc.
- Layer 2 (Semantic): Keyword scanning — "Decision:", "Rejected:", "Fixed:" → event classification
- Layer 3 (Explicit): [MEMORY:] tag extraction from user and assistant messages

Each layer is a standalone function returning list[Event]. The pipeline
orchestrator extract_events() runs all three and deduplicates results.
"""

import re

from memory_context_claude_ai.models import EventType, content_hash, create_event
from memory_context_claude_ai.transcript import (
    TranscriptEntry,
    extract_text_content,
    extract_tool_calls,
    extract_tool_results,
    strip_code_blocks,
)

# ============================================================
# Layer 2 Constants: Semantic keyword patterns
# ============================================================

# WHAT: Compiled regex patterns for keyword extraction.
# WHY: Each pattern maps a text keyword to an event type and confidence.
# Patterns match at line start (after optional whitespace and bold markers)
# to reduce false positives from mid-sentence usage.
SEMANTIC_PATTERNS: list[tuple[re.Pattern, EventType, float]] = [
    (re.compile(r"(?m)^\s*\*{0,2}Decision:\s*(.+)"), EventType.DECISION_MADE, 0.85),
    (re.compile(r"(?m)^\s*\*{0,2}Rejected:\s*(.+)"), EventType.APPROACH_REJECTED, 0.85),
    (re.compile(r"(?m)^\s*\*{0,2}Fixed:\s*(.+)"), EventType.ERROR_RESOLVED, 0.75),
    (re.compile(r"(?m)^\s*\*{0,2}Error resolved:\s*(.+)", re.IGNORECASE), EventType.ERROR_RESOLVED, 0.7),
    (re.compile(r"(?m)^\s*\*{0,2}(?:Learned|Lesson|TIL):\s*(.+)"), EventType.KNOWLEDGE_ACQUIRED, 0.7),
    (re.compile(r"(?m)^\s*\*{0,2}Preference:\s*(.+)"), EventType.PREFERENCE_NOTED, 0.8),
]

# ============================================================
# Layer 3 Constants: Explicit [MEMORY:] tag pattern
# ============================================================

# WHAT: Regex to extract [MEMORY: <content>] tags.
# WHY: Users and assistants can explicitly flag memories using this tag.
# Non-greedy match avoids consuming across multiple tags on the same line.
_MEMORY_TAG_RE = re.compile(r"\[MEMORY:\s*(.+?)\]", re.DOTALL)


# ============================================================
# Layer 1: Structural Extraction (tool call observation)
# ============================================================


def extract_structural(
    entry: TranscriptEntry,
    session_id: str = "",
    project: str = "",
    git_branch: str = "",
) -> list:
    """Extract events from tool calls in assistant entries.

    Maps tool invocations to event types:
    - Write/Edit → FILE_MODIFIED
    - Bash → COMMAND_RUN
    - Read/Glob/Grep → FILE_EXPLORED
    - TodoWrite → PLAN_CREATED

    Also extracts PLAN_STEP_COMPLETED from TodoWrite tool results
    in user entries (comparing oldTodos vs newTodos).

    Args:
        entry: A parsed TranscriptEntry.
        session_id: Fallback session ID if entry doesn't have one.
        project: Project identifier.
        git_branch: Fallback git branch if entry doesn't have one.

    Returns:
        List of Event objects extracted from tool observations.
    """
    sid = entry.session_id or session_id
    branch = entry.git_branch or git_branch
    events = []

    if entry.is_assistant:
        for call in extract_tool_calls(entry):
            event = _event_from_tool_call(call.name, call.input, sid, project, branch)
            if event is not None:
                events.append(event)

    if entry.is_user:
        events.extend(_extract_plan_step_completions(entry, sid, project, branch))

    return events


def _event_from_tool_call(
    tool_name: str,
    tool_input: dict,
    session_id: str,
    project: str,
    git_branch: str,
):
    """Create an Event from a single tool call, or return None if unrecognized."""
    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        return create_event(
            EventType.FILE_MODIFIED,
            content=f"Modified: {file_path}",
            session_id=session_id,
            project=project,
            git_branch=git_branch,
            metadata={"tool": tool_name, "file_path": file_path},
            provenance="structural",
        )

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        description = tool_input.get("description", "")
        return create_event(
            EventType.COMMAND_RUN,
            content=command,
            session_id=session_id,
            project=project,
            git_branch=git_branch,
            metadata={"tool": "Bash", "description": description},
            provenance="structural",
        )

    if tool_name in ("Read", "Glob", "Grep"):
        target = tool_input.get("file_path", tool_input.get("pattern", ""))
        return create_event(
            EventType.FILE_EXPLORED,
            content=f"Explored: {target}",
            session_id=session_id,
            project=project,
            git_branch=git_branch,
            metadata={"tool": tool_name},
            provenance="structural",
        )

    if tool_name == "TodoWrite":
        todos = tool_input.get("todos", [])
        content = _format_todos(todos)
        return create_event(
            EventType.PLAN_CREATED,
            content=content,
            session_id=session_id,
            project=project,
            git_branch=git_branch,
            metadata={"tool": "TodoWrite", "todo_count": len(todos)},
            provenance="structural",
        )

    return None


def _extract_plan_step_completions(
    entry: TranscriptEntry,
    session_id: str,
    project: str,
    git_branch: str,
) -> list:
    """Detect PLAN_STEP_COMPLETED from TodoWrite tool result metadata.

    Compares oldTodos vs newTodos in the toolUseResult envelope to find
    todos that transitioned to "completed" status.
    """
    events = []
    for result in extract_tool_results(entry):
        meta = result.metadata
        old_todos = meta.get("oldTodos", [])
        new_todos = meta.get("newTodos", [])

        if not old_todos or not new_todos:
            continue

        old_completed = {
            t.get("content", "") for t in old_todos if isinstance(t, dict) and t.get("status") == "completed"
        }
        new_completed = {
            t.get("content", "") for t in new_todos if isinstance(t, dict) and t.get("status") == "completed"
        }
        newly_completed = new_completed - old_completed

        for content in sorted(newly_completed):
            events.append(
                create_event(
                    EventType.PLAN_STEP_COMPLETED,
                    content=content,
                    session_id=session_id,
                    project=project,
                    git_branch=git_branch,
                    metadata={"tool": "TodoWrite"},
                    provenance="structural",
                )
            )

    return events


def _format_todos(todos: list) -> str:
    """Format a list of todo dicts into readable text for event content."""
    items = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        marker = "x" if status == "completed" else " "
        items.append(f"[{marker}] {content}")
    return "\n".join(items)


# ============================================================
# Layer 2: Semantic Extraction (keyword scanning)
# ============================================================


def extract_semantic(
    entry: TranscriptEntry,
    session_id: str = "",
    project: str = "",
    git_branch: str = "",
) -> list:
    """Extract events from keyword patterns in assistant text.

    Scans visible text content (after stripping code blocks) for
    structured keyword patterns like "Decision:", "Rejected:", etc.

    Only processes assistant entries — user messages are handled
    by Layer 3 (explicit [MEMORY:] tags) instead.

    Args:
        entry: A parsed TranscriptEntry.
        session_id: Fallback session ID.
        project: Project identifier.
        git_branch: Fallback git branch.

    Returns:
        List of Event objects from keyword matches.
    """
    if not entry.is_assistant:
        return []

    text = extract_text_content(entry)
    if not text:
        return []

    stripped = strip_code_blocks(text)
    if not stripped.strip():
        return []

    sid = entry.session_id or session_id
    branch = entry.git_branch or git_branch
    events = []

    for pattern, event_type, confidence in SEMANTIC_PATTERNS:
        for match in pattern.finditer(stripped):
            # WHAT: Strip trailing bold markers and whitespace from capture.
            # WHY: "**Decision: Use SQLite**" captures "Use SQLite**" —
            # we need to clean the trailing markdown.
            content = match.group(1).strip().rstrip("*").strip()
            if not content:
                continue

            events.append(
                create_event(
                    event_type,
                    content=content,
                    session_id=sid,
                    project=project,
                    git_branch=branch,
                    confidence=confidence,
                    metadata={"keyword": pattern.pattern},
                    provenance="semantic",
                )
            )

    return events


# ============================================================
# Layer 3: Explicit Extraction ([MEMORY:] tags)
# ============================================================


def extract_explicit(
    entry: TranscriptEntry,
    session_id: str = "",
    project: str = "",
    git_branch: str = "",
) -> list:
    """Extract [MEMORY:] tagged content from user and assistant messages.

    Scans both user and assistant messages because either party can
    explicitly flag information for memory retention.

    [MEMORY:] tags get the highest confidence (1.0) since they
    represent deliberate intent to preserve information.

    Args:
        entry: A parsed TranscriptEntry.
        session_id: Fallback session ID.
        project: Project identifier.
        git_branch: Fallback git branch.

    Returns:
        List of Event objects from [MEMORY:] tags.
    """
    if not entry.is_message:
        return []

    text = extract_text_content(entry)
    if not text:
        return []

    sid = entry.session_id or session_id
    branch = entry.git_branch or git_branch
    source = "user" if entry.is_user else "assistant"
    events = []

    for match in _MEMORY_TAG_RE.finditer(text):
        content = match.group(1).strip()
        if not content:
            continue

        events.append(
            create_event(
                EventType.KNOWLEDGE_ACQUIRED,
                content=content,
                session_id=sid,
                project=project,
                git_branch=branch,
                confidence=1.0,
                metadata={"source": source},
                provenance="explicit",
            )
        )

    return events


# ============================================================
# Pipeline Orchestration
# ============================================================


def extract_events(
    entries: list[TranscriptEntry],
    session_id: str = "",
    project: str = "",
    git_branch: str = "",
) -> list:
    """Run all three extraction layers and return deduplicated events.

    This is the main entry point for the extraction pipeline.
    Processes each TranscriptEntry through all three layers,
    then removes duplicates by content hash.

    Args:
        entries: Parsed TranscriptEntry objects (from TranscriptReader).
        session_id: Default session ID (overridden by entry-level values).
        project: Project identifier string.
        git_branch: Default git branch (overridden by entry-level values).

    Returns:
        Deduplicated list of Event objects.
    """
    events = []
    for entry in entries:
        events.extend(extract_structural(entry, session_id, project, git_branch))
        events.extend(extract_semantic(entry, session_id, project, git_branch))
        events.extend(extract_explicit(entry, session_id, project, git_branch))

    return _deduplicate(events)


def _deduplicate(events: list) -> list:
    """Remove duplicate events using content hash.

    Content hash is based on type + content + session_id, so the
    same fact in different sessions is preserved (stated again = signal).
    """
    seen: set[str] = set()
    unique = []
    for event in events:
        h = content_hash(event)
        if h not in seen:
            seen.add(h)
            unique.append(event)
    return unique

"""Transcript analyzer for Phase 3 baseline data collection.

# WHAT: Extracts objective metrics from real Claude Code JSONL transcripts.
# WHY: Two of the four Phase 3 metrics (cold start time, re-exploration count)
#       can be computed automatically from transcript data, eliminating manual
#       measurement for those metrics.

The analyzer parses a single transcript and computes:
- Cold start time: minutes from session start to first meaningful action
- Files explored: set of file paths read/searched during the session
- Files modified: set of file paths written/edited during the session
- Session duration: total time from first to last entry
- Tool call count: total number of tool invocations

Cross-session re-exploration detection is handled by the caller
(SessionRecorder), which maintains a cumulative set of explored files.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cortex.transcript import (
    TranscriptEntry,
    TranscriptReader,
    extract_tool_calls,
)


@dataclass
class TranscriptMetrics:
    """Objective metrics extracted from a single transcript.

    Attributes:
        cold_start_minutes: Minutes from session start to first meaningful
            action (Write, Edit, or Bash tool call). If no such action exists,
            equals session_duration_minutes (entire session was exploration).
        files_explored: Set of file paths targeted by Read/Glob/Grep tool calls.
            Used for cross-session re-exploration detection.
        files_modified: Set of file paths targeted by Write/Edit tool calls.
        session_duration_minutes: Total time from first to last entry.
        tool_call_count: Total number of tool calls in the session.
        transcript_path: Absolute path to the analyzed transcript file.
    """

    cold_start_minutes: float = 0.0
    files_explored: set[str] = field(default_factory=set)
    files_modified: set[str] = field(default_factory=set)
    session_duration_minutes: float = 0.0
    tool_call_count: int = 0
    transcript_path: str = ""


# WHAT: Tool names that count as "meaningful actions" for cold start timing.
# WHY: These tools produce observable side effects (file changes, commands run).
#       Read/Glob/Grep are exploration, not productive action.
_MEANINGFUL_ACTION_TOOLS = {"Write", "Edit", "Bash"}

# WHAT: Tool names that indicate file exploration.
# WHY: These tools read or search for file content. Their targets are tracked
#       across sessions to detect re-exploration.
_EXPLORATION_TOOLS = {"Read", "Glob", "Grep"}

# WHAT: Tool names that indicate file modification.
# WHY: Tracked separately for session summary reporting.
_MODIFICATION_TOOLS = {"Write", "Edit"}


class TranscriptAnalyzer:
    """Extracts objective metrics from a Claude Code JSONL transcript.

    Uses cortex.transcript as a library to parse entries and extract tool
    calls. Does not invoke hooks or modify any state — purely read-only
    analysis.

    Usage:
        analyzer = TranscriptAnalyzer(Path("transcript.jsonl"))
        metrics = analyzer.analyze()
        print(f"Cold start: {metrics.cold_start_minutes:.1f} min")
        print(f"Files explored: {len(metrics.files_explored)}")
    """

    def __init__(self, transcript_path: Path):
        self._path = transcript_path
        self._entries: list[TranscriptEntry] = []
        self._parsed = False

    def analyze(self) -> TranscriptMetrics:
        """Parse the transcript and compute all extractable metrics.

        Returns:
            TranscriptMetrics with all objective measurements filled in.
        """
        self._parse()

        return TranscriptMetrics(
            cold_start_minutes=self._cold_start_minutes(),
            files_explored=self._files_explored(),
            files_modified=self._files_modified(),
            session_duration_minutes=self._session_duration_minutes(),
            tool_call_count=self._tool_call_count(),
            transcript_path=str(self._path),
        )

    def _parse(self) -> None:
        """Parse the transcript file into entries (cached)."""
        if self._parsed:
            return

        reader = TranscriptReader(self._path)
        self._entries = reader.read_all()
        self._parsed = True

    def _get_timestamps(self) -> list[datetime]:
        """Extract all timestamps from entries as datetime objects.

        Returns:
            Sorted list of parsed timestamps. Entries without timestamps
            are silently skipped.
        """
        timestamps = []
        for entry in self._entries:
            if entry.timestamp:
                ts = _parse_timestamp(entry.timestamp)
                if ts:
                    timestamps.append(ts)
        timestamps.sort()
        return timestamps

    def _cold_start_minutes(self) -> float:
        """Compute minutes from session start to first meaningful action.

        A meaningful action is a Write, Edit, or Bash tool call — something
        that produces observable side effects beyond reading files.

        If no meaningful action exists, returns the full session duration
        (the entire session was exploration/reading).
        """
        session_start = None
        first_action_time = None

        for entry in self._entries:
            ts = _parse_timestamp(entry.timestamp) if entry.timestamp else None
            if ts and session_start is None:
                session_start = ts

            if entry.is_assistant:
                tool_calls = extract_tool_calls(entry)
                for tc in tool_calls:
                    if tc.name in _MEANINGFUL_ACTION_TOOLS:
                        if ts and (first_action_time is None or ts < first_action_time):
                            first_action_time = ts
                        break

        if session_start is None:
            return 0.0

        if first_action_time is None:
            # WHAT: No meaningful action found — entire session was exploration.
            # WHY: Return session duration so the metric reflects that
            #       no productive action happened, which is the worst-case
            #       cold start scenario.
            return self._session_duration_minutes()

        delta = (first_action_time - session_start).total_seconds() / 60.0
        return round(delta, 1)

    def _files_explored(self) -> set[str]:
        """Collect file paths targeted by Read/Glob/Grep tool calls."""
        paths: set[str] = set()
        for entry in self._entries:
            if not entry.is_assistant:
                continue
            for tc in extract_tool_calls(entry):
                if tc.name in _EXPLORATION_TOOLS:
                    path = _extract_file_path(tc.name, tc.input)
                    if path:
                        paths.add(path)
        return paths

    def _files_modified(self) -> set[str]:
        """Collect file paths targeted by Write/Edit tool calls."""
        paths: set[str] = set()
        for entry in self._entries:
            if not entry.is_assistant:
                continue
            for tc in extract_tool_calls(entry):
                if tc.name in _MODIFICATION_TOOLS:
                    path = _extract_file_path(tc.name, tc.input)
                    if path:
                        paths.add(path)
        return paths

    def _session_duration_minutes(self) -> float:
        """Compute total session duration from first to last entry."""
        timestamps = self._get_timestamps()
        if len(timestamps) < 2:
            return 0.0
        delta = (timestamps[-1] - timestamps[0]).total_seconds() / 60.0
        return round(delta, 1)

    def _tool_call_count(self) -> int:
        """Count total tool invocations across all assistant entries."""
        count = 0
        for entry in self._entries:
            if entry.is_assistant:
                count += len(extract_tool_calls(entry))
        return count


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO 8601 timestamp string to datetime.

    Handles the formats emitted by Claude Code:
    - 2026-02-05T19:30:00.000Z (with milliseconds)
    - 2026-02-05T19:30:00Z (without milliseconds)
    - 2026-02-05T19:30:00.000+00:00 (with timezone offset)

    Returns:
        Parsed datetime, or None if parsing fails.
    """
    if not ts_str:
        return None

    # WHAT: Strip trailing 'Z' and replace with +00:00 for fromisoformat.
    # WHY: Python's fromisoformat() doesn't handle 'Z' until Python 3.11.
    #       We support 3.11+ but normalizing is safer.
    normalized = ts_str.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_file_path(tool_name: str, tool_input: dict) -> str:
    """Extract the target file path from a tool call's input.

    Different tools use different parameter names:
    - Read: file_path
    - Write: file_path
    - Edit: file_path
    - Glob: pattern (not a single file — skip)
    - Grep: path or pattern

    Returns:
        The file path string, or empty string if not found.
    """
    # WHAT: Check common parameter names for file paths.
    # WHY: Each Claude Code tool uses slightly different input schemas.
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path", "")
    elif tool_name == "Grep":
        return tool_input.get("path", "")
    elif tool_name == "Glob":
        # WHAT: Use the path parameter, not pattern.
        # WHY: Glob's pattern is a glob expression (e.g., "**/*.py"),
        #       not a file path. The path parameter is the search directory.
        return tool_input.get("path", "")

    return ""

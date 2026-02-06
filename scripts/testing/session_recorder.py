"""Session recorder for Phase 3 baseline data collection.

# WHAT: Manages JSON storage of session metrics and provides an interactive
#       CLI for recording sessions with hybrid auto-extracted + manual metrics.
# WHY: Phase 3 requires recording 5-10 sessions without Cortex. Two metrics
#       (cold start, re-exploration) are auto-extracted from transcripts.
#       Two metrics (decision regression, continuity score) need human input.
#       This module handles both, plus persistent storage and running stats.

Contains two classes:
- BaselineDataStore: JSON file persistence with summary recomputation
- SessionRecorder: Interactive CLI orchestrating the recording workflow
"""

import json
from datetime import datetime
from pathlib import Path

from cortex.transcript import find_latest_transcript, find_transcript_path
from scripts.testing.transcript_analyzer import TranscriptAnalyzer


class BaselineDataStore:
    """Persistent JSON storage for baseline session data.

    Stores session records in a JSON file with automatic summary
    recomputation on every save. The schema supports incremental
    recording — sessions are appended one at a time.

    The JSON file location defaults to docs/testing/baseline-data.json
    (relative to the project root). It should be added to .gitignore
    since it contains local file paths.
    """

    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        """Path to the JSON data file."""
        return self._path

    def load(self) -> dict:
        """Load existing data or create an empty store.

        Returns:
            The data store dict with 'version', 'phase', 'sessions',
            and 'summary' keys.
        """
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)

        return {
            "version": 1,
            "phase": "baseline",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": [],
            "summary": {},
        }

    def save(self, data: dict) -> None:
        """Write the data store to disk with updated summary.

        Creates parent directories if they don't exist.
        Recomputes summary statistics before saving.

        Args:
            data: The full data store dict.
        """
        data["summary"] = self._recompute_summary(data)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def add_session(self, session: dict) -> dict:
        """Append a session record and save.

        Args:
            session: A session record dict with metric fields.

        Returns:
            The updated data store dict.
        """
        data = self.load()
        session["session_number"] = len(data["sessions"]) + 1
        session["recorded_at"] = datetime.now().isoformat(timespec="seconds")
        data["sessions"].append(session)
        self.save(data)
        return data

    def get_sessions(self) -> list[dict]:
        """Return all recorded session records."""
        return self.load().get("sessions", [])

    def get_all_files_explored(self) -> set[str]:
        """Cumulative set of files explored across all recorded sessions.

        Used by SessionRecorder to compute re-exploration count for
        a new session (intersection with the new session's files).
        """
        files: set[str] = set()
        for session in self.get_sessions():
            files.update(session.get("files_explored", []))
        return files

    def get_summary(self) -> dict:
        """Return the current summary statistics."""
        return self.load().get("summary", {})

    def reset(self) -> None:
        """Clear all session data and reset the store.

        Does NOT prompt for confirmation — the caller (run_phase3.py)
        handles that.
        """
        data = {
            "version": 1,
            "phase": "baseline",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": [],
            "summary": {},
        }
        self.save(data)

    def _recompute_summary(self, data: dict) -> dict:
        """Calculate avg/min/max for all numeric metrics.

        Returns:
            Summary dict with statistics for each metric.
        """
        sessions = data.get("sessions", [])
        if not sessions:
            return {"total_sessions": 0}

        cold_starts = [s["cold_start_minutes"] for s in sessions]
        regressions = [s["decision_regression_count"] for s in sessions]
        re_explorations = [s["re_exploration_count"] for s in sessions]
        continuity = [s["continuity_score"] for s in sessions]

        def _stats(values: list[float | int]) -> dict:
            return {
                "avg": round(sum(values) / len(values), 1),
                "min": min(values),
                "max": max(values),
            }

        return {
            "total_sessions": len(sessions),
            "cold_start": _stats(cold_starts),
            "decision_regression": _stats(regressions),
            "re_exploration": _stats(re_explorations),
            "continuity_score": _stats(continuity),
        }


class SessionRecorder:
    """Interactive CLI for recording a baseline session.

    Orchestrates the full recording workflow:
    1. Finds the most recent transcript (auto-discover or explicit path)
    2. Runs TranscriptAnalyzer to extract objective metrics
    3. Computes re-exploration count from prior sessions
    4. Prompts for subjective metrics (decision regression, continuity score)
    5. Saves to BaselineDataStore
    6. Prints running averages

    Usage:
        store = BaselineDataStore(Path("docs/testing/baseline-data.json"))
        recorder = SessionRecorder(store, project_cwd="/path/to/project")
        session = recorder.record_session()
    """

    def __init__(self, store: BaselineDataStore, project_cwd: str | None = None):
        self._store = store
        self._project_cwd = project_cwd

    def record_session(self, transcript_path: Path | None = None) -> dict:
        """Full interactive recording flow.

        Args:
            transcript_path: Explicit path to a transcript file. If None,
                auto-discovers the most recent transcript for the project.

        Returns:
            The recorded session dict.

        Raises:
            FileNotFoundError: If no transcript can be found.
            SystemExit: If the user cancels (Ctrl+C).
        """
        # Step 1: Find transcript
        if transcript_path is None:
            transcript_path = self._discover_transcript()

        print(f"  Found transcript: {transcript_path}")

        # Step 2: Analyze transcript for objective metrics
        analyzer = TranscriptAnalyzer(transcript_path)
        metrics = analyzer.analyze()

        print(f"  Session duration: {metrics.session_duration_minutes:.1f} minutes")
        print(f"  Cold start time: {metrics.cold_start_minutes:.1f} minutes (auto-extracted)")
        print(f"  Tool calls: {metrics.tool_call_count}")
        print(f"  Files explored: {len(metrics.files_explored)}")
        print(f"  Files modified: {len(metrics.files_modified)}")

        # Step 3: Compute re-exploration count
        prior_files = self._store.get_all_files_explored()
        re_explored = metrics.files_explored & prior_files
        re_exploration_count = len(re_explored)

        if re_explored:
            print(f"  Re-exploration count: {re_exploration_count} (auto-extracted)")
            print(f"    Re-explored files: {', '.join(sorted(re_explored)[:5])}")
            if len(re_explored) > 5:
                print(f"    ... and {len(re_explored) - 5} more")
        else:
            session_num = len(self._store.get_sessions()) + 1
            if session_num == 1:
                print("  Re-exploration count: 0 (first session — no prior data)")
            else:
                print("  Re-exploration count: 0 (no files re-explored)")

        # Step 4: Prompt for subjective metrics
        print("\n  --- Subjective metrics (your input needed) ---")
        task_description = _prompt("  Task description: ")
        decision_regression_count = _prompt_int("  Decision regression count (0+): ", min_val=0)
        continuity_score = _prompt_int("  Continuity score (1-5): ", min_val=1, max_val=5)
        notes = _prompt("  Notes (optional): ", required=False)

        # Step 5: Build session record
        session = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "task_description": task_description,
            "cold_start_minutes": metrics.cold_start_minutes,
            "decision_regression_count": decision_regression_count,
            "re_exploration_count": re_exploration_count,
            "continuity_score": continuity_score,
            "notes": notes,
            "transcript_path": str(transcript_path),
            "files_explored": sorted(metrics.files_explored),
            "files_modified": sorted(metrics.files_modified),
            "session_duration_minutes": metrics.session_duration_minutes,
            "tool_call_count": metrics.tool_call_count,
        }

        # Step 6: Save and show running averages
        data = self._store.add_session(session)
        self._print_running_averages(data)

        return session

    def _discover_transcript(self) -> Path:
        """Auto-discover the most recent transcript for the project.

        Uses cortex.transcript.find_transcript_path() and
        find_latest_transcript() to locate the most recent
        non-agent JSONL file.

        Raises:
            FileNotFoundError: If no transcript directory or file is found.
        """
        if self._project_cwd is None:
            msg = (
                "No transcript path provided and no project directory specified.\n"
                "Use --transcript to specify a transcript file, or run from the project directory."
            )
            raise FileNotFoundError(msg)

        transcript_dir = find_transcript_path(self._project_cwd)
        if transcript_dir is None:
            msg = (
                f"No Claude Code transcript directory found for: {self._project_cwd}\n"
                f"Expected: ~/.claude/projects/{self._project_cwd.replace('/', '-')}/"
            )
            raise FileNotFoundError(msg)

        latest = find_latest_transcript(transcript_dir)
        if latest is None:
            msg = f"No transcript files found in: {transcript_dir}"
            raise FileNotFoundError(msg)

        return latest

    def _print_running_averages(self, data: dict) -> None:
        """Print running average statistics after recording."""
        summary = data.get("summary", {})
        total = summary.get("total_sessions", 0)

        print(f"\n  Session {total} recorded. Running averages:")

        cs = summary.get("cold_start", {})
        if cs:
            print(f"    Cold start: {cs['avg']:.1f} min (avg), {cs['min']:.1f} min (min), {cs['max']:.1f} min (max)")

        dr = summary.get("decision_regression", {})
        if dr:
            print(f"    Decision regression: {dr['avg']:.1f} (avg)")

        re = summary.get("re_exploration", {})
        if re:
            print(f"    Re-exploration: {re['avg']:.1f} (avg)")

        cont = summary.get("continuity_score", {})
        if cont:
            print(f"    Continuity score: {cont['avg']:.1f} (avg)")


def _prompt(message: str, required: bool = True) -> str:
    """Prompt the user for text input.

    Args:
        message: The prompt message to display.
        required: If True, re-prompts on empty input.

    Returns:
        The user's input string (stripped).
    """
    while True:
        value = input(message).strip()
        if value or not required:
            return value
        print("    (required — please enter a value)")


def _prompt_int(message: str, min_val: int = 0, max_val: int | None = None) -> int:
    """Prompt the user for an integer input with validation.

    Args:
        message: The prompt message to display.
        min_val: Minimum acceptable value (inclusive).
        max_val: Maximum acceptable value (inclusive), or None for no max.

    Returns:
        The validated integer.
    """
    while True:
        raw = input(message).strip()
        try:
            value = int(raw)
        except ValueError:
            print("    (please enter a number)")
            continue

        if value < min_val:
            print(f"    (must be >= {min_val})")
            continue

        if max_val is not None and value > max_val:
            print(f"    (must be <= {max_val})")
            continue

        return value

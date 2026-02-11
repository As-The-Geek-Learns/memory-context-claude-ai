"""Session recorder for Phase 4 comparison data collection.

# WHAT: Manages JSON storage of Cortex-enabled session metrics and provides
#       an interactive CLI for recording sessions with hybrid auto/manual metrics.
# WHY: Phase 4 requires recording 5-10 sessions WITH Cortex enabled. In addition
#       to the 4 baseline metrics, two new metrics are auto-extracted:
#       briefing_token_count (from cortex-briefing.md) and event_count
#       (from the EventStore). This enables A/B comparison against Phase 3.

Contains two classes:
- ComparisonDataStore: JSON file persistence with summary recomputation
- ComparisonRecorder: Interactive CLI orchestrating the recording workflow
"""

import json
from datetime import datetime
from pathlib import Path

from cortex.project import get_project_hash
from cortex.store import EventStore
from cortex.transcript import find_latest_transcript, find_transcript_path
from scripts.testing.session_recorder import _prompt, _prompt_int
from scripts.testing.transcript_analyzer import TranscriptAnalyzer

# WHAT: Approximate characters per token for estimating briefing size.
# WHY: The research paper specifies a 200K context window. Briefing
#       overhead is measured as a percentage of this budget.
CHARS_PER_TOKEN = 4
CONTEXT_WINDOW_TOKENS = 200_000


class ComparisonDataStore:
    """Persistent JSON storage for comparison (Cortex-enabled) session data.

    Mirrors BaselineDataStore but tracks 6 metrics instead of 4:
    the 4 baseline metrics plus briefing_token_count and event_count.

    The JSON file location defaults to docs/testing/comparison-data.json
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
            "phase": "comparison",
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

        Used by ComparisonRecorder to compute re-exploration count for
        a new session (intersection with the new session's files).
        Re-exploration is tracked against Phase 4 sessions only for
        clean methodology.
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

        Does NOT prompt for confirmation — the caller (run_phase4.py)
        handles that.
        """
        data = {
            "version": 1,
            "phase": "comparison",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": [],
            "summary": {},
        }
        self.save(data)

    def _recompute_summary(self, data: dict) -> dict:
        """Calculate avg/min/max for all numeric metrics.

        Includes the two new Phase 4 metrics: briefing_token_count
        and event_count.

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
        briefing_tokens = [s["briefing_token_count"] for s in sessions]
        event_counts = [s["event_count"] for s in sessions]

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
            "briefing_token_count": _stats(briefing_tokens),
            "event_count": _stats(event_counts),
        }


class ComparisonRecorder:
    """Interactive CLI for recording a Cortex-enabled session.

    Orchestrates the full recording workflow:
    1. Finds the most recent transcript (auto-discover or explicit path)
    2. Runs TranscriptAnalyzer to extract objective metrics
    3. Computes re-exploration count from prior Phase 4 sessions
    4. Auto-extracts briefing_token_count from cortex-briefing.md
    5. Auto-extracts event_count from EventStore
    6. Prompts for subjective metrics (decision regression, continuity score)
    7. Saves to ComparisonDataStore
    8. Prints running averages

    Usage:
        store = ComparisonDataStore(Path("docs/testing/comparison-data.json"))
        recorder = ComparisonRecorder(store, project_cwd="/path/to/project")
        session = recorder.record_session()
    """

    def __init__(self, store: ComparisonDataStore, project_cwd: str | None = None):
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

        # Step 3: Compute re-exploration count (against Phase 4 sessions only)
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
                print("  Re-exploration count: 0 (first comparison session — no prior data)")
            else:
                print("  Re-exploration count: 0 (no files re-explored)")

        # Step 4: Auto-extract Cortex-specific metrics
        briefing_token_count = self._read_briefing_token_count()
        event_count = self._read_event_count()

        print(f"  Briefing token count: {briefing_token_count} (auto-extracted)")
        print(f"  Event count: {event_count} (auto-extracted)")

        if briefing_token_count > 0:
            overhead_pct = briefing_token_count / CONTEXT_WINDOW_TOKENS * 100
            print(f"    Token overhead: {overhead_pct:.1f}% of {CONTEXT_WINDOW_TOKENS:,} context window")

        # Step 5: Prompt for subjective metrics
        print("\n  --- Subjective metrics (your input needed) ---")
        task_description = _prompt("  Task description: ")
        decision_regression_count = _prompt_int("  Decision regression count (0+): ", min_val=0)
        continuity_score = _prompt_int("  Continuity score (1-5): ", min_val=1, max_val=5)
        notes = _prompt("  Notes (optional): ", required=False)

        # Step 6: Build session record
        session = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "task_description": task_description,
            "cold_start_minutes": metrics.cold_start_minutes,
            "decision_regression_count": decision_regression_count,
            "re_exploration_count": re_exploration_count,
            "continuity_score": continuity_score,
            "briefing_token_count": briefing_token_count,
            "event_count": event_count,
            "notes": notes,
            "transcript_path": str(transcript_path),
            "files_explored": sorted(metrics.files_explored),
            "files_modified": sorted(metrics.files_modified),
            "session_duration_minutes": metrics.session_duration_minutes,
            "tool_call_count": metrics.tool_call_count,
        }

        # Step 7: Save and show running averages
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

    def _read_briefing_token_count(self) -> int:
        """Read the cortex-briefing.md file and estimate token count.

        Returns:
            Estimated token count (chars // 4), or 0 if no briefing exists.
        """
        if self._project_cwd is None:
            return 0

        briefing_path = Path(self._project_cwd) / ".claude" / "rules" / "cortex-briefing.md"
        if not briefing_path.exists():
            return 0

        try:
            content = briefing_path.read_text(encoding="utf-8")
            if not content.strip():
                return 0
            return len(content) // CHARS_PER_TOKEN
        except OSError:
            return 0

    def _read_event_count(self) -> int:
        """Read the event count from the Cortex EventStore.

        Returns:
            Number of events in the store, or 0 on error.
        """
        if self._project_cwd is None:
            return 0

        try:
            project_hash = get_project_hash(self._project_cwd)
            store = EventStore(project_hash)
            return store.count()
        except Exception:
            return 0

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

        bt = summary.get("briefing_token_count", {})
        if bt:
            print(f"    Briefing tokens: {bt['avg']:.0f} (avg)")

        ec = summary.get("event_count", {})
        if ec:
            print(f"    Event count: {ec['avg']:.0f} (avg)")

"""Baseline report generator for Phase 3 data collection.

# WHAT: Generates a filled-in version of BASELINE-DATA-TEMPLATE.md from
#       recorded session data stored in baseline-data.json.
# WHY: The template has a specific structure with 10 session tables and
#       summary statistics. Filling it in manually is tedious.
#       This generates it automatically from the JSON data store.
"""

from collections import Counter
from pathlib import Path

from scripts.testing.session_recorder import BaselineDataStore


class BaselineReporter:
    """Generates a filled-in baseline data report from recorded sessions.

    Mirrors the structure of docs/testing/BASELINE-DATA-TEMPLATE.md:
    - Header with dates and project description
    - Up to 10 session tables with metrics
    - Summary statistics (avg/min/max)
    - Observations section with auto-generated insights

    Usage:
        store = BaselineDataStore(Path("docs/testing/baseline-data.json"))
        reporter = BaselineReporter(store)
        reporter.write_report(Path("docs/testing/BASELINE-DATA-RESULTS.md"))
    """

    def __init__(self, store: BaselineDataStore):
        self._store = store

    def generate_report(self) -> str:
        """Generate the full markdown report.

        Returns:
            Complete markdown string matching the template structure.
        """
        data = self._store.load()
        sessions = data.get("sessions", [])
        summary = data.get("summary", {})

        sections = [
            self._header(sessions),
            self._instructions_note(),
            self._session_tables(sessions),
            self._summary_statistics(sessions, summary),
            self._observations(sessions),
            self._next_steps(),
        ]

        return "\n".join(sections)

    def write_report(self, output_path: Path) -> Path:
        """Generate and write the report to a file.

        Args:
            output_path: Path to write the markdown report.

        Returns:
            The output path.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate_report()
        output_path.write_text(content, encoding="utf-8")
        print(f"Report written to: {output_path}")
        return output_path

    def _header(self, sessions: list[dict]) -> str:
        """Generate the report header with date range."""
        if sessions:
            dates = [s.get("date", "") for s in sessions if s.get("date")]
            start = min(dates) if dates else "N/A"
            end = max(dates) if dates else "N/A"
        else:
            start = "N/A"
            end = "N/A"

        return (
            "# Tier 0 Baseline Data Collection Results\n\n"
            "**Purpose:** Record 5-10 sessions **without Cortex** to establish baselines "
            "for cold start time, decision regression, and re-exploration.\n\n"
            f"**Period:** {start} to {end}\n"
            f"**Sessions recorded:** {len(sessions)}\n"
            "**Method:** Automated extraction (scripts/testing/run_phase3.py) + manual input\n\n"
            "---\n"
        )

    def _instructions_note(self) -> str:
        """Brief note about data collection method."""
        return (
            "\n## Data Collection Method\n\n"
            "- **Cold start time** and **re-exploration count**: Auto-extracted from "
            "Claude Code JSONL transcripts\n"
            "- **Decision regression count** and **continuity score**: Recorded manually "
            "by the developer after each session\n\n"
            "---\n"
        )

    def _session_tables(self, sessions: list[dict]) -> str:
        """Generate session data tables (up to 10 slots)."""
        lines: list[str] = ["\n## Session Data\n"]

        for i in range(10):
            optional = " — Optional" if i >= 5 else ""
            lines.append(f"### Session {i + 1} (without Cortex){optional}\n")

            if i < len(sessions):
                s = sessions[i]
                lines.append("| Field | Value |")
                lines.append("|-------|-------|")
                lines.append(f"| **Date** | {s.get('date', 'N/A')} |")
                lines.append(f"| **Task** | {s.get('task_description', 'N/A')} |")
                lines.append(f"| **Cold start time** | {s.get('cold_start_minutes', 'N/A')} minutes |")
                lines.append(f"| **Decision regression count** | {s.get('decision_regression_count', 'N/A')} |")
                lines.append(f"| **Re-exploration count** | {s.get('re_exploration_count', 'N/A')} |")
                lines.append(f"| **Continuity score** | {s.get('continuity_score', 'N/A')} |")
                notes = s.get("notes", "") or "(none)"
                lines.append(f"| **Notes** | {notes} |")

                # Extra detail: files explored/modified
                duration = s.get("session_duration_minutes", 0)
                tools = s.get("tool_call_count", 0)
                explored = len(s.get("files_explored", []))
                modified = len(s.get("files_modified", []))
                lines.append(
                    f"| **Session details** | {duration:.1f} min, {tools} tool calls, "
                    f"{explored} files explored, {modified} files modified |"
                )
            else:
                lines.append("*Not yet recorded.*\n")

            lines.append("\n---\n")

        return "\n".join(lines)

    def _summary_statistics(self, sessions: list[dict], summary: dict) -> str:
        """Generate the summary statistics table."""
        total = len(sessions)
        if total == 0:
            return "\n## Summary Statistics\n\n*No sessions recorded yet.*\n\n---\n"

        cs = summary.get("cold_start", {})
        dr = summary.get("decision_regression", {})
        re = summary.get("re_exploration", {})
        cont = summary.get("continuity_score", {})

        def _fmt(stats: dict, decimals: int = 1) -> tuple[str, str, str]:
            if not stats:
                return ("N/A", "N/A", "N/A")
            fmt = f".{decimals}f"
            return (
                f"{stats.get('avg', 0):{fmt}}",
                f"{stats.get('min', 0):{fmt}}",
                f"{stats.get('max', 0):{fmt}}",
            )

        cs_avg, cs_min, cs_max = _fmt(cs)
        dr_avg, dr_min, dr_max = _fmt(dr)
        re_avg, re_min, re_max = _fmt(re)
        co_avg, co_min, co_max = _fmt(cont)

        return (
            "\n## Summary Statistics\n\n"
            "| Metric | Sessions Recorded | Average | Min | Max |\n"
            "|--------|------------------|---------|-----|-----|\n"
            f"| Cold start time (min) | {total} | {cs_avg} | {cs_min} | {cs_max} |\n"
            f"| Decision regression count | {total} | {dr_avg} | {dr_min} | {dr_max} |\n"
            f"| Re-exploration count | {total} | {re_avg} | {re_min} | {re_max} |\n"
            f"| Continuity score (1-5) | {total} | {co_avg} | {co_min} | {co_max} |\n\n"
            "---\n"
        )

    def _observations(self, sessions: list[dict]) -> str:
        """Generate observations section with auto-generated insights."""
        lines: list[str] = ["\n## Observations\n"]

        if not sessions:
            lines.append("*No sessions recorded yet.*\n")
            return "\n".join(lines)

        # Most frequently re-explored files
        lines.append("### Files Most Frequently Explored\n")
        file_counts: Counter[str] = Counter()
        for s in sessions:
            for f in s.get("files_explored", []):
                file_counts[f] += 1

        # WHAT: Show files explored in 2+ sessions.
        # WHY: These are the files that benefit most from Cortex memory —
        #       they keep being re-read because Claude doesn't remember them.
        multi_session_files = [(f, c) for f, c in file_counts.most_common(15) if c >= 2]
        if multi_session_files:
            lines.append("Files explored in multiple sessions (candidates for Cortex memory):\n")
            for filepath, count in multi_session_files:
                lines.append(f"- `{filepath}` — {count} sessions")
            lines.append("")
        else:
            if len(sessions) < 2:
                lines.append("*Need 2+ sessions to detect re-exploration patterns.*\n")
            else:
                lines.append("*No files were explored in multiple sessions.*\n")

        # Context loss patterns
        lines.append("### Common Context Loss Patterns\n")
        high_regression = [s for s in sessions if s.get("decision_regression_count", 0) >= 2]
        if high_regression:
            lines.append(f"{len(high_regression)} of {len(sessions)} sessions had 2+ decision regressions:\n")
            for s in high_regression:
                notes = s.get("notes", "(no notes)")
                lines.append(
                    f"- Session {s.get('session_number', '?')}: "
                    f"{s.get('decision_regression_count', 0)} regressions — {notes}"
                )
            lines.append("")
        else:
            lines.append("*No sessions had significant decision regression (2+).*\n")

        # Cold start analysis
        lines.append("### Cold Start Analysis\n")
        cold_starts = [s.get("cold_start_minutes", 0) for s in sessions]
        avg_cs = sum(cold_starts) / len(cold_starts) if cold_starts else 0
        slow_starts = [s for s in sessions if s.get("cold_start_minutes", 0) > avg_cs * 1.5]
        if slow_starts:
            lines.append(
                f"Average cold start: {avg_cs:.1f} minutes. "
                f"{len(slow_starts)} sessions had notably slow starts (>1.5x average):\n"
            )
            for s in slow_starts:
                lines.append(
                    f"- Session {s.get('session_number', '?')}: "
                    f"{s.get('cold_start_minutes', 0):.1f} min — {s.get('task_description', '(no task)')}"
                )
            lines.append("")
        else:
            lines.append(f"Average cold start: {avg_cs:.1f} minutes. No outliers detected.\n")

        lines.append("---\n")
        return "\n".join(lines)

    def _next_steps(self) -> str:
        """Generate the next steps section."""
        return (
            "\n## Next Steps\n\n"
            "After completing 5-10 baseline sessions:\n"
            "1. Re-enable Cortex hooks in Claude Code settings\n"
            "2. Proceed to Phase 4 (A/B Comparison)\n"
            "3. Use the same project and comparable tasks for fair comparison\n"
        )

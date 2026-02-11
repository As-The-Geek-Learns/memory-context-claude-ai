"""A/B comparison report generator for Phase 4.

# WHAT: Generates a filled-in version of AB-COMPARISON-TEMPLATE.md from
#       both baseline (Phase 3) and comparison (Phase 4) session data.
# WHY: The template has a specific structure with session tables, A/B
#       comparison table, and success criteria evaluation. Filling it in
#       manually is tedious and error-prone — this generates it automatically
#       with correct improvement percentages and pass/fail evaluations.
"""

from collections import Counter
from pathlib import Path

from scripts.testing.comparison_recorder import (
    CONTEXT_WINDOW_TOKENS,
    ComparisonDataStore,
)
from scripts.testing.session_recorder import BaselineDataStore


class ComparisonReporter:
    """Generates an A/B comparison report from baseline and comparison data.

    Mirrors the structure of docs/testing/AB-COMPARISON-TEMPLATE.md:
    - Header with dates and project description
    - Up to 10 session tables with metrics (including Cortex-specific)
    - A/B comparison table with improvement percentages
    - Success criteria evaluation with pass/fail
    - Qualitative observation sections (placeholders for manual input)

    Usage:
        baseline_store = BaselineDataStore(Path("docs/testing/baseline-data.json"))
        comparison_store = ComparisonDataStore(Path("docs/testing/comparison-data.json"))
        reporter = ComparisonReporter(baseline_store, comparison_store)
        reporter.write_report(Path("docs/testing/AB-COMPARISON-RESULTS.md"))
    """

    def __init__(self, baseline_store: BaselineDataStore, comparison_store: ComparisonDataStore):
        self._baseline_store = baseline_store
        self._comparison_store = comparison_store

    def generate_report(self) -> str:
        """Generate the full A/B comparison markdown report.

        Returns:
            Complete markdown string matching the template structure.
        """
        baseline_data = self._baseline_store.load()
        comparison_data = self._comparison_store.load()

        baseline_summary = baseline_data.get("summary", {})
        comparison_sessions = comparison_data.get("sessions", [])
        comparison_summary = comparison_data.get("summary", {})

        sections = [
            self._header(comparison_sessions),
            self._instructions_note(),
            self._session_tables(comparison_sessions),
            self._comparison_table(baseline_summary, comparison_summary),
            self._success_criteria(baseline_summary, comparison_summary),
            self._observations(comparison_sessions),
            self._qualitative_sections(),
            self._conclusion(),
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
            "# Tier 0 A/B Comparison Results\n\n"
            "**Purpose:** Compare Cortex-enabled sessions vs. baseline sessions "
            "to measure improvement.\n\n"
            f"**Period:** {start} to {end}\n"
            f"**Sessions recorded:** {len(sessions)}\n"
            "**Method:** Automated extraction (scripts/testing/run_phase4.py) + manual input\n\n"
            "---\n"
        )

    def _instructions_note(self) -> str:
        """Brief note about data collection method."""
        return (
            "\n## Data Collection Method\n\n"
            "- **Cold start time**, **re-exploration count**, **briefing token count**, "
            "and **event count**: Auto-extracted\n"
            "- **Decision regression count** and **continuity score**: Recorded manually "
            "by the developer after each session\n\n"
            "---\n"
        )

    def _session_tables(self, sessions: list[dict]) -> str:
        """Generate session data tables (up to 10 slots)."""
        lines: list[str] = ["\n## Cortex-Enabled Session Data\n"]

        for i in range(10):
            lines.append(f"### Session {i + 1} (with Cortex)\n")

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
                lines.append(f"| **Briefing token count** | {s.get('briefing_token_count', 'N/A')} |")
                lines.append(f"| **Event count** | {s.get('event_count', 'N/A')} |")
                notes = s.get("notes", "") or "(none)"
                lines.append(f"| **Notes** | {notes} |")

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

    def _comparison_table(self, baseline_summary: dict, comparison_summary: dict) -> str:
        """Generate the A/B comparison results table.

        Calculates improvement percentages for each metric. For metrics
        where lower is better (cold start, regression, re-exploration),
        improvement = reduction. For higher-is-better (continuity),
        improvement = increase.
        """
        lines: list[str] = ["\n## A/B Comparison Results\n"]

        baseline_total = baseline_summary.get("total_sessions", 0)
        comparison_total = comparison_summary.get("total_sessions", 0)

        if baseline_total == 0 or comparison_total == 0:
            lines.append("*Need both baseline and comparison data to generate comparison.*\n")
            lines.append("---\n")
            return "\n".join(lines)

        lines.append("| Metric | Baseline Avg | Cortex Avg | Improvement | Target | Met? |")
        lines.append("|--------|-------------|-----------|-------------|--------|------|")

        # Cold start — lower is better
        cs_base = baseline_summary.get("cold_start", {}).get("avg", 0)
        cs_comp = comparison_summary.get("cold_start", {}).get("avg", 0)
        cs_imp = _calc_improvement(cs_base, cs_comp, lower_is_better=True)
        cs_met = "Yes" if cs_imp >= 80.0 else "No"
        lines.append(
            f"| Cold start time (min) | {cs_base:.1f} | {cs_comp:.1f} | {cs_imp:.0f}% reduction | 80%+ | {cs_met} |"
        )

        # Decision regression — lower is better
        dr_base = baseline_summary.get("decision_regression", {}).get("avg", 0)
        dr_comp = comparison_summary.get("decision_regression", {}).get("avg", 0)
        dr_imp = _calc_improvement(dr_base, dr_comp, lower_is_better=True)
        dr_met = "Yes" if dr_comp <= 0.1 else "No"
        lines.append(
            f"| Decision regression | {dr_base:.1f} | {dr_comp:.1f} | {dr_imp:.0f}% reduction | Near-zero | {dr_met} |"
        )

        # Re-exploration — lower is better
        re_base = baseline_summary.get("re_exploration", {}).get("avg", 0)
        re_comp = comparison_summary.get("re_exploration", {}).get("avg", 0)
        re_imp = _calc_improvement(re_base, re_comp, lower_is_better=True)
        re_met = "Yes" if re_imp >= 50.0 else "No"
        lines.append(
            f"| Re-exploration count | {re_base:.1f} | {re_comp:.1f} | "
            f"{re_imp:.0f}% reduction | Significant | {re_met} |"
        )

        # Continuity score — higher is better
        co_base = baseline_summary.get("continuity_score", {}).get("avg", 0)
        co_comp = comparison_summary.get("continuity_score", {}).get("avg", 0)
        co_imp = co_comp - co_base
        co_met = "Yes" if co_imp > 0 else "No"
        lines.append(
            f"| Continuity score (1-5) | {co_base:.1f} | {co_comp:.1f} | "
            f"+{co_imp:.1f} points | Improvement | {co_met} |"
        )

        # Token overhead — Cortex-only metric
        bt_comp = comparison_summary.get("briefing_token_count", {}).get("avg", 0)
        overhead_pct = bt_comp / CONTEXT_WINDOW_TOKENS * 100 if bt_comp > 0 else 0
        bt_met = "Yes" if overhead_pct <= 15.0 else "No"
        lines.append(
            f"| Token overhead | N/A | {bt_comp:.0f} tokens | {overhead_pct:.1f}% of context | <=15% | {bt_met} |"
        )

        lines.append("\n---\n")
        return "\n".join(lines)

    def _success_criteria(self, baseline_summary: dict, comparison_summary: dict) -> str:
        """Generate the success criteria evaluation table."""
        lines: list[str] = ["\n## Success Criteria Evaluation\n"]

        baseline_total = baseline_summary.get("total_sessions", 0)
        comparison_total = comparison_summary.get("total_sessions", 0)

        if baseline_total == 0 or comparison_total == 0:
            lines.append("*Need both baseline and comparison data to evaluate criteria.*\n")
            lines.append("---\n")
            return "\n".join(lines)

        lines.append("| Criterion | Target | Result | Status |")
        lines.append("|-----------|--------|--------|--------|")

        # Cold start reduction
        cs_base = baseline_summary.get("cold_start", {}).get("avg", 0)
        cs_comp = comparison_summary.get("cold_start", {}).get("avg", 0)
        cs_imp = _calc_improvement(cs_base, cs_comp, lower_is_better=True)
        cs_pass = cs_imp >= 80.0
        lines.append(
            f"| Cold start time reduction | 80%+ | {cs_imp:.0f}% reduction | {'Pass' if cs_pass else 'Fail'} |"
        )

        # Decision regression
        dr_comp = comparison_summary.get("decision_regression", {}).get("avg", 0)
        dr_pass = dr_comp <= 0.1
        lines.append(f"| Decision regression | Near-zero | {dr_comp:.1f} avg | {'Pass' if dr_pass else 'Fail'} |")

        # Continuity
        co_base = baseline_summary.get("continuity_score", {}).get("avg", 0)
        co_comp = comparison_summary.get("continuity_score", {}).get("avg", 0)
        co_pass = co_comp > co_base
        lines.append(
            f"| Plan continuity | Improvement | {co_base:.1f} -> {co_comp:.1f} | {'Pass' if co_pass else 'Fail'} |"
        )

        # Token overhead
        bt_comp = comparison_summary.get("briefing_token_count", {}).get("avg", 0)
        overhead_pct = bt_comp / CONTEXT_WINDOW_TOKENS * 100 if bt_comp > 0 else 0
        bt_pass = overhead_pct <= 15.0
        lines.append(f"| Token overhead | <=15% | {overhead_pct:.1f}% | {'Pass' if bt_pass else 'Fail'} |")

        # Manual criteria — placeholders
        lines.append("| Extraction accuracy | >90% recall | *(manual evaluation)* | *(pending)* |")
        lines.append("| User maintenance effort | Near-zero | *(manual evaluation)* | *(pending)* |")

        lines.append("\n---\n")
        return "\n".join(lines)

    def _observations(self, sessions: list[dict]) -> str:
        """Generate observations section with auto-generated insights."""
        lines: list[str] = ["\n## Observations\n"]

        if not sessions:
            lines.append("*No comparison sessions recorded yet.*\n")
            return "\n".join(lines)

        # Briefing effectiveness
        lines.append("### Briefing Size Analysis\n")
        briefing_tokens = [s.get("briefing_token_count", 0) for s in sessions]
        avg_bt = sum(briefing_tokens) / len(briefing_tokens) if briefing_tokens else 0
        if avg_bt > 0:
            overhead_pct = avg_bt / CONTEXT_WINDOW_TOKENS * 100
            lines.append(f"Average briefing size: {avg_bt:.0f} tokens ({overhead_pct:.1f}% of context window)\n")

            growing = all(briefing_tokens[i] <= briefing_tokens[i + 1] for i in range(len(briefing_tokens) - 1))
            if len(briefing_tokens) >= 3 and growing:
                lines.append(
                    "*Note: Briefing size is monotonically increasing. Monitor for context budget pressure.*\n"
                )
        else:
            lines.append("*No briefing data recorded.*\n")

        # Files frequently explored (same as baseline reporter)
        lines.append("### Files Most Frequently Explored\n")
        file_counts: Counter[str] = Counter()
        for s in sessions:
            for f in s.get("files_explored", []):
                file_counts[f] += 1

        multi_session_files = [(f, c) for f, c in file_counts.most_common(15) if c >= 2]
        if multi_session_files:
            lines.append("Files explored in multiple comparison sessions:\n")
            for filepath, count in multi_session_files:
                lines.append(f"- `{filepath}` — {count} sessions")
            lines.append("")
        else:
            if len(sessions) < 2:
                lines.append("*Need 2+ sessions to detect re-exploration patterns.*\n")
            else:
                lines.append("*No files were explored in multiple sessions (Cortex reducing re-exploration).*\n")

        # Cold start analysis
        lines.append("### Cold Start Analysis\n")
        cold_starts = [s.get("cold_start_minutes", 0) for s in sessions]
        avg_cs = sum(cold_starts) / len(cold_starts) if cold_starts else 0
        lines.append(f"Average cold start with Cortex: {avg_cs:.1f} minutes\n")

        lines.append("---\n")
        return "\n".join(lines)

    def _qualitative_sections(self) -> str:
        """Generate placeholder sections for manual qualitative input."""
        return (
            "\n## Qualitative Observations\n\n"
            "### Briefing Quality\n\n"
            "*[How useful was the briefing content? Did it include the right information?]*\n\n"
            "### Context Preservation\n\n"
            "*[Did Claude remember decisions, plans, and prior work?]*\n\n"
            "### Pain Points\n\n"
            "*[Any issues with Cortex? Missing events? Wrong information?]*\n\n"
            "### Unexpected Benefits\n\n"
            "*[Any positive surprises? Things that worked better than expected?]*\n\n"
            "---\n"
        )

    def _conclusion(self) -> str:
        """Generate the conclusion section with placeholders."""
        baseline_total = self._baseline_store.get_summary().get("total_sessions", 0)
        comparison_total = self._comparison_store.get_summary().get("total_sessions", 0)

        status = ""
        if baseline_total > 0 and comparison_total > 0:
            # Auto-count pass/fail criteria
            baseline_summary = self._baseline_store.get_summary()
            comparison_summary = self._comparison_store.get_summary()

            pass_count = 0
            total_auto = 4  # 4 auto-evaluated criteria

            cs_base = baseline_summary.get("cold_start", {}).get("avg", 0)
            cs_comp = comparison_summary.get("cold_start", {}).get("avg", 0)
            if _calc_improvement(cs_base, cs_comp, lower_is_better=True) >= 80.0:
                pass_count += 1

            dr_comp = comparison_summary.get("decision_regression", {}).get("avg", 0)
            if dr_comp <= 0.1:
                pass_count += 1

            co_base = baseline_summary.get("continuity_score", {}).get("avg", 0)
            co_comp = comparison_summary.get("continuity_score", {}).get("avg", 0)
            if co_comp > co_base:
                pass_count += 1

            bt_comp = comparison_summary.get("briefing_token_count", {}).get("avg", 0)
            overhead = bt_comp / CONTEXT_WINDOW_TOKENS * 100 if bt_comp > 0 else 0
            if overhead <= 15.0:
                pass_count += 1

            status = f"\n\n**Auto-evaluated criteria: {pass_count}/{total_auto} passed** (2 criteria require manual evaluation)\n"

        return (
            "\n## Conclusion\n\n"
            "**Overall Assessment:** *[ ] Tier 0 meets success criteria [ ] Needs iteration*"
            f"{status}\n"
            "**Recommendation:**\n"
            "- [ ] Proceed to Tier 1 implementation\n"
            "- [ ] Iterate on Tier 0 (specify areas)\n"
            "- [ ] Gather more data before deciding\n\n"
            "**Key Learnings:**\n\n"
            "*[Summarize what was learned from the A/B comparison]*\n"
        )


def _calc_improvement(baseline: float, comparison: float, *, lower_is_better: bool) -> float:
    """Calculate improvement percentage between baseline and comparison.

    Args:
        baseline: The baseline average value.
        comparison: The comparison (Cortex-enabled) average value.
        lower_is_better: If True, a reduction is an improvement.
            If False, an increase is an improvement.

    Returns:
        Improvement percentage. Positive means improved.
        Returns 0.0 if baseline is zero (can't compute percentage).
    """
    if baseline == 0:
        return 0.0

    if lower_is_better:
        return (baseline - comparison) / baseline * 100
    else:
        return (comparison - baseline) / baseline * 100

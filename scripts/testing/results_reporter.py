"""Results reporter for Phase 2 test automation.

# WHAT: Collects structured test results and generates a markdown report.
# WHY: Mirrors the MANUAL-TESTING-TEMPLATE.md format so results are
#       directly comparable — but filled in automatically.
"""

from datetime import datetime
from pathlib import Path


class ResultsReporter:
    """Collects test results and generates a filled-in testing report."""

    def __init__(self):
        self._results: dict[str, dict] = {}
        self._timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    def record(self, phase: str, results: dict) -> None:
        """Record results for a test phase."""
        self._results[phase] = results

    def all_passed(self) -> bool:
        """Check if all recorded test phases passed."""
        return all(r.get("passed", False) for r in self._results.values())

    def print_summary(self) -> None:
        """Print a concise pass/fail summary to stdout."""
        print("\n" + "=" * 60)
        print("CORTEX PHASE 2 AUTOMATED TEST RESULTS")
        print("=" * 60)

        phases = [
            ("2.1", "Single Session Flow"),
            ("2.2", "Multi-Session Continuity"),
            ("2.3.1", "Empty Session"),
            ("2.3.2", "Large Briefing (Budget Overflow)"),
            ("2.3.3", "Reset Command"),
        ]

        all_pass = True
        for phase_id, name in phases:
            result = self._results.get(phase_id, {})
            passed = result.get("passed", False)
            status = "PASS" if passed else "FAIL"
            marker = "[x]" if passed else "[ ]"
            if not passed:
                all_pass = False
            print(f"  {marker} {phase_id} {name}: {status}")

        print("-" * 60)
        overall = "PASS" if all_pass else "FAIL"
        print(f"  Overall Phase 2 Result: {overall}")
        print("=" * 60 + "\n")

    def write_report(self, output_path: Path | None = None) -> Path:
        """Generate the filled-in testing results as a markdown file.

        Returns the path to the written file.
        """
        if output_path is None:
            output_path = Path("docs/testing/AUTOMATED-TESTING-RESULTS.md")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._generate_markdown()
        output_path.write_text(content, encoding="utf-8")
        print(f"Report written to: {output_path}")
        return output_path

    def _generate_markdown(self) -> str:
        """Generate the full markdown report."""
        sections = [
            self._header(),
            self._phase_2_1(),
            self._phase_2_2(),
            self._phase_2_3_1(),
            self._phase_2_3_2(),
            self._phase_2_3_3(),
            self._summary_table(),
        ]
        return "\n".join(sections)

    def _header(self) -> str:
        return (
            "# Tier 0 Automated Testing Results\n\n"
            f"**Date:** {self._timestamp}\n"
            "**Tester:** Automated (scripts/testing/run_phase2.py)\n"
            "**Method:** Synthetic transcript generation + direct hook invocation\n\n"
            "---\n"
        )

    def _pass_fail(self, passed: bool) -> str:
        return "PASS" if passed else "FAIL"

    def _check(self, passed: bool) -> str:
        return "[x]" if passed else "[ ]"

    def _phase_2_1(self) -> str:
        r = self._results.get("2.1", {})
        if not r:
            return "\n## Phase 2.1: Single Session Flow\n\n*Not executed.*\n"

        lines = [
            "\n## Phase 2.1: Single Session Flow\n",
            "**Goal:** Verify extraction and briefing generation after a single session.\n",
            "### Test Steps\n",
            "| Step | Action | Expected | Actual | Pass? |",
            "|------|--------|----------|--------|-------|",
        ]

        for step in r.get("steps", []):
            status = self._pass_fail(step["passed"])
            lines.append(f"| {step['step']} | {step['action']} | {step['expected']} | {step['actual']} | {status} |")

        lines.append(f"\n**Event count after session:** {r.get('event_count', 'N/A')}\n")

        # Events found table
        events_found = r.get("events_found", [])
        if events_found:
            lines.append("**Events extracted:**\n")
            lines.append("| Event Type | Content (summary) | Found? |")
            lines.append("|------------|-------------------|--------|")
            for ef in events_found:
                found = "Yes" if ef["found"] else "No"
                lines.append(f"| {ef['type']} | {ef['content']} | {found} |")

        # Briefing content
        briefing = r.get("briefing_content", "")
        if briefing:
            lines.append("\n**Briefing content:**\n")
            lines.append("```markdown")
            # Truncate if very long
            if len(briefing) > 2000:
                lines.append(briefing[:2000] + "\n... (truncated)")
            else:
                lines.append(briefing)
            lines.append("```\n")

        return "\n".join(lines)

    def _phase_2_2(self) -> str:
        r = self._results.get("2.2", {})
        if not r:
            return "\n## Phase 2.2: Multi-Session Continuity\n\n*Not executed.*\n"

        lines = [
            "\n## Phase 2.2: Multi-Session Continuity\n",
            "**Goal:** Verify briefing is loaded and context persists across sessions.\n",
        ]

        # Session results
        s1_decisions = r.get("session1_briefing_has_decisions", False)
        plan_in_briefing = r.get("plan_in_briefing", False)
        total_events = r.get("total_events", 0)

        lines.append("### Results\n")
        lines.append(
            f"**Did briefing reference prior decisions after Session 1?** "
            f"{self._check(s1_decisions)} {'Yes' if s1_decisions else 'No'}\n"
        )
        lines.append(
            f"**Did briefing contain plan after Session 3?** "
            f"{self._check(plan_in_briefing)} {'Yes' if plan_in_briefing else 'No'}\n"
        )
        lines.append(f"**Total events across 3 sessions:** {total_events}\n")

        # Show briefing after session 3
        s3_briefing = r.get("session3_briefing", "")
        if s3_briefing:
            lines.append("**Briefing after Session 3:**\n")
            lines.append("```markdown")
            if len(s3_briefing) > 2000:
                lines.append(s3_briefing[:2000] + "\n... (truncated)")
            else:
                lines.append(s3_briefing)
            lines.append("```\n")

        return "\n".join(lines)

    def _phase_2_3_1(self) -> str:
        r = self._results.get("2.3.1", {})
        if not r:
            return "\n## Phase 2.3.1: Empty Session\n\n*Not executed.*\n"

        lines = [
            "\n## Phase 2.3.1: Empty Session (Edge Case)\n",
            "| Check | Expected | Actual | Pass? |",
            "|-------|----------|--------|-------|",
            f"| Stop hook return code | 0 | {r.get('return_code', 'N/A')} "
            f"| {self._pass_fail(r.get('no_crash', False))} |",
            f"| Event count | 0 or minimal | {r.get('event_count', 'N/A')} "
            f"| {self._pass_fail(r.get('event_count', -1) <= 1)} |",
            f"\n**Result:** {self._check(r.get('passed', False))} {self._pass_fail(r.get('passed', False))}\n",
        ]
        return "\n".join(lines)

    def _phase_2_3_2(self) -> str:
        r = self._results.get("2.3.2", {})
        if not r:
            return "\n## Phase 2.3.2: Large Briefing (Budget Overflow)\n\n*Not executed.*\n"

        lines = [
            "\n## Phase 2.3.2: Large Briefing — Budget Overflow (Edge Case)\n",
            "| Check | Expected | Actual | Pass? |",
            "|-------|----------|--------|-------|",
            f"| Total events | >= 100 | {r.get('total_events', 'N/A')} "
            f"| {self._pass_fail(r.get('total_events', 0) >= 100)} |",
            f"| Briefing chars | <= 12000 | {r.get('briefing_chars', 'N/A')} "
            f"| {self._pass_fail(r.get('under_budget', False))} |",
            f"| Estimated tokens | <= {r.get('max_tokens', 3000)} "
            f"| {r.get('estimated_tokens', 'N/A'):.0f} "
            f"| {self._pass_fail(r.get('under_budget', False))} |",
            f"\n**Result:** {self._check(r.get('passed', False))} {self._pass_fail(r.get('passed', False))}\n",
        ]
        return "\n".join(lines)

    def _phase_2_3_3(self) -> str:
        r = self._results.get("2.3.3", {})
        if not r:
            return "\n## Phase 2.3.3: Reset Command\n\n*Not executed.*\n"

        lines = [
            "\n## Phase 2.3.3: Reset Command (Edge Case)\n",
            "| Check | Expected | Actual | Pass? |",
            "|-------|----------|--------|-------|",
            f"| Events before reset | > 0 | {r.get('count_before', 'N/A')} "
            f"| {self._pass_fail(r.get('count_before', 0) > 0)} |",
            f"| Reset return code | 0 | {r.get('reset_return_code', 'N/A')} "
            f"| {self._pass_fail(r.get('reset_return_code', -1) == 0)} |",
            f"| Events after reset | 0 | {r.get('count_after', 'N/A')} "
            f"| {self._pass_fail(r.get('count_after', -1) == 0)} |",
            f"\n**Result:** {self._check(r.get('passed', False))} {self._pass_fail(r.get('passed', False))}\n",
        ]
        return "\n".join(lines)

    def _summary_table(self) -> str:
        phases = [
            ("2.1", "Single Session Flow"),
            ("2.2", "Multi-Session Continuity"),
            ("2.3.1", "Empty Session"),
            ("2.3.2", "Large Briefing"),
            ("2.3.3", "Reset Command"),
        ]

        lines = [
            "\n---\n\n## Summary\n",
            "| Test | Status |",
            "|------|--------|",
        ]

        for phase_id, name in phases:
            r = self._results.get(phase_id, {})
            passed = r.get("passed", False)
            status = f"{self._check(passed)} {self._pass_fail(passed)}"
            lines.append(f"| {phase_id} {name} | {status} |")

        overall = self.all_passed()
        lines.append(f"\n**Overall Phase 2 Result:** {self._check(overall)} {self._pass_fail(overall)}\n")

        return "\n".join(lines)

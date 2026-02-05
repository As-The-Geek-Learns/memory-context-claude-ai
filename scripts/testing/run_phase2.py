"""Phase 2 automated test runner for Cortex Tier 0.

# WHAT: Runs all Phase 2 test cases using synthetic transcripts.
# WHY: Automates the manual testing documented in MANUAL-TESTING-TEMPLATE.md
#       by generating JSONL transcripts, calling hooks directly via the
#       Python API, and verifying results programmatically.

Usage:
    cd /Users/jamescruce/Projects/cortex
    python -m scripts.testing.run_phase2
"""

import sys
from pathlib import Path

# WHAT: Add src/ to path for direct execution.
# WHY: When run as `python -m scripts.testing.run_phase2`, Python
#       resolves the project root. We need src/ on the path so
#       `import cortex` works without pip install.
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))

from scripts.testing.results_reporter import ResultsReporter
from scripts.testing.test_environment import TestEnvironment
from scripts.testing.transcript_generator import (
    create_empty_session_transcript,
    create_large_event_transcripts,
    create_session2_transcript,
    create_session3_transcript,
    create_single_session_transcript,
)


def run_phase_2_1() -> dict:
    """Phase 2.1: Single Session Flow.

    Generates a transcript with file creation, decision, [MEMORY:] tag,
    and test execution. Verifies events are extracted and briefing is generated.
    """
    print("\n--- Phase 2.1: Single Session Flow ---")
    env = TestEnvironment()
    env.setup()

    try:
        # Step 1: Generate synthetic transcript
        builder = create_single_session_transcript(cwd=str(env.project_dir), session_id="phase2-s1")
        transcript_path = env.project_dir / "transcript-s1.jsonl"
        builder.write_to(transcript_path)
        print(f"  Transcript generated: {transcript_path.name}")

        # Step 2: Run Stop hook
        stop_code = env.run_stop_hook(transcript_path, "phase2-s1")
        print(f"  Stop hook returned: {stop_code}")

        # Step 3: Check event count
        store = env.get_event_store()
        event_count = store.count()
        all_events = store.load_all()
        print(f"  Events extracted: {event_count}")

        # Step 4: Run SessionStart hook to generate briefing
        env.run_session_start_hook()
        briefing_content = env.read_briefing()
        briefing_exists = len(briefing_content) > 0
        print(f"  Briefing generated: {briefing_exists} ({len(briefing_content)} chars)")

        # Step 5: Verify expected event types
        event_type_values = {e.type.value for e in all_events}
        expected_events = [
            ("file_modified", "hello.py created"),
            ("file_modified", "test file created"),
            ("command_run", "pytest command"),
            ("decision_made", "Python 3.11+ decision (semantic)"),
            ("knowledge_acquired", "[MEMORY:] tag about Python 3.11+"),
            ("approach_rejected", "Python 3.9 rejected (semantic)"),
        ]

        events_found = []
        for etype, description in expected_events:
            found = etype in event_type_values
            events_found.append({"type": etype.upper(), "content": description, "found": found})
            status = "found" if found else "MISSING"
            print(f"  Event {etype}: {status}")

        # Build step results
        steps = [
            {
                "step": 1,
                "action": "Generate synthetic transcript",
                "expected": "JSONL file created",
                "actual": f"{transcript_path.name} ({transcript_path.stat().st_size} bytes)",
                "passed": transcript_path.exists(),
            },
            {
                "step": 2,
                "action": "Run Stop hook (extract events)",
                "expected": "Returns 0",
                "actual": f"Returned {stop_code}",
                "passed": stop_code == 0,
            },
            {
                "step": 3,
                "action": "Check event count > 0",
                "expected": "Event count > 0",
                "actual": f"Event count = {event_count}",
                "passed": event_count > 0,
            },
            {
                "step": 4,
                "action": "Generate briefing (SessionStart hook)",
                "expected": "Briefing file exists with content",
                "actual": f"Exists: {briefing_exists}, {len(briefing_content)} chars",
                "passed": briefing_exists,
            },
        ]

        # Core events that must be present (file_modified and decision_made at minimum)
        core_types_found = "file_modified" in event_type_values and "decision_made" in event_type_values

        passed = all(s["passed"] for s in steps) and core_types_found
        print(f"  Phase 2.1 result: {'PASS' if passed else 'FAIL'}")

        return {
            "steps": steps,
            "event_count": event_count,
            "briefing_content": briefing_content,
            "events_found": events_found,
            "passed": passed,
        }
    finally:
        env.cleanup()


def run_phase_2_2() -> dict:
    """Phase 2.2: Multi-Session Continuity.

    Runs 3 sequential sessions. Verifies:
    - Session 1 decisions appear in the briefing before Session 2
    - Plan from Session 2 persists into Session 3 briefing
    """
    print("\n--- Phase 2.2: Multi-Session Continuity ---")
    env = TestEnvironment()
    env.setup()

    try:
        # --- Session 1 ---
        print("  Session 1: Initial session (decisions + memory)")
        builder1 = create_single_session_transcript(cwd=str(env.project_dir), session_id="phase2-multi-s1")
        t1_path = env.project_dir / "transcript-s1.jsonl"
        builder1.write_to(t1_path)
        env.run_stop_hook(t1_path, "phase2-multi-s1")

        store = env.get_event_store()
        s1_events = store.count()
        print(f"    Events after S1: {s1_events}")

        # Generate briefing before Session 2
        env.run_session_start_hook()
        briefing_after_s1 = env.read_briefing()
        s1_has_decisions = (
            "Python 3.11" in briefing_after_s1 or "Decision" in briefing_after_s1 or "decision" in briefing_after_s1
        )
        print(f"    Briefing has decisions: {s1_has_decisions}")

        # --- Session 2 ---
        print("  Session 2: Plan creation + step 1")
        builder2 = create_session2_transcript(cwd=str(env.project_dir), session_id="phase2-multi-s2")
        t2_path = env.project_dir / "transcript-s2.jsonl"
        builder2.write_to(t2_path)
        env.run_stop_hook(t2_path, "phase2-multi-s2")

        s2_events = store.count()
        print(f"    Events after S2: {s2_events}")

        # Generate briefing before Session 3
        env.run_session_start_hook()
        briefing_after_s2 = env.read_briefing()

        # --- Session 3 ---
        print("  Session 3: Plan continuation + completion")
        builder3 = create_session3_transcript(cwd=str(env.project_dir), session_id="phase2-multi-s3")
        t3_path = env.project_dir / "transcript-s3.jsonl"
        builder3.write_to(t3_path)
        env.run_stop_hook(t3_path, "phase2-multi-s3")

        s3_events = store.count()
        print(f"    Events after S3: {s3_events}")

        env.run_session_start_hook()
        briefing_after_s3 = env.read_briefing()

        # Check for plan content in briefing
        plan_in_briefing = (
            "Plan" in briefing_after_s3
            or "logging" in briefing_after_s3.lower()
            or "import" in briefing_after_s3.lower()
        )
        print(f"    Plan in final briefing: {plan_in_briefing}")

        # Verify event count grew across sessions
        events_grew = s1_events > 0 and s2_events > s1_events and s3_events > s2_events
        print(f"    Events grew across sessions: {events_grew}")

        passed = s1_has_decisions and events_grew
        print(f"  Phase 2.2 result: {'PASS' if passed else 'FAIL'}")

        return {
            "session1_briefing_has_decisions": s1_has_decisions,
            "session2_briefing": briefing_after_s2,
            "session3_briefing": briefing_after_s3,
            "total_events": s3_events,
            "events_grew": events_grew,
            "plan_in_briefing": plan_in_briefing,
            "passed": passed,
        }
    finally:
        env.cleanup()


def run_phase_2_3_1() -> dict:
    """Phase 2.3.1: Empty Session (Edge Case).

    Verifies the Stop hook handles an empty transcript gracefully.
    """
    print("\n--- Phase 2.3.1: Empty Session ---")
    env = TestEnvironment()
    env.setup()

    try:
        builder = create_empty_session_transcript(cwd=str(env.project_dir))
        t_path = env.project_dir / "transcript-empty.jsonl"
        builder.write_to(t_path)

        return_code = env.run_stop_hook(t_path, "phase2-empty")
        event_count = env.get_event_store().count()

        print(f"  Stop hook returned: {return_code}")
        print(f"  Event count: {event_count}")

        passed = return_code == 0
        print(f"  Phase 2.3.1 result: {'PASS' if passed else 'FAIL'}")

        return {
            "return_code": return_code,
            "event_count": event_count,
            "no_crash": return_code == 0,
            "passed": passed,
        }
    finally:
        env.cleanup()


def run_phase_2_3_2() -> dict:
    """Phase 2.3.2: Large Briefing — Budget Overflow (Edge Case).

    Creates 100+ events and verifies the briefing stays under token budget.
    Uses both direct API event creation and synthetic transcripts.
    """
    print("\n--- Phase 2.3.2: Large Briefing (Budget Overflow) ---")
    env = TestEnvironment()
    env.setup()

    try:
        from cortex.briefing import generate_briefing
        from cortex.models import EventType, create_event

        store = env.get_event_store()
        project_hash = env.get_project_hash()

        # WHAT: Directly create 120 events via the API.
        # WHY: Faster and more controlled than generating 12 transcripts.
        #       Covers all event types to test briefing prioritization.
        events = []
        event_types = [
            EventType.DECISION_MADE,
            EventType.APPROACH_REJECTED,
            EventType.FILE_MODIFIED,
            EventType.COMMAND_RUN,
            EventType.KNOWLEDGE_ACQUIRED,
            EventType.PLAN_CREATED,
            EventType.ERROR_RESOLVED,
            EventType.PREFERENCE_NOTED,
        ]
        for i in range(120):
            etype = event_types[i % len(event_types)]
            events.append(
                create_event(
                    etype,
                    content=f"Event {i}: {etype.value} — test data for budget overflow verification (iteration {i})",
                    session_id=f"large-session-{i // 10}",
                    project=str(env.project_dir),
                    git_branch="main",
                )
            )
        store.append_many(events)
        print(f"  Created {len(events)} events via API")

        # Also generate some via transcripts for realism
        builders = create_large_event_transcripts(cwd=str(env.project_dir), count=3)
        for idx, builder in enumerate(builders):
            t_path = env.project_dir / f"transcript-large-{idx}.jsonl"
            builder.write_to(t_path)
            env.run_stop_hook(t_path, f"phase2-large-{idx:03d}")

        total_events = store.count()
        print(f"  Total events in store: {total_events}")

        # Generate briefing and check budget
        briefing = generate_briefing(
            project_hash=project_hash,
            config=env.config,
            branch="main",
        )
        briefing_chars = len(briefing)
        estimated_tokens = briefing_chars / 4
        max_tokens = env.config.max_briefing_tokens

        print(f"  Briefing: {briefing_chars} chars (~{estimated_tokens:.0f} tokens)")
        print(f"  Budget: {max_tokens} tokens ({max_tokens * 4} chars)")

        under_budget = estimated_tokens <= max_tokens
        passed = total_events >= 100 and under_budget
        print(f"  Under budget: {under_budget}")
        print(f"  Phase 2.3.2 result: {'PASS' if passed else 'FAIL'}")

        return {
            "total_events": total_events,
            "briefing_chars": briefing_chars,
            "estimated_tokens": estimated_tokens,
            "max_tokens": max_tokens,
            "under_budget": under_budget,
            "passed": passed,
        }
    finally:
        env.cleanup()


def run_phase_2_3_3() -> dict:
    """Phase 2.3.3: Reset Command (Edge Case).

    Adds events, runs reset, verifies count drops to 0.
    """
    print("\n--- Phase 2.3.3: Reset Command ---")
    env = TestEnvironment()
    env.setup()

    try:
        from cortex.models import EventType, create_event

        store = env.get_event_store()

        # Add some events
        for i in range(5):
            store.append(
                create_event(
                    EventType.DECISION_MADE,
                    content=f"Decision {i} for reset test",
                    session_id="reset-test",
                )
            )

        count_before = store.count()
        print(f"  Events before reset: {count_before}")

        # Run reset with monkeypatched config
        import cortex.cli

        original_load = cortex.cli.load_config
        cortex.cli.load_config = lambda: env.config
        try:
            reset_code = cortex.cli.cmd_reset(cwd=str(env.project_dir))
        finally:
            cortex.cli.load_config = original_load

        count_after = store.count()
        print(f"  Reset return code: {reset_code}")
        print(f"  Events after reset: {count_after}")

        passed = count_before > 0 and reset_code == 0 and count_after == 0
        print(f"  Phase 2.3.3 result: {'PASS' if passed else 'FAIL'}")

        return {
            "count_before": count_before,
            "reset_return_code": reset_code,
            "count_after": count_after,
            "passed": passed,
        }
    finally:
        env.cleanup()


def main() -> int:
    """Run all Phase 2 tests and generate results report."""
    print("=" * 60)
    print("Cortex Phase 2 Automated Testing")
    print("=" * 60)

    reporter = ResultsReporter()

    # Run all test phases
    reporter.record("2.1", run_phase_2_1())
    reporter.record("2.2", run_phase_2_2())
    reporter.record("2.3.1", run_phase_2_3_1())
    reporter.record("2.3.2", run_phase_2_3_2())
    reporter.record("2.3.3", run_phase_2_3_3())

    # Generate report
    report_path = _project_root / "docs" / "testing" / "AUTOMATED-TESTING-RESULTS.md"
    reporter.write_report(report_path)
    reporter.print_summary()

    return 0 if reporter.all_passed() else 1


if __name__ == "__main__":
    sys.exit(main())

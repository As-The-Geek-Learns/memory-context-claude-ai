"""Phase 3 baseline data collection CLI for Cortex Tier 0.

# WHAT: Main entry point for recording, listing, and reporting baseline
#       session data during Phase 3 testing.
# WHY: Phase 3 requires running 5-10 dev sessions without Cortex and
#       recording 4 metrics per session. This CLI automates the objective
#       metrics and prompts for the subjective ones.

Usage:
    cd /Users/jamescruce/Projects/cortex

    # Record a session (after ending a Claude Code session)
    python -m scripts.testing.run_phase3 record

    # Record with explicit transcript path
    python -m scripts.testing.run_phase3 record --transcript /path/to/file.jsonl

    # List recorded sessions
    python -m scripts.testing.run_phase3 list

    # Show running summary statistics
    python -m scripts.testing.run_phase3 summary

    # Generate filled-in baseline report
    python -m scripts.testing.run_phase3 report

    # Reset all data (with confirmation)
    python -m scripts.testing.run_phase3 reset
"""

import argparse
import sys
from pathlib import Path

# WHAT: Add src/ to path for direct execution.
# WHY: When run as `python -m scripts.testing.run_phase3`, Python
#       resolves the project root. We need src/ on the path so
#       `import cortex` works without pip install.
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))

from scripts.testing.baseline_reporter import BaselineReporter
from scripts.testing.session_recorder import BaselineDataStore, SessionRecorder

# WHAT: Default paths relative to the project root.
# WHY: Keeps all testing data in docs/testing/ alongside other test artifacts.
_DEFAULT_DATA_PATH = _project_root / "docs" / "testing" / "baseline-data.json"
_DEFAULT_REPORT_PATH = _project_root / "docs" / "testing" / "BASELINE-DATA-RESULTS.md"


def cmd_record(args: argparse.Namespace) -> int:
    """Record a baseline session.

    Auto-discovers the most recent transcript or uses --transcript path.
    Extracts objective metrics and prompts for subjective ones.
    """
    print("=" * 60)
    print("Cortex Phase 3 — Record Baseline Session")
    print("=" * 60)

    store = BaselineDataStore(_DEFAULT_DATA_PATH)

    # WHAT: Determine project working directory for transcript discovery.
    # WHY: If --project is given, use it. Otherwise use the Cortex project root.
    #       The user might be collecting baselines for a different project.
    project_cwd = args.project if args.project else str(_project_root)

    transcript_path = Path(args.transcript) if args.transcript else None

    recorder = SessionRecorder(store, project_cwd=project_cwd)

    try:
        recorder.record_session(transcript_path=transcript_path)
        return 0
    except FileNotFoundError as e:
        print(f"\n  Error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\n  Cancelled.")
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List all recorded sessions."""
    store = BaselineDataStore(_DEFAULT_DATA_PATH)
    sessions = store.get_sessions()

    if not sessions:
        print("No sessions recorded yet.")
        print("Run: python -m scripts.testing.run_phase3 record")
        return 0

    print("=" * 60)
    print(f"Cortex Phase 3 — Recorded Sessions ({len(sessions)} total)")
    print("=" * 60)

    print(f"\n  {'#':<3} {'Date':<12} {'Cold Start':<12} {'Regression':<12} {'Re-explore':<12} {'Continuity':<12} Task")
    print("  " + "-" * 78)

    for s in sessions:
        num = s.get("session_number", "?")
        date = s.get("date", "N/A")
        cold = f"{s.get('cold_start_minutes', 0):.1f} min"
        regr = str(s.get("decision_regression_count", 0))
        reex = str(s.get("re_exploration_count", 0))
        cont = str(s.get("continuity_score", 0))
        task = s.get("task_description", "(no description)")
        # WHAT: Truncate long task descriptions.
        # WHY: Keep the table readable in a terminal.
        if len(task) > 30:
            task = task[:27] + "..."

        print(f"  {num:<3} {date:<12} {cold:<12} {regr:<12} {reex:<12} {cont:<12} {task}")

    print()
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """Show running summary statistics."""
    store = BaselineDataStore(_DEFAULT_DATA_PATH)
    summary = store.get_summary()
    total = summary.get("total_sessions", 0)

    if total == 0:
        print("No sessions recorded yet.")
        return 0

    print("=" * 60)
    print(f"Cortex Phase 3 — Summary ({total} sessions)")
    print("=" * 60)

    cs = summary.get("cold_start", {})
    dr = summary.get("decision_regression", {})
    re = summary.get("re_exploration", {})
    cont = summary.get("continuity_score", {})

    def _show(label: str, stats: dict, unit: str = "") -> None:
        if not stats:
            print(f"  {label}: N/A")
            return
        avg = stats.get("avg", 0)
        mn = stats.get("min", 0)
        mx = stats.get("max", 0)
        u = f" {unit}" if unit else ""
        print(f"  {label}: {avg:.1f}{u} (avg), {mn:.1f}{u} (min), {mx:.1f}{u} (max)")

    print()
    _show("Cold start time", cs, "min")
    _show("Decision regression", dr)
    _show("Re-exploration count", re)
    _show("Continuity score", cont)

    # WHAT: Show progress toward target session count.
    # WHY: Phase 3 requires 5-10 sessions. This helps track progress.
    if total < 5:
        print(f"\n  Progress: {total}/5 sessions (minimum). {5 - total} more needed.")
    elif total < 10:
        print(f"\n  Progress: {total} sessions recorded. Target: 5-10.")
        print("  You can generate a report now or continue collecting data.")
    else:
        print(f"\n  Progress: {total} sessions recorded. Target reached!")
        print("  Generate a report: python -m scripts.testing.run_phase3 report")

    print()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate the filled-in baseline data report."""
    store = BaselineDataStore(_DEFAULT_DATA_PATH)
    sessions = store.get_sessions()

    if not sessions:
        print("No sessions recorded yet. Nothing to report.")
        return 1

    print("=" * 60)
    print("Cortex Phase 3 — Generate Baseline Report")
    print("=" * 60)

    reporter = BaselineReporter(store)
    output_path = Path(args.output) if args.output else _DEFAULT_REPORT_PATH
    reporter.write_report(output_path)

    print(f"\nReport generated with {len(sessions)} sessions.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Reset all recorded session data."""
    store = BaselineDataStore(_DEFAULT_DATA_PATH)
    sessions = store.get_sessions()

    if not sessions:
        print("No sessions recorded. Nothing to reset.")
        return 0

    print(f"This will delete {len(sessions)} recorded sessions.")
    confirm = input("Are you sure? (yes/no): ").strip().lower()

    if confirm != "yes":
        print("Cancelled.")
        return 0

    store.reset()
    print("All session data has been reset.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.testing.run_phase3",
        description="Cortex Phase 3 baseline data collection tool.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # record
    record_parser = subparsers.add_parser("record", help="Record a baseline session")
    record_parser.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Explicit path to a transcript JSONL file (auto-discovers if not provided)",
    )
    record_parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Project directory for transcript auto-discovery (defaults to cortex project root)",
    )

    # list
    subparsers.add_parser("list", help="List all recorded sessions")

    # summary
    subparsers.add_parser("summary", help="Show running summary statistics")

    # report
    report_parser = subparsers.add_parser("report", help="Generate the filled-in baseline report")
    report_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for the report (defaults to docs/testing/BASELINE-DATA-RESULTS.md)",
    )

    # reset
    subparsers.add_parser("reset", help="Reset all recorded session data")

    return parser


def main() -> int:
    """Parse arguments and dispatch to the appropriate command."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "record": cmd_record,
        "list": cmd_list,
        "summary": cmd_summary,
        "report": cmd_report,
        "reset": cmd_reset,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())

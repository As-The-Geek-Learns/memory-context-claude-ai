"""Phase 4 A/B comparison CLI for Cortex Tier 0.

# WHAT: Main entry point for recording, listing, and reporting Cortex-enabled
#       session data during Phase 4 comparison testing.
# WHY: Phase 4 requires running 5-10 dev sessions WITH Cortex enabled and
#       recording 6 metrics per session (4 baseline + briefing_token_count +
#       event_count). This CLI automates the objective metrics and prompts
#       for the subjective ones, then generates A/B comparison reports.

Usage:
    cd /Users/jamescruce/Projects/cortex

    # Record a Cortex-enabled session (after ending a Claude Code session)
    python -m scripts.testing.run_phase4 record

    # Record with explicit transcript and project paths
    python -m scripts.testing.run_phase4 record --transcript /path/to/file.jsonl --project /path/to/project

    # List recorded comparison sessions
    python -m scripts.testing.run_phase4 list

    # Show running summary statistics
    python -m scripts.testing.run_phase4 summary

    # Generate A/B comparison report (loads both baseline + comparison data)
    python -m scripts.testing.run_phase4 report

    # Reset all comparison data (with confirmation)
    python -m scripts.testing.run_phase4 reset
"""

import argparse
import sys
from pathlib import Path

# WHAT: Add src/ to path for direct execution.
# WHY: When run as `python -m scripts.testing.run_phase4`, Python
#       resolves the project root. We need src/ on the path so
#       `import cortex` works without pip install.
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))

from scripts.testing.comparison_recorder import ComparisonDataStore, ComparisonRecorder
from scripts.testing.comparison_reporter import ComparisonReporter
from scripts.testing.session_recorder import BaselineDataStore

# WHAT: Default paths relative to the project root.
# WHY: Keeps all testing data in docs/testing/ alongside other test artifacts.
_DEFAULT_DATA_PATH = _project_root / "docs" / "testing" / "comparison-data.json"
_DEFAULT_BASELINE_PATH = _project_root / "docs" / "testing" / "baseline-data.json"
_DEFAULT_REPORT_PATH = _project_root / "docs" / "testing" / "AB-COMPARISON-RESULTS.md"


def cmd_record(args: argparse.Namespace) -> int:
    """Record a Cortex-enabled comparison session.

    Auto-discovers the most recent transcript or uses --transcript path.
    Extracts objective metrics (including briefing tokens and event count)
    and prompts for subjective ones.
    """
    print("=" * 60)
    print("Cortex Phase 4 — Record Comparison Session")
    print("=" * 60)

    store = ComparisonDataStore(_DEFAULT_DATA_PATH)

    # WHAT: Determine project working directory for transcript discovery
    #       and Cortex metric extraction.
    # WHY: If --project is given, use it. Otherwise use the Cortex project root.
    #       The project directory is needed for briefing file and event store lookup.
    project_cwd = args.project if args.project else str(_project_root)

    transcript_path = Path(args.transcript) if args.transcript else None

    recorder = ComparisonRecorder(store, project_cwd=project_cwd)

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
    """List all recorded comparison sessions."""
    store = ComparisonDataStore(_DEFAULT_DATA_PATH)
    sessions = store.get_sessions()

    if not sessions:
        print("No comparison sessions recorded yet.")
        print("Run: python -m scripts.testing.run_phase4 record")
        return 0

    print("=" * 60)
    print(f"Cortex Phase 4 — Comparison Sessions ({len(sessions)} total)")
    print("=" * 60)

    # WHAT: Extended header with briefing tokens and event count columns.
    # WHY: Phase 4 tracks 2 additional metrics beyond the baseline 4.
    print(
        f"\n  {'#':<3} {'Date':<12} {'Cold Start':<12} {'Regression':<12} "
        f"{'Re-explore':<12} {'Continuity':<12} {'Briefing':<10} {'Events':<8} Task"
    )
    print("  " + "-" * 100)

    for s in sessions:
        num = s.get("session_number", "?")
        date = s.get("date", "N/A")
        cold = f"{s.get('cold_start_minutes', 0):.1f} min"
        regr = str(s.get("decision_regression_count", 0))
        reex = str(s.get("re_exploration_count", 0))
        cont = str(s.get("continuity_score", 0))
        brief = str(s.get("briefing_token_count", 0))
        events = str(s.get("event_count", 0))
        task = s.get("task_description", "(no description)")
        if len(task) > 25:
            task = task[:22] + "..."

        print(f"  {num:<3} {date:<12} {cold:<12} {regr:<12} {reex:<12} {cont:<12} {brief:<10} {events:<8} {task}")

    print()
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """Show running summary statistics for comparison sessions."""
    store = ComparisonDataStore(_DEFAULT_DATA_PATH)
    summary = store.get_summary()
    total = summary.get("total_sessions", 0)

    if total == 0:
        print("No comparison sessions recorded yet.")
        return 0

    print("=" * 60)
    print(f"Cortex Phase 4 — Summary ({total} sessions)")
    print("=" * 60)

    cs = summary.get("cold_start", {})
    dr = summary.get("decision_regression", {})
    re = summary.get("re_exploration", {})
    cont = summary.get("continuity_score", {})
    bt = summary.get("briefing_token_count", {})
    ec = summary.get("event_count", {})

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
    _show("Briefing token count", bt, "tokens")
    _show("Event count", ec)

    if total < 5:
        print(f"\n  Progress: {total}/5 sessions (minimum). {5 - total} more needed.")
    elif total < 10:
        print(f"\n  Progress: {total} sessions recorded. Target: 5-10.")
        print("  You can generate a report now or continue collecting data.")
    else:
        print(f"\n  Progress: {total} sessions recorded. Target reached!")
        print("  Generate a report: python -m scripts.testing.run_phase4 report")

    print()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate the A/B comparison report.

    Loads both baseline (Phase 3) and comparison (Phase 4) data
    to produce a side-by-side analysis with improvement percentages
    and success criteria evaluation.
    """
    baseline_store = BaselineDataStore(_DEFAULT_BASELINE_PATH)
    comparison_store = ComparisonDataStore(_DEFAULT_DATA_PATH)

    baseline_sessions = baseline_store.get_sessions()
    comparison_sessions = comparison_store.get_sessions()

    if not baseline_sessions:
        print("No baseline sessions found. Run Phase 3 first:")
        print("  python -m scripts.testing.run_phase3 record")
        return 1

    if not comparison_sessions:
        print("No comparison sessions recorded yet. Record some sessions first:")
        print("  python -m scripts.testing.run_phase4 record")
        return 1

    print("=" * 60)
    print("Cortex Phase 4 — Generate A/B Comparison Report")
    print("=" * 60)
    print(f"  Baseline sessions: {len(baseline_sessions)}")
    print(f"  Comparison sessions: {len(comparison_sessions)}")

    reporter = ComparisonReporter(baseline_store, comparison_store)
    output_path = Path(args.output) if args.output else _DEFAULT_REPORT_PATH
    reporter.write_report(output_path)

    print(
        f"\nReport generated with {len(comparison_sessions)} comparison sessions vs {len(baseline_sessions)} baseline sessions."
    )
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Reset all recorded comparison session data."""
    store = ComparisonDataStore(_DEFAULT_DATA_PATH)
    sessions = store.get_sessions()

    if not sessions:
        print("No comparison sessions recorded. Nothing to reset.")
        return 0

    print(f"This will delete {len(sessions)} recorded comparison sessions.")
    print("(Baseline data will NOT be affected.)")
    confirm = input("Are you sure? (yes/no): ").strip().lower()

    if confirm != "yes":
        print("Cancelled.")
        return 0

    store.reset()
    print("All comparison session data has been reset.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.testing.run_phase4",
        description="Cortex Phase 4 A/B comparison tool.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # record
    record_parser = subparsers.add_parser("record", help="Record a Cortex-enabled comparison session")
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
        help="Project directory for transcript auto-discovery and Cortex metric extraction",
    )

    # list
    subparsers.add_parser("list", help="List all recorded comparison sessions")

    # summary
    subparsers.add_parser("summary", help="Show running summary statistics")

    # report
    report_parser = subparsers.add_parser("report", help="Generate A/B comparison report")
    report_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for the report (defaults to docs/testing/AB-COMPARISON-RESULTS.md)",
    )

    # reset
    subparsers.add_parser("reset", help="Reset all comparison session data")

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

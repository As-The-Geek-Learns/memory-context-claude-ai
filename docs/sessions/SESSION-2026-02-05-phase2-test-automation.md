# Session Notes: Phase 2 Test Automation

**Date:** 2026-02-05
**Project Phase:** Testing — Phase 2 Automation Scripts

---

## What Was Accomplished

Built a complete test automation suite that replaces the manual Phase 2 testing workflow. Instead of manually launching Claude Code sessions, typing prompts, ending sessions, and checking results, the scripts generate synthetic JSONL transcripts and exercise the entire Cortex pipeline programmatically.

### Key Insight

Cortex hooks consume **JSONL transcript files** and **JSON payloads** — not live Claude Code sessions. By synthesizing both, we can test the full extraction → storage → briefing pipeline without ever launching Claude Code. This turned ~60 minutes of manual testing into a ~3-second automated run.

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/testing/__init__.py` | 2 | Package marker |
| `scripts/testing/test_environment.py` | 138 | Isolated sandbox: temp dirs, git init, config monkeypatching |
| `scripts/testing/transcript_generator.py` | 772 | Builder-pattern JSONL transcript generator with scenario factories |
| `scripts/testing/run_phase2.py` | 436 | Main test runner for all 5 test cases |
| `scripts/testing/results_reporter.py` | 269 | Markdown report generator mirroring MANUAL-TESTING-TEMPLATE.md |
| `docs/testing/AUTOMATED-TESTING-RESULTS.md` | 148 | Generated test results (auto-filled) |
| **Total** | **1,765** | |

---

## Architecture Decisions

### Decision: Synthetic transcripts over live sessions

**Context:** Phase 2 testing required launching real Claude Code sessions, typing specific prompts, waiting for responses, and manually checking results.

**Decision:** Generate synthetic JSONL transcripts that match Claude Code's exact format, then call hook handlers directly via Python API.

**Why:** The Cortex pipeline is deterministic once it has transcript data. The hooks don't validate that the transcript came from a real session — they just parse JSONL. This means we can test extraction accuracy, briefing generation, budget enforcement, and multi-session persistence without Claude Code running at all.

**Tradeoff:** Cannot test whether Claude actually *reads* the generated briefing and improves its responses. That subjective quality check remains manual.

### Decision: Direct API calls over subprocess execution

**Context:** Could either shell out to `cortex stop` (subprocess) or call `handle_stop()` directly (Python API).

**Decision:** Call hook handlers directly with monkeypatched `load_config()` to redirect storage to temp directories.

**Why:** Direct calls are faster, give programmatic access to return values, and allow config isolation without modifying `~/.cortex/`. The monkeypatching pattern matches what the existing pytest suite uses in `tests/test_hooks.py`.

### Decision: Builder pattern for transcript generation

**Context:** Need to produce complex JSONL transcripts with proper UUID chaining, timestamps, and varied content blocks.

**Decision:** `TranscriptBuilder` class with chainable `add_*()` methods and scenario factory functions.

**Why:** Each method appends one JSONL line and handles internal state (parent UUID, auto-incrementing timestamps, tool ID tracking). Factory functions compose these into complete test scenarios. This makes it easy to add new scenarios later without understanding JSONL internals.

---

## Test Results

All 5 test cases passed on first run:

| Test | Result | Details |
|------|--------|---------|
| 2.1 Single Session Flow | PASS | 6 events extracted (FILE_MODIFIED x2, COMMAND_RUN, DECISION_MADE, KNOWLEDGE_ACQUIRED, APPROACH_REJECTED). 509-char briefing generated. |
| 2.2 Multi-Session Continuity | PASS | Events grew 6→10→14 across 3 sessions. Decisions persisted in briefings. Plan appeared in final briefing. |
| 2.3.1 Empty Session | PASS | Stop hook returned 0, 0 events — no crash. |
| 2.3.2 Large Briefing | PASS | 141 events stored. Briefing: 5,475 chars (~1,369 tokens) — well under 3,000 token budget. |
| 2.3.3 Reset Command | PASS | 5 events → reset → 0 events. Return code 0. |

Existing test suite: **331/331 tests still passing** — zero regressions.

---

## How to Run

```bash
cd /Users/jamescruce/Projects/cortex
python -m scripts.testing.run_phase2
```

Output:
- Console summary with pass/fail for each test
- Report written to `docs/testing/AUTOMATED-TESTING-RESULTS.md`

---

## Concepts & Patterns Learned

### Synthetic Input Testing
When your system processes files (not live user interactions), you can build integration tests by synthesizing the input files. The key question is: *does my system validate the source of its inputs, or just the format?* Cortex hooks don't care where the transcript came from — they parse JSONL. So we generate the JSONL ourselves and skip the UI layer entirely.

### Config Monkeypatching for Isolation
The Cortex hooks call `load_config()` internally, which reads from `~/.cortex/`. To isolate tests, we replace the function with a lambda returning a `CortexConfig(cortex_home=temp_dir)`. This is the same pattern the existing pytest suite uses. The try/finally block ensures restoration even if the test crashes.

### Builder Pattern for Complex Test Data
The `TranscriptBuilder` handles three pieces of state that callers shouldn't need to think about: parent UUID chaining (each message links to the previous), monotonically increasing timestamps, and tool ID generation. The caller just says `add_user_message("text")` and the builder handles the JSONL plumbing.

---

## ASTGL Content Moments

1. **[ASTGL CONTENT] Testing pattern — synthetic input files:** When your system's pipeline is file-driven, you can bypass the UI entirely for integration testing. Generate the input files programmatically, run the processing pipeline, and check the output. This pattern works for any system that consumes structured files (logs, transcripts, CSVs, configs).

2. **[ASTGL CONTENT] Monkeypatching vs. dependency injection:** The Cortex codebase uses module-level `load_config()` calls, which makes testing harder than if config were injected as a parameter. The workaround is monkeypatching, but it's fragile — you have to patch every code path. This is a concrete example of why dependency injection matters in testable code design.

3. **[ASTGL CONTENT] Manual testing templates as automation specs:** The MANUAL-TESTING-TEMPLATE.md turned out to be an excellent specification for what the automation scripts needed to do. Each manual step mapped cleanly to a programmatic assertion. Writing the manual test plan first, then automating it, is a solid workflow.

---

## Open Questions / Next Steps

- [ ] **Commit the new scripts** — 5 new files + 1 generated report to add
- [ ] **Phase 3 automation** — Baseline data collection (5-10 sessions without Cortex) could potentially be automated with a similar synthetic approach, though it measures human-perceived quality which is harder to quantify programmatically
- [ ] **Phase 4 automation** — A/B comparison would benefit from automated metric collection, even if the sessions themselves are manual
- [ ] **CI integration** — The Phase 2 automation script could run in GitHub Actions as part of the test suite (it's fast — ~3 seconds)
- [ ] **Real Claude Code validation** — The one thing these scripts cannot test: does Claude actually give better responses when informed by the briefing? That remains a manual, subjective evaluation

---

*Session duration: ~45 minutes*
*Files created: 6 (1,765 lines)*
*Tests: 5/5 automated tests passing, 331/331 existing tests passing*

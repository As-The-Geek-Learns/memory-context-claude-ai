# Session Notes: Tier 0 Implementation — Phases 1 & 2

**Date:** 2026-01-31
**Duration:** ~90 minutes (across two context windows)
**Model:** Claude Opus 4.5
**Project Phase:** Implementation — Tier 0 foundation modules

---

## What Was Accomplished

Built the complete foundation layer of the Cortex event-sourced memory system: the data model, configuration, project identity resolution, and JSON-backed event store. This is Phases 1-2 of the 8-phase implementation plan. All 112 tests pass.

### Files Created (6 source files)

| File | Purpose | Approx Lines |
|------|---------|-------------|
| `src/memory_context_claude_ai/models.py` | Event dataclass, 11-type EventType enum, salience decay, content hash | 175 |
| `src/memory_context_claude_ai/config.py` | CortexConfig dataclass, load/save to JSON, path resolution | 157 |
| `src/memory_context_claude_ai/project.py` | Project hash (SHA-256 of path), git branch/info via subprocess | 113 |
| `src/memory_context_claude_ai/store.py` | EventStore (append, query, briefing projection), HookState | 279 |
| `tests/test_config.py` | 23 tests covering config defaults, serialization, load/save, corruption | 210 |
| `tests/test_project.py` | 17 tests covering hash, git branch, git info, identify_project | 115 |
| `tests/test_store.py` | 38 tests covering append, dedup, queries, briefing, HookState | 310 |
| `tests/test_models.py` | 33 tests covering EventType, salience, decay, serialization, hash | 312 |

### Files Modified (4 files)

| File | What Changed |
|------|-------------|
| `pyproject.toml` | Added `[build-system]`, `[project.scripts]` CLI entry, `[tool.setuptools.packages.find]` |
| `src/memory_context_claude_ai/__init__.py` | Added public API exports (Event, EventType, EventStore, CortexConfig, etc.) |
| `tests/conftest.py` | Replaced placeholder with shared fixtures (tmp_cortex_home, sample_events, event_store, hook_state, tmp_git_repo) |
| `.gitignore` | Added `.claude/rules/cortex-briefing.md`, `*.egg-info/`, `dist/`, `build/` |

### Directories Created

| Directory | Purpose |
|-----------|---------|
| `tests/fixtures/` | Empty — ready for transcript JSONL fixtures in Phase 3 |

---

## Key Decisions Made

### Architecture Decision: Global `~/.cortex/` Storage
- **Chosen over** project-local `.cortex/` directory
- **Why:** Centralized global storage with per-project isolation via 16-character path hashes. Survives git clean, repo recloning, and multiple checkouts. The `~/.cortex/projects/<hash>/` structure keeps all project data in one place.
- **Tradeoff:** Not portable between machines (but that's intentional — memory is machine-contextual)

### Architecture Decision: `pip install -e .` (Editable Install)
- **Chosen over** pipx global install or direct `python3 -m` execution
- **Why:** Standard Python development workflow. Editable mode means code changes take effect immediately without reinstall. Also provides the `cortex` CLI command via `[project.scripts]`.
- **Tradeoff:** Requires a virtual environment, but that's standard practice

### Design Decision: Immutable Event Reinforcement
`reinforce_event()` returns a **new Event** rather than mutating the original. This matches the event-sourcing philosophy (events are facts that happened) and prevents accidental mutation bugs. The EventStore's `mark_accessed()` works at the storage layer instead.

### Design Decision: Content Hash for Deduplication
`content_hash()` uses `sha256(f"{type}:{content}:{session_id}")[:16]` — scoped to type + content + session. This means the same decision text in different sessions is stored separately (which is correct — it was stated again, which is itself a signal). The dedup prevents the Stop hook and PreCompact hook from creating duplicates when they both process the same transcript.

### Design Decision: Briefing-Oriented Queries
`load_for_briefing()` structures events into three sections (immortal, active_plan, recent) with no overlap. This makes the briefing generator's job simpler — it doesn't need to deduplicate across sections. Events are pre-sorted by effective salience for the "recent" bucket.

---

## Concepts & Patterns Applied

### Event Sourcing (Append-Only Store)
The EventStore is append-only by design. Events are never modified after creation (except for access tracking metadata). All "views" of the data (briefings, filtered lists) are projections computed from the raw event stream. This makes the system inherently auditable and recoverable.

### Temporal Decay Function
`effective_salience = salience × (0.995 ^ hours_since_access)`. This exponential decay means:
- After 48 hours: ~78.6% of original salience
- After 7 days: ~43% of original salience
- After 30 days: ~2.2% of original salience

Immortal events (decisions, rejections) bypass decay entirely — they're always at full salience.

### Atomic File Writes
All file writes use the temp-file-then-rename pattern:
```python
tmp_path.write_text(content)
tmp_path.rename(target_path)  # Atomic on POSIX
```
This prevents corruption if the process is killed mid-write. The renamed file either exists completely or doesn't exist at all.

### Defensive Deserialization
Both `Event.from_dict()` and `HookState.load()` use `.get()` with defaults for every field. Corrupted or partial JSON files never crash the system — they silently degrade to defaults. This is critical because hooks must always exit 0.

---

## Bug Fix

### Invalid setuptools Build Backend
**Problem:** `pyproject.toml` had `build-backend = "setuptools.backends._legacy:_Backend"` which doesn't exist in setuptools.
**Fix:** Changed to `build-backend = "setuptools.build_meta"` (the correct standard entry point).
**Root cause:** The original value was likely a hallucination from the initial scaffold generation.

[ASTGL CONTENT] This is a common gotcha with pyproject.toml — the build backend string is easy to get wrong and the error message (`ModuleNotFoundError: No module named 'setuptools.backends'`) doesn't immediately tell you what to fix. The correct value for setuptools is always `"setuptools.build_meta"`.

---

## Test Results

```
============================= 112 passed in 0.83s ==============================

tests/test_config.py    .......................     23 tests
tests/test_models.py    .................................  33 tests
tests/test_project.py   .................      17 tests
tests/test_store.py     ......................................  38 tests
tests/test_placeholder.py .                      1 test (legacy, can remove later)
```

---

## ASTGL Content Moments

1. **[ASTGL CONTENT] Build Backend Gotcha** — `setuptools.build_meta` is the one true build backend string for setuptools. Getting this wrong gives a confusing `ModuleNotFoundError` at install time.

2. **[ASTGL CONTENT] Event Sourcing vs CRUD** — The difference between "store the latest state" (CRUD) and "store every fact that happened" (event sourcing) becomes concrete when you build it. The Event model is immutable; all views are projections. This makes the system naturally auditable — you can always answer "why did the system think X?"

3. **[ASTGL CONTENT] Defensive Defaults Pattern** — When building systems that must never crash (like Claude Code hooks), every `.get()` needs a default, every JSON parse needs a try/except, and every function that could fail returns a safe fallback. The pattern is: `try: parse → except: return defaults`. This is enterprise-grade error handling applied to a developer tool.

4. **[ASTGL CONTENT] Content Hash Scoping** — Deduplication hashes need careful scoping. Hashing just the content would miss the fact that the same text as a "decision" vs. "knowledge" is semantically different. Hashing the ID would prevent all dedup. The sweet spot: `hash(type + content + session_id)`.

---

## What's Next: Phase 3 — Transcript Parser

Phase 3 builds `transcript.py`, the incremental JSONL transcript parser. This is the **highest-risk module** because the exact format of Claude Code's transcript files needs empirical discovery.

### What Phase 3 Will Build
- `transcript.py` — Incremental JSONL reader with byte-offset tracking
- `TranscriptEntry` dataclass
- `extract_tool_calls()` and `extract_text_content()` helpers
- Code block stripping utility (to avoid false keyword matches in code)

### Key Risk
The expected transcript format (from docs + research) is:
```jsonl
{"type": "human", "content": [{"type": "text", "text": "..."}]}
{"type": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "name": "Read", ...}]}
{"type": "human", "content": [{"type": "tool_result", "tool_use_id": "abc", ...}]}
```
But the real format may differ. The parser should be built defensively with `.get()` defaults everywhere.

### Preparation
- Inspect a real Claude Code transcript (from `~/.claude/projects/`) to verify the JSONL structure
- Create fixture files in `tests/fixtures/` with realistic transcript data
- Build the parser to handle format variations gracefully

### Files to Create
- `src/memory_context_claude_ai/transcript.py`
- `tests/test_transcript.py`
- `tests/fixtures/transcript_simple.jsonl`
- `tests/fixtures/transcript_decisions.jsonl`
- `tests/fixtures/transcript_memory_tags.jsonl`
- `tests/fixtures/transcript_mixed.jsonl`

---

## Project Status After This Session

```
Phase 1: Foundation (models, config, project)     ████████████████ DONE
Phase 2: Storage (store, hook state)               ████████████████ DONE
Phase 3: Transcript Parser                         ░░░░░░░░░░░░░░░░ NEXT
Phase 4: Three-Layer Extraction                    ░░░░░░░░░░░░░░░░ Pending
Phase 5: Briefing Generation                       ░░░░░░░░░░░░░░░░ Pending
Phase 6: Hook Handlers                             ░░░░░░░░░░░░░░░░ Pending
Phase 7: CLI + Installer                           ░░░░░░░░░░░░░░░░ Pending
Phase 8: Integration Tests                         ░░░░░░░░░░░░░░░░ Pending
```

**4 source modules built, 112 tests passing, 0 external dependencies.**

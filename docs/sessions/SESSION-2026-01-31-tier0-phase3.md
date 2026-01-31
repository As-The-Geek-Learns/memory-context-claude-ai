# Session Notes: Tier 0 Implementation — Phase 3 (Transcript Parser)

**Date:** 2026-01-31
**Duration:** ~60 minutes (across two context windows)
**Model:** Claude Opus 4.5
**Project Phase:** Implementation — Tier 0, Phase 3 of 8

---

## What Was Accomplished

Built the complete transcript parser module for Claude Code's JSONL transcripts. This is Phase 3 of the 8-phase implementation plan — the bridge between Claude Code's raw session output and Cortex's event extraction pipeline. The parser was built by first inspecting real transcript files to discover the actual format, then building a defensively-coded module with 96 tests. All 208 tests pass (112 existing + 96 new).

### Critical Discovery: Real Format vs. Research Hypothesis

The research phase predicted a transcript format based on the Anthropic API message schema. **The real format is significantly different.** The user wisely mandated inspecting real files before coding.

| Aspect | Research Hypothesis | Actual Format (v2.0.76) |
|--------|-------------------|------------------------|
| User type field | `"human"` | `"user"` |
| Content location | Top-level `content` | Nested under `message.content` |
| User content type | Always array | String for human input, array for tool results |
| Metadata | Minimal | Rich envelope: `parentUuid`, `isSidechain`, `sessionId`, `cwd`, `version`, `gitBranch`, `uuid`, `timestamp` |
| Streaming | Not considered | Multiple JSONL entries per API call sharing same `requestId` |
| Extra record types | None expected | `"summary"` (compaction) and `"file-history-snapshot"` (file tracking) |
| Initial chunks | Not considered | `"(no content)"` placeholder text in first streamed chunk |
| Tool metadata | Not considered | `toolUseResult` field with tool-specific data (stdout/stderr for Bash, filePath for Write, oldTodos/newTodos for TodoWrite) |

[ASTGL CONTENT] **The hypothesis was wrong in 8 out of 8 dimensions.** This is a powerful argument for "inspect real data first" over "build from documentation." The Anthropic API docs describe the *API wire format*, not the *on-disk storage format* that Claude Code uses. Lesson: when building integrations, always look at what actually gets written.

### Files Created (6 files)

| File | Lines | Purpose |
|------|-------|---------|
| `src/memory_context_claude_ai/transcript.py` | 529 | Core transcript parser module |
| `tests/test_transcript.py` | 590 | 96 comprehensive tests across 14 test classes |
| `tests/fixtures/transcript_simple.jsonl` | 7 | Basic conversation: summary, snapshot, user text, tool call, tool result |
| `tests/fixtures/transcript_decisions.jsonl` | 5 | Decision-making: thinking blocks, "Decision: X / Rejected: Y" patterns |
| `tests/fixtures/transcript_memory_tags.jsonl` | 5 | `[MEMORY:]` tag patterns in user and assistant messages, Write tool |
| `tests/fixtures/transcript_mixed.jsonl` | 15 | All record types: summary, snapshots, thinking, Bash, TodoWrite, Read, Task (agent), code blocks |

### Files Modified (1 file)

| File | What Changed |
|------|-------------|
| `src/memory_context_claude_ai/__init__.py` | Added 11 new public API exports for transcript module |

---

## Key Components Built

### TranscriptEntry Dataclass
A defensively-constructed data class representing one JSONL line. Handles all 4 record types (`user`, `assistant`, `summary`, `file-history-snapshot`) with 8 computed properties:

- `is_user`, `is_assistant`, `is_summary`, `is_file_snapshot` — Type checks
- `is_message` — True for user/assistant (not metadata records)
- `has_tool_use`, `has_tool_result`, `has_thinking` — Content inspection

### TranscriptReader (Incremental JSONL Reader)
The core mechanism for the Stop hook. Uses byte-offset tracking (`f.seek()` / `f.tell()`) so each invocation only processes new content since the last read:

```python
reader = TranscriptReader(Path("transcript.jsonl"))
entries = reader.read_new(from_offset=0)       # First read: everything
offset = reader.last_offset                     # Save this to HookState
entries = reader.read_new(from_offset=offset)   # Later: only new lines
```

This integrates with `HookState.last_transcript_position` from Phase 2.

### Extraction Helpers (4 functions)
- `extract_text_content()` — Visible text from all `"text"` blocks, filters `"(no content)"` placeholders
- `extract_thinking_content()` — Extended thinking text from `"thinking"` blocks
- `extract_tool_calls()` → `list[ToolCall]` — Tool invocations with id, name, input
- `extract_tool_results()` → `list[ToolResult]` — Tool results with flattened content, error flag, metadata from `toolUseResult`

### strip_code_blocks()
Regex-based removal of fenced code blocks (``` and ~~~) and inline code spans (`` ` ``) before keyword matching. Order matters: fenced blocks removed first because they may contain backticks internally.

### Path Resolution (2 functions)
- `find_transcript_path()` — Maps `/Users/x/Projects/y` → `~/.claude/projects/-Users-x-Projects-y`
- `find_latest_transcript()` — Finds most recent UUID-named `.jsonl` by mtime, excluding `agent-*.jsonl` sub-conversations

---

## Key Decisions Made

### Design Decision: Content Normalization
**Chosen:** Normalize string user content to `[{"type": "text", "text": content}]` in `parse_entry()`.
**Why:** User messages have `content` as a plain string for human input but as an array for tool results. Normalizing at parse time means all downstream code can always iterate content blocks without type-checking.
**Tradeoff:** Slight memory overhead for the wrapper dict, but simplifies every extraction function.

### Design Decision: Agent File Exclusion
**Chosen:** `find_latest_transcript()` filters out `agent-*.jsonl` files.
**Why:** Agent transcripts are sub-conversations spawned by the Task tool. Their content is already represented in the main session transcript as tool results. Parsing them separately would create duplicate events.
**Tradeoff:** If we ever need to extract fine-grained agent data, we'd need a separate reader path. For now, the main session's tool result contains enough.

### Design Decision: Defensive Parsing Over Strict Validation
**Chosen:** Silent skip of malformed lines, `.get()` defaults everywhere, `try/except json.JSONDecodeError`.
**Why:** Transcript files may have partial writes if Claude Code is interrupted mid-stream. The Stop hook runs after session end — the file might be in any state. The parser must never crash because hooks must always exit 0.
**Tradeoff:** Silent failures make debugging harder, but this is the right call for a background tool that must be invisible.

### Design Decision: Fixture Files Based on Real Format
**Chosen:** Created 4 fixture files with the exact envelope structure discovered from inspection.
**Why:** Tests that use hypothetical formats would pass but not catch real-world parsing bugs. Every fixture line has the full metadata envelope (`parentUuid`, `sessionId`, `gitBranch`, `cwd`, etc.) matching what Claude Code v2.0.76 actually writes.

---

## Concepts & Patterns Applied

### Incremental Parsing via Byte Offsets
The `TranscriptReader` uses `f.seek(offset)` and `f.tell()` for O(1) positioning to the last-read position. This is much more efficient than re-reading the entire file and skipping already-processed lines. For a 1MB transcript with 1000 lines, the Stop hook only processes the new lines since the last run.

[ASTGL CONTENT] **Byte offsets vs. line counts**: Line-based tracking would require reading every line to count them. Byte offsets let you jump directly to the position. The gotcha is that byte offsets can be invalid if the file is truncated or rewritten (e.g., compaction). The defensive approach: if seek fails or returns garbage, fall back to reading from the start.

### Content Block Polymorphism
Claude Code's assistant messages can contain any mix of `text`, `thinking`, `tool_use` blocks in a single `content_blocks` array. Rather than using inheritance or union types, we use duck-typing with dict access: `block.get("type")`. This matches the JSONL format's structure and avoids unnecessary class hierarchies.

### Regex Order Sensitivity in strip_code_blocks
Fenced code blocks must be removed before inline code spans because fenced blocks may contain backticks internally. Removing inline first would break fenced block detection by consuming the opening/closing triple backticks piecemeal.

---

## Test Coverage Summary

```
208 passed in 0.89s

tests/test_config.py      .......................         23 tests
tests/test_models.py      .................................  33 tests
tests/test_project.py     .................               17 tests
tests/test_store.py       ......................................  38 tests
tests/test_transcript.py  ................................  96 tests  ← NEW
tests/test_placeholder.py .                                1 test
```

### Test Classes in test_transcript.py (14 classes, 96 tests)

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestConstants` | 2 | Record type and content type constant values |
| `TestParseEntry` | 13 | All 4 record types + edge cases (empty dict, null parentUuid, missing message, non-dict content, sidechain) |
| `TestTranscriptEntryProperties` | 11 | All 8 computed properties + non-dict block resilience |
| `TestExtractTextContent` | 9 | Text extraction, "(no content)" filtering, summary text, non-dict blocks |
| `TestExtractThinkingContent` | 4 | Single/multiple thinking blocks, empty thinking |
| `TestExtractToolCalls` | 4 | Single/multiple calls, no calls, missing fields |
| `TestExtractToolResults` | 6 | String/array content, error flag, toolUseResult metadata, missing fields |
| `TestStripCodeBlocks` | 8 | Fenced, tilde-fenced, inline, combined, empty, no-code, multiple blocks, single backtick |
| `TestTranscriptReader` | 12 | read_all, read_new, incremental, appended content, nonexistent/empty/malformed files, non-dict JSON, offset past EOF |
| `TestReaderDecisionsFixture` | 4 | Entry count, thinking block, decision text extraction, git branch |
| `TestReaderMemoryTagsFixture` | 5 | Entry count, user/assistant MEMORY tags, Write tool call, Write tool result metadata |
| `TestReaderMixedFixture` | 10 | All record types, Bash/TodoWrite/Read/Task tools, array content flattening, code block stripping, session ID consistency |
| `TestFindTranscriptPath` | 3 | Existing directory, missing directory, path encoding |
| `TestFindLatestTranscript` | 5 | Latest by mtime, agent file exclusion, empty/nonexistent dir, only-agents, single file |

---

## ASTGL Content Moments

1. **[ASTGL CONTENT] Inspect Real Data First** — The research hypothesis about the transcript format was wrong in every dimension. Building from docs would have produced a parser that fails on real files. The user's instinct to mandate inspection saved significant rework. Lesson: when integrating with any tool's internal storage, read the actual files before writing a line of code.

2. **[ASTGL CONTENT] API Format ≠ Storage Format** — The Anthropic API's message format (`{"type": "human", "content": [...]}`) is completely different from Claude Code's on-disk transcript format (`{"type": "user", "message": {"role": "user", "content": "..."}, "parentUuid": "...", ...}`). The tool adds a rich metadata envelope around the API messages. This is common in tools — the wire format and the storage format serve different purposes.

3. **[ASTGL CONTENT] Byte Offset Incremental Parsing** — The `seek()`/`tell()` pattern for incremental file reading is a classic systems technique. It's more efficient than line counting and avoids re-processing already-seen data. The key design question: what happens when the offset is invalid? Answer: defensive fallback to reading from the start.

4. **[ASTGL CONTENT] Streamed Assistant Messages** — Claude Code writes *multiple* JSONL entries per assistant turn (thinking chunk, text chunk, tool_use chunk) all sharing the same `requestId`. This means "one assistant response" might be 1-5 JSONL lines. The `requestId` field is how you group them back together — a pattern the extraction layer (Phase 4) will use.

5. **[ASTGL CONTENT] Content Normalization Simplifies Everything** — When user messages can be either a string or an array, every downstream function needs `if isinstance(content, str):` checks. Normalizing once at parse time (string → `[{"type": "text", "text": content}]`) eliminates this branching from all extraction functions. One-time cost, perpetual simplification.

---

## What's Next: Phase 4 — Three-Layer Extraction

Phase 4 builds the event extraction pipeline that converts parsed transcript entries into Cortex events. This is where the intelligence lives — the system that decides what's worth remembering.

### What Phase 4 Will Build
- `extractors.py` — Three-layer extraction pipeline:
  - **Layer 1 (Structural):** Direct tool observation — Write/Edit → FILE_MODIFIED, Bash → COMMAND_RUN, TodoWrite → PLAN_CREATED/PLAN_STEP_COMPLETED
  - **Layer 2 (Semantic):** Keyword-based text scanning — "Decision:", "Rejected:", "Error:", "Fixed:" → event classification
  - **Layer 3 (Explicit):** `[MEMORY: ...]` tag extraction — user/assistant explicitly flagged memories

### Key Design Questions for Phase 4
- How to handle streamed assistant chunks (multiple entries per response)?
- Confidence scoring for Layer 2 keyword matches (how confident are we in the classification)?
- How to avoid false positives from code blocks (strip_code_blocks is ready)?
- Session-scoped dedup (content_hash from Phase 1 is ready)?

### Preparation Done
- `strip_code_blocks()` is ready for keyword matching
- `extract_tool_calls()` / `extract_tool_results()` feed Layer 1
- `extract_text_content()` / `extract_thinking_content()` feed Layers 2-3
- `content_hash()` from models.py handles deduplication
- All 4 fixture files cover the extraction patterns needed

---

## Project Status After This Session

```
Phase 1: Foundation (models, config, project)      ████████████████ DONE (33+23+17 tests)
Phase 2: Storage (store, hook state)                ████████████████ DONE (38 tests)
Phase 3: Transcript Parser                          ████████████████ DONE (96 tests)
Phase 4: Three-Layer Extraction                     ░░░░░░░░░░░░░░░░ NEXT
Phase 5: Briefing Generation                        ░░░░░░░░░░░░░░░░ Pending
Phase 6: Hook Handlers                              ░░░░░░░░░░░░░░░░ Pending
Phase 7: CLI + Installer                            ░░░░░░░░░░░░░░░░ Pending
Phase 8: Integration Tests                          ░░░░░░░░░░░░░░░░ Pending
```

**5 source modules built, 208 tests passing, 0 external dependencies.**

---

## Next Session Bootstrap Prompt

Copy-paste this to start the next session with full context for Phase 4:

```
Read the project CLAUDE.md, then read these files to understand the project state:

1. docs/sessions/SESSION-2026-01-31-tier0-phase1-2.md (Phases 1-2 context)
2. docs/sessions/SESSION-2026-01-31-tier0-phase3.md (Phase 3 context, includes Phase 4 preview)
3. src/memory_context_claude_ai/__init__.py (public API surface)

Then start building Phase 4: Three-Layer Extraction (extractors.py).

Phase 4 builds the event extraction pipeline that converts parsed
TranscriptEntries into Cortex Events using three layers:
- Layer 1 (Structural): Tool observation — Write→FILE_MODIFIED, Bash→COMMAND_RUN, TodoWrite→PLAN_CREATED
- Layer 2 (Semantic): Keyword scanning — "Decision:", "Rejected:", "Fixed:" → event classification
- Layer 3 (Explicit): [MEMORY:] tag extraction

Key context:
- 208 tests passing across 5 source modules
- transcript.py provides: extract_tool_calls(), extract_text_content(), strip_code_blocks()
- models.py provides: create_event(), EventType (11 types), content_hash() for dedup
- store.py provides: EventStore.append() with built-in dedup
- All test fixtures in tests/fixtures/ cover the extraction patterns needed
```

[ASTGL CONTENT] This bootstrap prompt is a hand-crafted version of exactly what Cortex will automate in Phase 6. The SessionStart hook will generate a `cortex-briefing.md` containing decisions, active plans, and recent context — eliminating the need to manually craft session continuity prompts.

"""Tests for the three-layer event extraction pipeline.

Covers:
- Layer 1 (Structural): Tool call → Event mapping
- Layer 2 (Semantic): Keyword pattern matching
- Layer 3 (Explicit): [MEMORY:] tag extraction
- Pipeline orchestration with deduplication
- Integration tests against fixture JSONL files
"""

from pathlib import Path

from memory_context_claude_ai.extractors import (
    SEMANTIC_PATTERNS,
    _deduplicate,
    _extract_plan_step_completions,
    _format_todos,
    extract_events,
    extract_explicit,
    extract_semantic,
    extract_structural,
)
from memory_context_claude_ai.models import EventType, create_event
from memory_context_claude_ai.transcript import TranscriptEntry, TranscriptReader

# ============================================================
# Helpers: Build TranscriptEntry objects for unit tests
# ============================================================


def _make_assistant_entry(
    content_blocks: list,
    session_id: str = "test-session",
    git_branch: str = "main",
) -> TranscriptEntry:
    """Build an assistant TranscriptEntry with given content blocks."""
    return TranscriptEntry(
        record_type="assistant",
        uuid="test-uuid",
        session_id=session_id,
        git_branch=git_branch,
        role="assistant",
        content_blocks=content_blocks,
        raw={},
    )


def _make_user_entry(
    content_blocks: list,
    session_id: str = "test-session",
    git_branch: str = "main",
    raw: dict | None = None,
) -> TranscriptEntry:
    """Build a user TranscriptEntry with given content blocks."""
    return TranscriptEntry(
        record_type="user",
        uuid="test-uuid",
        session_id=session_id,
        git_branch=git_branch,
        role="user",
        content_blocks=content_blocks,
        raw=raw or {},
    )


def _make_tool_use_block(name: str, tool_input: dict, tool_id: str = "toolu_test") -> dict:
    """Build a tool_use content block."""
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def _make_tool_result_block(
    tool_use_id: str = "toolu_test",
    content: str = "OK",
    is_error: bool = False,
) -> dict:
    """Build a tool_result content block."""
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error}


# ============================================================
# Layer 1: Structural Extraction Tests
# ============================================================


class TestExtractStructural:
    """Tests for Layer 1: tool call → Event mapping."""

    def test_write_tool_creates_file_modified(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Write", {"file_path": "/tmp/test.py", "content": "print('hello')"})]
        )
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.FILE_MODIFIED
        assert "Modified: /tmp/test.py" == events[0].content
        assert events[0].metadata["tool"] == "Write"
        assert events[0].metadata["file_path"] == "/tmp/test.py"
        assert events[0].provenance == "structural"

    def test_edit_tool_creates_file_modified(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Edit", {"file_path": "/tmp/test.py", "old_string": "a", "new_string": "b"})]
        )
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.FILE_MODIFIED
        assert "Modified: /tmp/test.py" == events[0].content
        assert events[0].metadata["tool"] == "Edit"

    def test_bash_tool_creates_command_run(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Bash", {"command": "pytest tests/ -v", "description": "Run tests"})]
        )
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.COMMAND_RUN
        assert events[0].content == "pytest tests/ -v"
        assert events[0].metadata["tool"] == "Bash"
        assert events[0].metadata["description"] == "Run tests"

    def test_read_tool_creates_file_explored(self):
        entry = _make_assistant_entry([_make_tool_use_block("Read", {"file_path": "/tmp/config.py"})])
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.FILE_EXPLORED
        assert "Explored: /tmp/config.py" == events[0].content
        assert events[0].metadata["tool"] == "Read"

    def test_glob_tool_creates_file_explored(self):
        entry = _make_assistant_entry([_make_tool_use_block("Glob", {"pattern": "**/*.py"})])
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.FILE_EXPLORED
        assert "Explored: **/*.py" == events[0].content

    def test_grep_tool_creates_file_explored(self):
        entry = _make_assistant_entry([_make_tool_use_block("Grep", {"pattern": "def main", "file_path": "/tmp/src"})])
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.FILE_EXPLORED

    def test_todowrite_creates_plan_created(self):
        todos = [
            {"content": "Build models", "status": "in_progress", "activeForm": "Building models"},
            {"content": "Build store", "status": "pending", "activeForm": "Building store"},
        ]
        entry = _make_assistant_entry([_make_tool_use_block("TodoWrite", {"todos": todos})])
        events = extract_structural(entry)
        assert len(events) == 1
        assert events[0].type == EventType.PLAN_CREATED
        assert "[ ] Build models" in events[0].content
        assert "[ ] Build store" in events[0].content
        assert events[0].metadata["todo_count"] == 2

    def test_unknown_tool_ignored(self):
        entry = _make_assistant_entry([_make_tool_use_block("WebSearch", {"query": "python async"})])
        events = extract_structural(entry)
        assert len(events) == 0

    def test_non_assistant_entry_ignored(self):
        entry = _make_user_entry([{"type": "text", "text": "Hello"}])
        events = extract_structural(entry)
        # User entries can still produce events from tool results (step completions)
        # but a plain text user entry produces nothing
        assert len(events) == 0

    def test_summary_entry_ignored(self):
        entry = TranscriptEntry(record_type="summary", summary_text="A summary", raw={})
        events = extract_structural(entry)
        assert len(events) == 0

    def test_multiple_tool_calls(self):
        entry = _make_assistant_entry(
            [
                _make_tool_use_block("Read", {"file_path": "/tmp/a.py"}, "toolu_1"),
                _make_tool_use_block("Write", {"file_path": "/tmp/b.py", "content": "x"}, "toolu_2"),
                _make_tool_use_block("Bash", {"command": "ls"}, "toolu_3"),
            ]
        )
        events = extract_structural(entry)
        assert len(events) == 3
        types = {e.type for e in events}
        assert EventType.FILE_EXPLORED in types
        assert EventType.FILE_MODIFIED in types
        assert EventType.COMMAND_RUN in types

    def test_entry_session_id_used(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Bash", {"command": "ls"})],
            session_id="entry-session",
        )
        events = extract_structural(entry, session_id="fallback-session")
        assert events[0].session_id == "entry-session"

    def test_fallback_session_id_used(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Bash", {"command": "ls"})],
            session_id="",
        )
        events = extract_structural(entry, session_id="fallback-session")
        assert events[0].session_id == "fallback-session"

    def test_entry_git_branch_used(self):
        entry = _make_assistant_entry(
            [_make_tool_use_block("Bash", {"command": "ls"})],
            git_branch="feature/test",
        )
        events = extract_structural(entry, git_branch="fallback-branch")
        assert events[0].git_branch == "feature/test"

    def test_project_propagated(self):
        entry = _make_assistant_entry([_make_tool_use_block("Bash", {"command": "ls"})])
        events = extract_structural(entry, project="my-project")
        assert events[0].project == "my-project"


# ============================================================
# Layer 1: Plan Step Completion Tests
# ============================================================


class TestExtractPlanStepCompletions:
    """Tests for PLAN_STEP_COMPLETED detection from TodoWrite results."""

    def test_completed_step_detected(self):
        old_todos = [
            {"content": "Build models", "status": "in_progress"},
            {"content": "Build store", "status": "pending"},
        ]
        new_todos = [
            {"content": "Build models", "status": "completed"},
            {"content": "Build store", "status": "in_progress"},
        ]
        entry = _make_user_entry(
            [_make_tool_result_block(content="Todos updated")],
            raw={"toolUseResult": {"oldTodos": old_todos, "newTodos": new_todos}},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 1
        assert events[0].type == EventType.PLAN_STEP_COMPLETED
        assert events[0].content == "Build models"

    def test_multiple_completions(self):
        old_todos = [
            {"content": "Task A", "status": "in_progress"},
            {"content": "Task B", "status": "in_progress"},
        ]
        new_todos = [
            {"content": "Task A", "status": "completed"},
            {"content": "Task B", "status": "completed"},
        ]
        entry = _make_user_entry(
            [_make_tool_result_block(content="Todos updated")],
            raw={"toolUseResult": {"oldTodos": old_todos, "newTodos": new_todos}},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 2
        contents = {e.content for e in events}
        assert "Task A" in contents
        assert "Task B" in contents

    def test_no_completions_when_empty_old(self):
        """First TodoWrite (empty oldTodos) should not detect completions."""
        entry = _make_user_entry(
            [_make_tool_result_block(content="Todos updated")],
            raw={"toolUseResult": {"oldTodos": [], "newTodos": [{"content": "Task A", "status": "pending"}]}},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 0

    def test_no_completions_when_no_status_change(self):
        old_todos = [{"content": "Task A", "status": "in_progress"}]
        new_todos = [{"content": "Task A", "status": "in_progress"}]
        entry = _make_user_entry(
            [_make_tool_result_block(content="Todos updated")],
            raw={"toolUseResult": {"oldTodos": old_todos, "newTodos": new_todos}},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 0

    def test_already_completed_not_recounted(self):
        old_todos = [
            {"content": "Task A", "status": "completed"},
            {"content": "Task B", "status": "in_progress"},
        ]
        new_todos = [
            {"content": "Task A", "status": "completed"},
            {"content": "Task B", "status": "completed"},
        ]
        entry = _make_user_entry(
            [_make_tool_result_block(content="Todos updated")],
            raw={"toolUseResult": {"oldTodos": old_todos, "newTodos": new_todos}},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 1
        assert events[0].content == "Task B"

    def test_no_tool_use_result_metadata(self):
        entry = _make_user_entry(
            [_make_tool_result_block(content="OK")],
            raw={},
        )
        events = _extract_plan_step_completions(entry, "s1", "proj", "main")
        assert len(events) == 0


# ============================================================
# Layer 2: Semantic Extraction Tests
# ============================================================


class TestExtractSemantic:
    """Tests for Layer 2: keyword pattern → Event mapping."""

    def test_decision_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Decision: Use SQLite for storage"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.DECISION_MADE
        assert events[0].content == "Use SQLite for storage"
        assert events[0].confidence == 0.85
        assert events[0].provenance == "semantic"

    def test_bold_decision(self):
        entry = _make_assistant_entry([{"type": "text", "text": "**Decision: Use SQLite**"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.DECISION_MADE
        assert events[0].content == "Use SQLite"

    def test_rejected_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Rejected: PostgreSQL — overkill for single-user"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.APPROACH_REJECTED
        assert "PostgreSQL" in events[0].content

    def test_bold_rejected(self):
        entry = _make_assistant_entry([{"type": "text", "text": "**Rejected: MongoDB** — too complex"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.APPROACH_REJECTED
        assert "MongoDB" in events[0].content

    def test_fixed_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Fixed: import error in models.py"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.ERROR_RESOLVED
        assert events[0].confidence == 0.75

    def test_error_resolved_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Error resolved: missing dependency"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.ERROR_RESOLVED
        assert events[0].confidence == 0.7

    def test_learned_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Learned: Always use content hashes for dedup"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.KNOWLEDGE_ACQUIRED

    def test_preference_keyword(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Preference: Use double quotes for strings"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].type == EventType.PREFERENCE_NOTED

    def test_multiple_keywords(self):
        entry = _make_assistant_entry(
            [{"type": "text", "text": "**Decision: Use SQLite**\n\n**Rejected: PostgreSQL**\n**Rejected: MongoDB**"}]
        )
        events = extract_semantic(entry)
        assert len(events) == 3
        types = [e.type for e in events]
        assert types.count(EventType.DECISION_MADE) == 1
        assert types.count(EventType.APPROACH_REJECTED) == 2

    def test_code_block_filtered(self):
        """Keywords inside code blocks should not trigger events."""
        entry = _make_assistant_entry(
            [
                {
                    "type": "text",
                    "text": "Here is the code:\n```python\nDecision: this is a variable\n```\n\nNo decisions here.",
                }
            ]
        )
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_inline_code_filtered(self):
        entry = _make_assistant_entry(
            [{"type": "text", "text": "The function `Decision: foo` is not a real decision."}]
        )
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_no_keywords_empty(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Just a regular message with no keywords."}])
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_non_assistant_ignored(self):
        entry = _make_user_entry([{"type": "text", "text": "Decision: I want to use SQLite"}])
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_empty_text_ignored(self):
        entry = _make_assistant_entry([{"type": "text", "text": ""}])
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_only_thinking_blocks_no_events(self):
        """Thinking blocks should not be scanned for keywords."""
        entry = _make_assistant_entry([{"type": "thinking", "thinking": "Decision: internal reasoning about SQLite"}])
        events = extract_semantic(entry)
        assert len(events) == 0

    def test_keyword_with_leading_whitespace(self):
        entry = _make_assistant_entry([{"type": "text", "text": "  Decision: Use SQLite"}])
        events = extract_semantic(entry)
        assert len(events) == 1
        assert events[0].content == "Use SQLite"

    def test_keyword_empty_after_colon_ignored(self):
        entry = _make_assistant_entry([{"type": "text", "text": "Decision:   **"}])
        events = extract_semantic(entry)
        assert len(events) == 0


# ============================================================
# Layer 3: Explicit Extraction Tests
# ============================================================


class TestExtractExplicit:
    """Tests for Layer 3: [MEMORY:] tag extraction."""

    def test_memory_tag_in_user_message(self):
        entry = _make_user_entry([{"type": "text", "text": "[MEMORY: The pipeline must handle CSV and JSON formats.]"}])
        events = extract_explicit(entry)
        assert len(events) == 1
        assert events[0].type == EventType.KNOWLEDGE_ACQUIRED
        assert events[0].content == "The pipeline must handle CSV and JSON formats."
        assert events[0].confidence == 1.0
        assert events[0].provenance == "explicit"
        assert events[0].metadata["source"] == "user"

    def test_memory_tag_in_assistant_message(self):
        entry = _make_assistant_entry(
            [{"type": "text", "text": "[MEMORY: Uses factory pattern for format detection.]"}]
        )
        events = extract_explicit(entry)
        assert len(events) == 1
        assert events[0].metadata["source"] == "assistant"

    def test_multiple_memory_tags(self):
        entry = _make_assistant_entry(
            [{"type": "text", "text": "[MEMORY: First fact.] Some text [MEMORY: Second fact.]"}]
        )
        events = extract_explicit(entry)
        assert len(events) == 2
        contents = {e.content for e in events}
        assert "First fact." in contents
        assert "Second fact." in contents

    def test_no_memory_tags_empty(self):
        entry = _make_assistant_entry([{"type": "text", "text": "No memory tags here."}])
        events = extract_explicit(entry)
        assert len(events) == 0

    def test_non_message_entry_ignored(self):
        entry = TranscriptEntry(
            record_type="summary",
            summary_text="[MEMORY: This should be ignored in summaries.]",
            raw={},
        )
        events = extract_explicit(entry)
        assert len(events) == 0

    def test_memory_tag_with_inline_text(self):
        entry = _make_user_entry(
            [{"type": "text", "text": "Please implement this. [MEMORY: Priority is reliability over speed.] Thanks."}]
        )
        events = extract_explicit(entry)
        assert len(events) == 1
        assert events[0].content == "Priority is reliability over speed."

    def test_memory_tag_session_and_branch(self):
        entry = _make_user_entry(
            [{"type": "text", "text": "[MEMORY: Test fact.]"}],
            session_id="sess-123",
            git_branch="feature/x",
        )
        events = extract_explicit(entry, project="my-proj")
        assert events[0].session_id == "sess-123"
        assert events[0].git_branch == "feature/x"
        assert events[0].project == "my-proj"

    def test_empty_memory_tag_ignored(self):
        entry = _make_user_entry([{"type": "text", "text": "[MEMORY: ]"}])
        events = extract_explicit(entry)
        assert len(events) == 0


# ============================================================
# Format Todos Tests
# ============================================================


class TestFormatTodos:
    """Tests for the _format_todos helper."""

    def test_mixed_statuses(self):
        todos = [
            {"content": "Task A", "status": "completed"},
            {"content": "Task B", "status": "in_progress"},
            {"content": "Task C", "status": "pending"},
        ]
        result = _format_todos(todos)
        assert "[x] Task A" in result
        assert "[ ] Task B" in result
        assert "[ ] Task C" in result

    def test_empty_list(self):
        assert _format_todos([]) == ""

    def test_non_dict_items_skipped(self):
        todos = [{"content": "Valid", "status": "pending"}, "invalid", 42]
        result = _format_todos(todos)
        assert "[ ] Valid" in result
        assert "invalid" not in result

    def test_missing_content_defaults(self):
        todos = [{"status": "pending"}]
        result = _format_todos(todos)
        assert "[ ] " in result


# ============================================================
# Deduplication Tests
# ============================================================


class TestDeduplicate:
    """Tests for the _deduplicate function."""

    def test_identical_events_deduplicated(self):
        e1 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s1")
        result = _deduplicate([e1, e2])
        assert len(result) == 1

    def test_different_content_preserved(self):
        e1 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "Use PostgreSQL", session_id="s1")
        result = _deduplicate([e1, e2])
        assert len(result) == 2

    def test_different_types_preserved(self):
        e1 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s1")
        e2 = create_event(EventType.APPROACH_REJECTED, "Use SQLite", session_id="s1")
        result = _deduplicate([e1, e2])
        assert len(result) == 2

    def test_different_sessions_preserved(self):
        e1 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "Use SQLite", session_id="s2")
        result = _deduplicate([e1, e2])
        assert len(result) == 2

    def test_empty_list(self):
        assert _deduplicate([]) == []

    def test_order_preserved(self):
        e1 = create_event(EventType.DECISION_MADE, "First", session_id="s1")
        e2 = create_event(EventType.DECISION_MADE, "Second", session_id="s1")
        e3 = create_event(EventType.DECISION_MADE, "Third", session_id="s1")
        result = _deduplicate([e1, e2, e3])
        assert [e.content for e in result] == ["First", "Second", "Third"]


# ============================================================
# Semantic Patterns Constant Tests
# ============================================================


class TestSemanticPatterns:
    """Verify the SEMANTIC_PATTERNS constant is well-formed."""

    def test_all_patterns_are_tuples(self):
        for item in SEMANTIC_PATTERNS:
            assert isinstance(item, tuple)
            assert len(item) == 3

    def test_all_patterns_compile(self):
        for pattern, event_type, confidence in SEMANTIC_PATTERNS:
            assert hasattr(pattern, "finditer")
            assert isinstance(event_type, EventType)
            assert 0.0 < confidence <= 1.0


# ============================================================
# Integration: extract_events() Pipeline Tests
# ============================================================


class TestExtractEventsPipeline:
    """Tests for the full extract_events() pipeline."""

    def test_empty_entries(self):
        events = extract_events([])
        assert events == []

    def test_single_bash_entry(self):
        entry = _make_assistant_entry([_make_tool_use_block("Bash", {"command": "ls -la"})])
        events = extract_events([entry])
        assert len(events) == 1
        assert events[0].type == EventType.COMMAND_RUN

    def test_combined_structural_and_semantic(self):
        """Entry with tool call and keyword text should produce events from both layers."""
        entry = _make_assistant_entry(
            [
                {"type": "text", "text": "Decision: Use pytest for testing"},
                _make_tool_use_block("Write", {"file_path": "/tmp/test.py", "content": "import pytest"}),
            ]
        )
        events = extract_events([entry])
        types = {e.type for e in events}
        assert EventType.DECISION_MADE in types
        assert EventType.FILE_MODIFIED in types

    def test_combined_all_three_layers(self):
        """Entry with tool call, keyword, and [MEMORY:] tag."""
        entry = _make_assistant_entry(
            [
                {"type": "text", "text": "Decision: Use pytest\n[MEMORY: pytest is the test framework]"},
                _make_tool_use_block("Write", {"file_path": "/tmp/test.py", "content": "x"}),
            ]
        )
        events = extract_events([entry])
        types = [e.type for e in events]
        assert EventType.DECISION_MADE in types
        assert EventType.KNOWLEDGE_ACQUIRED in types
        assert EventType.FILE_MODIFIED in types

    def test_deduplication_across_entries(self):
        """Duplicate events across entries should be removed."""
        entry1 = _make_assistant_entry(
            [{"type": "text", "text": "Decision: Use SQLite"}],
            session_id="s1",
        )
        entry2 = _make_assistant_entry(
            [{"type": "text", "text": "Decision: Use SQLite"}],
            session_id="s1",
        )
        events = extract_events([entry1, entry2])
        decision_events = [e for e in events if e.type == EventType.DECISION_MADE]
        assert len(decision_events) == 1

    def test_same_content_different_sessions_preserved(self):
        entry1 = _make_assistant_entry(
            [{"type": "text", "text": "Decision: Use SQLite"}],
            session_id="s1",
        )
        entry2 = _make_assistant_entry(
            [{"type": "text", "text": "Decision: Use SQLite"}],
            session_id="s2",
        )
        events = extract_events([entry1, entry2])
        decision_events = [e for e in events if e.type == EventType.DECISION_MADE]
        assert len(decision_events) == 2


# ============================================================
# Integration: Fixture-Based Tests
# ============================================================


class TestFixtureSimple:
    """Integration tests using transcript_simple.jsonl fixture."""

    def test_events_from_simple_fixture(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_simple.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        # Simple fixture has: Bash tool call (ls -la) → COMMAND_RUN
        command_events = [e for e in events if e.type == EventType.COMMAND_RUN]
        assert len(command_events) >= 1
        assert "ls -la" in command_events[0].content

    def test_session_id_propagated(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_simple.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        # All events should have session-001 from the fixture
        for event in events:
            if event.session_id:
                assert event.session_id == "session-001"


class TestFixtureDecisions:
    """Integration tests using transcript_decisions.jsonl fixture."""

    def test_decisions_extracted(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_decisions.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        decisions = [e for e in events if e.type == EventType.DECISION_MADE]
        assert len(decisions) >= 2
        contents = " ".join(e.content for e in decisions)
        assert "SQLite" in contents
        assert "API key" in contents or "config file" in contents

    def test_rejections_extracted(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_decisions.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        rejections = [e for e in events if e.type == EventType.APPROACH_REJECTED]
        assert len(rejections) >= 2
        contents = " ".join(e.content for e in rejections)
        assert "PostgreSQL" in contents

    def test_git_branch_propagated(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_decisions.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        # Decisions fixture uses "feature/auth" branch
        branched = [e for e in events if e.git_branch == "feature/auth"]
        assert len(branched) > 0


class TestFixtureMemoryTags:
    """Integration tests using transcript_memory_tags.jsonl fixture."""

    def test_memory_tags_extracted(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_memory_tags.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        explicit = [e for e in events if e.provenance == "explicit"]
        assert len(explicit) >= 2
        contents = " ".join(e.content for e in explicit)
        assert "CSV" in contents or "pipeline" in contents.lower()

    def test_user_memory_tag_detected(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_memory_tags.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        user_explicit = [e for e in events if e.provenance == "explicit" and e.metadata.get("source") == "user"]
        assert len(user_explicit) >= 1

    def test_assistant_memory_tag_detected(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_memory_tags.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        asst_explicit = [e for e in events if e.provenance == "explicit" and e.metadata.get("source") == "assistant"]
        assert len(asst_explicit) >= 1

    def test_write_tool_file_modified(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_memory_tags.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        file_events = [e for e in events if e.type == EventType.FILE_MODIFIED]
        assert len(file_events) >= 1
        assert "pipeline.py" in file_events[0].content


class TestFixtureMixed:
    """Integration tests using transcript_mixed.jsonl fixture."""

    def test_all_layer_types_present(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        provenances = {e.provenance for e in events}
        assert "structural" in provenances

    def test_bash_command_extracted(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        commands = [e for e in events if e.type == EventType.COMMAND_RUN]
        assert len(commands) >= 1
        assert "pytest" in commands[0].content

    def test_todowrite_plan_created(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        plans = [e for e in events if e.type == EventType.PLAN_CREATED]
        assert len(plans) >= 1
        assert "edge case" in plans[0].content.lower() or "CI" in plans[0].content

    def test_read_tool_file_explored(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        explored = [e for e in events if e.type == EventType.FILE_EXPLORED]
        assert len(explored) >= 1
        assert "pipeline.py" in explored[0].content

    def test_code_blocks_stripped_for_semantic(self, fixtures_dir: Path):
        """Code blocks in the mixed fixture should not produce false keyword matches."""
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        # The mixed fixture has "Decision: this is a variable" inside a code block
        # but NOT as a real keyword. Verify no false positive.
        semantic_decisions = [e for e in events if e.type == EventType.DECISION_MADE and e.provenance == "semantic"]
        for d in semantic_decisions:
            assert "this is a variable" not in d.content

    def test_event_count_reasonable(self, fixtures_dir: Path):
        reader = TranscriptReader(fixtures_dir / "transcript_mixed.jsonl")
        entries = reader.read_all()
        events = extract_events(entries)

        # Mixed fixture has ~15 lines with various tools. Should produce
        # a reasonable number of events (not zero, not hundreds).
        assert 3 <= len(events) <= 30

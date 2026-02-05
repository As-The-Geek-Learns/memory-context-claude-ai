"""Synthetic JSONL transcript builder for Phase 2 test automation.

# WHAT: Generates realistic Claude Code transcript files in JSONL format.
# WHY: Cortex hooks consume transcript files — we can exercise the entire
#       extraction pipeline without a live Claude Code session by creating
#       synthetic transcripts that match the exact format Claude Code produces.

The JSONL format was reverse-engineered from real Claude Code v2.0.76
transcripts and documented in src/cortex/transcript.py. Each line is a
JSON object with specific fields depending on record type:
- summary, file-history-snapshot (metadata records)
- user, assistant (conversation messages)

See tests/fixtures/ for reference examples.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class TranscriptConfig:
    """Configuration for a synthetic transcript."""

    session_id: str = ""
    cwd: str = ""
    git_branch: str = "main"
    version: str = "2.0.76"
    start_time: datetime = field(default_factory=lambda: datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc))


class TranscriptBuilder:
    """Builds a synthetic JSONL transcript for a Claude Code session.

    Usage:
        builder = TranscriptBuilder(TranscriptConfig(
            session_id="test-001",
            cwd="/path/to/project",
        ))
        builder.add_summary("Working on project")
        builder.add_user_message("Create hello.py")
        builder.add_assistant_write_file("/path/hello.py", "print('hi')")
        builder.add_tool_result_success("File created")
        builder.write_to(Path("transcript.jsonl"))
    """

    def __init__(self, config: TranscriptConfig):
        self._config = config
        self._lines: list[dict] = []
        self._msg_counter = 0
        self._tool_counter = 0
        self._parent_uuid: str | None = None
        self._current_time = config.start_time
        self._last_tool_id = ""

    def _next_uuid(self) -> str:
        self._msg_counter += 1
        return f"msg-{self._config.session_id}-{self._msg_counter:04d}"

    def _next_tool_id(self) -> str:
        self._tool_counter += 1
        tid = f"toolu_{self._config.session_id}_{self._tool_counter:04d}"
        self._last_tool_id = tid
        return tid

    def _advance_time(self, seconds: int = 2) -> str:
        self._current_time += timedelta(seconds=seconds)
        return self._current_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _base_entry(self, entry_type: str) -> dict:
        """Base fields shared by user and assistant entries."""
        msg_uuid = self._next_uuid()
        timestamp = self._advance_time()
        entry = {
            "parentUuid": self._parent_uuid,
            "isSidechain": False,
            "userType": "external",
            "cwd": self._config.cwd,
            "sessionId": self._config.session_id,
            "version": self._config.version,
            "gitBranch": self._config.git_branch,
            "type": entry_type,
            "uuid": msg_uuid,
            "timestamp": timestamp,
        }
        self._parent_uuid = msg_uuid
        return entry

    # ------------------------------------------------------------------
    # Metadata records
    # ------------------------------------------------------------------

    def add_summary(self, text: str) -> "TranscriptBuilder":
        """Add a summary metadata line (appears at transcript start)."""
        self._lines.append(
            {
                "type": "summary",
                "summary": text,
                "leafUuid": f"leaf-{self._config.session_id}",
            }
        )
        return self

    def add_file_snapshot(self) -> "TranscriptBuilder":
        """Add a file-history-snapshot metadata line."""
        msg_id = f"snap-{self._config.session_id}"
        self._lines.append(
            {
                "type": "file-history-snapshot",
                "messageId": msg_id,
                "snapshot": {
                    "messageId": msg_id,
                    "trackedFileBackups": {},
                    "timestamp": self._advance_time(0),
                },
                "isSnapshotUpdate": False,
            }
        )
        return self

    # ------------------------------------------------------------------
    # User messages
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> "TranscriptBuilder":
        """Add a user message with plain text content."""
        entry = self._base_entry("user")
        entry["message"] = {"role": "user", "content": text}
        entry["thinkingMetadata"] = {
            "level": "high",
            "disabled": False,
            "triggers": [],
        }
        entry["todos"] = []
        self._lines.append(entry)
        return self

    def add_user_message_with_memory(self, text: str, memory_content: str) -> "TranscriptBuilder":
        """Add a user message containing a [MEMORY:] tag.

        # WHAT: Embeds [MEMORY: ...] in the user's text.
        # WHY: Triggers Layer 3 explicit extraction in extractors.py.
        """
        full_text = f"{text} [MEMORY: {memory_content}]"
        return self.add_user_message(full_text)

    # ------------------------------------------------------------------
    # Tool results (appear as user entries with tool_result content)
    # ------------------------------------------------------------------

    def add_tool_result_success(self, content: str, tool_use_id: str | None = None) -> "TranscriptBuilder":
        """Add a generic successful tool result."""
        tid = tool_use_id or self._last_tool_id
        entry = self._base_entry("user")
        entry["message"] = {
            "role": "user",
            "content": [
                {
                    "tool_use_id": tid,
                    "type": "tool_result",
                    "content": content,
                    "is_error": False,
                }
            ],
        }
        entry["toolUseResult"] = {
            "stdout": content,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        }
        # Remove thinkingMetadata and todos — tool results don't have them
        entry.pop("thinkingMetadata", None)
        entry.pop("todos", None)
        return self

    def add_tool_result_bash(
        self,
        stdout: str,
        stderr: str = "",
        tool_use_id: str | None = None,
    ) -> "TranscriptBuilder":
        """Add a tool result for a Bash command."""
        tid = tool_use_id or self._last_tool_id
        entry = self._base_entry("user")
        entry["message"] = {
            "role": "user",
            "content": [
                {
                    "tool_use_id": tid,
                    "type": "tool_result",
                    "content": stdout,
                    "is_error": bool(stderr and not stdout),
                }
            ],
        }
        entry["toolUseResult"] = {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": False,
            "isImage": False,
        }
        return self

    def add_tool_result_todowrite(
        self,
        old_todos: list[dict],
        new_todos: list[dict],
        tool_use_id: str | None = None,
    ) -> "TranscriptBuilder":
        """Add a tool result for TodoWrite with oldTodos/newTodos metadata.

        # WHAT: Includes the before/after todo state in toolUseResult.
        # WHY: The extractor at extractors.py:158-199 detects PLAN_STEP_COMPLETED
        #       by comparing oldTodos vs newTodos to find newly completed items.
        """
        tid = tool_use_id or self._last_tool_id
        entry = self._base_entry("user")
        entry["message"] = {
            "role": "user",
            "content": [
                {
                    "tool_use_id": tid,
                    "type": "tool_result",
                    "content": "Todos have been modified successfully.",
                }
            ],
        }
        entry["toolUseResult"] = {
            "oldTodos": old_todos,
            "newTodos": new_todos,
        }
        return self

    # ------------------------------------------------------------------
    # Assistant messages
    # ------------------------------------------------------------------

    def _assistant_entry(self, content_blocks: list[dict]) -> dict:
        """Create an assistant entry with the given content blocks."""
        entry = self._base_entry("assistant")
        entry["message"] = {
            "model": "claude-opus-4-5-20251101",
            "id": f"api-{self._config.session_id}-{self._msg_counter}",
            "type": "message",
            "role": "assistant",
            "content": content_blocks,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        entry["requestId"] = f"req-{self._config.session_id}-{self._msg_counter}"
        return entry

    def add_assistant_text(self, text: str) -> "TranscriptBuilder":
        """Add an assistant text response."""
        entry = self._assistant_entry([{"type": "text", "text": text}])
        self._lines.append(entry)
        return self

    def add_assistant_thinking(self, text: str) -> "TranscriptBuilder":
        """Add an assistant thinking block."""
        entry = self._assistant_entry(
            [
                {
                    "type": "thinking",
                    "thinking": text,
                    "signature": f"sig-{self._config.session_id}-{self._msg_counter}",
                }
            ]
        )
        self._lines.append(entry)
        return self

    def add_assistant_decision(self, decision: str, rejected: str | None = None) -> "TranscriptBuilder":
        """Add an assistant response with Decision:/Rejected: keywords.

        # WHAT: Embeds structured keywords in assistant text.
        # WHY: Triggers Layer 2 semantic extraction via SEMANTIC_PATTERNS
        #       in extractors.py:31-38.
        """
        lines = [f"Decision: {decision}"]
        if rejected:
            lines.append(f"Rejected: {rejected}")
        text = "\n\n".join(lines)
        return self.add_assistant_text(text)

    def add_assistant_write_file(self, file_path: str, content: str = "") -> "TranscriptBuilder":
        """Add an assistant Write tool call.

        # WHAT: Creates a Write tool_use content block.
        # WHY: Triggers Layer 1 structural extraction → FILE_MODIFIED event.
        """
        tool_id = self._next_tool_id()
        entry = self._assistant_entry(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Write",
                    "input": {"file_path": file_path, "content": content},
                }
            ]
        )
        self._lines.append(entry)
        return self

    def add_assistant_edit_file(self, file_path: str) -> "TranscriptBuilder":
        """Add an assistant Edit tool call."""
        tool_id = self._next_tool_id()
        entry = self._assistant_entry(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Edit",
                    "input": {
                        "file_path": file_path,
                        "old_string": "placeholder",
                        "new_string": "updated",
                    },
                }
            ]
        )
        self._lines.append(entry)
        return self

    def add_assistant_bash(self, command: str, description: str = "") -> "TranscriptBuilder":
        """Add an assistant Bash tool call.

        # WHAT: Creates a Bash tool_use content block.
        # WHY: Triggers Layer 1 structural extraction → COMMAND_RUN event.
        """
        tool_id = self._next_tool_id()
        entry = self._assistant_entry(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Bash",
                    "input": {"command": command, "description": description},
                }
            ]
        )
        self._lines.append(entry)
        return self

    def add_assistant_read_file(self, file_path: str) -> "TranscriptBuilder":
        """Add an assistant Read tool call (→ FILE_EXPLORED)."""
        tool_id = self._next_tool_id()
        entry = self._assistant_entry(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Read",
                    "input": {"file_path": file_path},
                }
            ]
        )
        self._lines.append(entry)
        return self

    def add_assistant_todowrite(self, todos: list[dict]) -> "TranscriptBuilder":
        """Add an assistant TodoWrite tool call (→ PLAN_CREATED).

        Args:
            todos: List of todo dicts with 'content', 'status', 'activeForm' keys.
        """
        tool_id = self._next_tool_id()
        entry = self._assistant_entry(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "TodoWrite",
                    "input": {"todos": todos},
                }
            ]
        )
        self._lines.append(entry)
        return self

    # ------------------------------------------------------------------
    # Build and output
    # ------------------------------------------------------------------

    def build(self) -> list[str]:
        """Return the transcript as a list of JSON strings (one per line)."""
        return [json.dumps(line, ensure_ascii=False) for line in self._lines]

    def write_to(self, path: Path) -> None:
        """Write the transcript to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for line in self.build():
                f.write(line + "\n")


# ======================================================================
# Scenario Factories
# ======================================================================


def create_single_session_transcript(cwd: str, session_id: str = "phase2-s1") -> TranscriptBuilder:
    """Phase 2.1: Single session — file creation, decision, memory tag, test run.

    Produces events:
    - FILE_MODIFIED x2 (hello.py, test_hello.py)
    - COMMAND_RUN x1 (pytest)
    - DECISION_MADE x1 (Python 3.11+)
    - KNOWLEDGE_ACQUIRED x1 ([MEMORY:] tag)
    """
    config = TranscriptConfig(session_id=session_id, cwd=cwd)
    b = TranscriptBuilder(config)

    b.add_summary("Setting up test project with Python CLI tool")
    b.add_file_snapshot()

    # User asks to create a script
    b.add_user_message("Create a Python script that prints 'Hello, Cortex!'")
    b.add_assistant_thinking("The user wants a simple Python script. I'll create hello.py.")
    b.add_assistant_text("I'll create a Python script for you.")
    hello_path = f"{cwd}/hello.py"
    b.add_assistant_write_file(hello_path, "print('Hello, Cortex!')\n")
    b.add_tool_result_success(f"File created at {hello_path}")

    # User states a decision with [MEMORY:] tag
    b.add_user_message_with_memory(
        "Decision: Use Python 3.11+ for this project.",
        "Use Python 3.11+ for compatibility with modern type hints.",
    )
    b.add_assistant_decision(
        "Use Python 3.11+ for modern type hints and performance improvements",
        "Python 3.9 — lacks modern type hint syntax (X | Y union types)",
    )

    # User asks for a test file
    b.add_user_message("Add a test file for the script")
    test_path = f"{cwd}/test_hello.py"
    b.add_assistant_write_file(
        test_path,
        (
            "import subprocess\n"
            "def test_hello():\n"
            "    result = subprocess.run(['python', 'hello.py'], capture_output=True, text=True)\n"
            "    assert 'Hello, Cortex!' in result.stdout\n"
        ),
    )
    b.add_tool_result_success(f"File created at {test_path}")

    # User asks to run the test
    b.add_user_message("Run the test")
    b.add_assistant_bash("python -m pytest test_hello.py -v", "Run tests")
    b.add_tool_result_bash("test_hello.py::test_hello PASSED\n\n1 passed in 0.12s")
    b.add_assistant_text("The test passed. The script correctly prints 'Hello, Cortex!'.")

    return b


def create_session2_transcript(cwd: str, session_id: str = "phase2-s2") -> TranscriptBuilder:
    """Phase 2.2 Session 2: Reference prior decisions, create logging plan.

    Produces events:
    - PLAN_CREATED x1 (logging plan with 3 steps)
    - FILE_MODIFIED x1 (hello.py edited with logging import)
    - DECISION_MADE x1 (use stdlib logging)
    """
    config = TranscriptConfig(session_id=session_id, cwd=cwd)
    b = TranscriptBuilder(config)

    b.add_summary("Continuing project — adding logging")
    b.add_file_snapshot()

    # User asks about decisions (simulates checking briefing)
    b.add_user_message("What decisions have we made so far?")
    b.add_assistant_text(
        "Based on the project context, we've decided to use Python 3.11+ for compatibility with modern type hints."
    )

    # User creates a plan
    b.add_user_message(
        "Let's add logging to the script. Create a plan with these steps: "
        "1) Add logging import, 2) Add log statements, 3) Test logging output."
    )

    plan_todos = [
        {
            "content": "Add logging import to hello.py",
            "status": "in_progress",
            "activeForm": "Adding logging import",
        },
        {
            "content": "Add log statements to hello.py",
            "status": "pending",
            "activeForm": "Adding log statements",
        },
        {
            "content": "Test logging output",
            "status": "pending",
            "activeForm": "Testing logging output",
        },
    ]
    b.add_assistant_todowrite(plan_todos)
    b.add_tool_result_todowrite(old_todos=[], new_todos=plan_todos)

    # Implement step 1
    b.add_user_message("Implement step 1: add logging import")
    b.add_assistant_decision("Use Python stdlib logging module — no external dependencies needed")
    hello_path = f"{cwd}/hello.py"
    b.add_assistant_edit_file(hello_path)
    b.add_tool_result_success("File edited successfully")

    # Mark step 1 completed
    completed_todos = [
        {
            "content": "Add logging import to hello.py",
            "status": "completed",
            "activeForm": "Adding logging import",
        },
        {
            "content": "Add log statements to hello.py",
            "status": "in_progress",
            "activeForm": "Adding log statements",
        },
        {
            "content": "Test logging output",
            "status": "pending",
            "activeForm": "Testing logging output",
        },
    ]
    b.add_assistant_todowrite(completed_todos)
    b.add_tool_result_todowrite(old_todos=plan_todos, new_todos=completed_todos)

    b.add_assistant_text("Step 1 complete. Logging import added to hello.py.")

    return b


def create_session3_transcript(cwd: str, session_id: str = "phase2-s3") -> TranscriptBuilder:
    """Phase 2.2 Session 3: Continue plan from step 2.

    Produces events:
    - FILE_MODIFIED x1 (hello.py with log statements)
    - COMMAND_RUN x1 (test logging)
    - PLAN_STEP_COMPLETED (step 2 and 3 marked complete)
    """
    config = TranscriptConfig(session_id=session_id, cwd=cwd)
    b = TranscriptBuilder(config)

    b.add_summary("Continuing logging plan — steps 2 and 3")
    b.add_file_snapshot()

    # User asks about plan
    b.add_user_message("What's the current plan?")
    b.add_assistant_text(
        "The current plan has 3 steps:\n"
        "1. [x] Add logging import to hello.py (completed)\n"
        "2. [ ] Add log statements to hello.py\n"
        "3. [ ] Test logging output\n\n"
        "We're on step 2."
    )

    # Continue with step 2
    b.add_user_message("Continue with the plan")
    hello_path = f"{cwd}/hello.py"
    b.add_assistant_edit_file(hello_path)
    b.add_tool_result_success("File edited successfully")

    # Mark step 2 completed
    after_step1 = [
        {
            "content": "Add logging import to hello.py",
            "status": "completed",
            "activeForm": "Adding logging import",
        },
        {
            "content": "Add log statements to hello.py",
            "status": "in_progress",
            "activeForm": "Adding log statements",
        },
        {
            "content": "Test logging output",
            "status": "pending",
            "activeForm": "Testing logging output",
        },
    ]
    after_step2 = [
        {
            "content": "Add logging import to hello.py",
            "status": "completed",
            "activeForm": "Adding logging import",
        },
        {
            "content": "Add log statements to hello.py",
            "status": "completed",
            "activeForm": "Adding log statements",
        },
        {
            "content": "Test logging output",
            "status": "in_progress",
            "activeForm": "Testing logging output",
        },
    ]
    b.add_assistant_todowrite(after_step2)
    b.add_tool_result_todowrite(old_todos=after_step1, new_todos=after_step2)

    # Step 3: run tests
    b.add_assistant_bash(
        "python -m pytest test_hello.py -v --log-cli-level=INFO",
        "Run tests with logging",
    )
    b.add_tool_result_bash("test_hello.py::test_hello PASSED\n\n1 passed in 0.15s")

    # Mark step 3 completed
    all_done = [
        {
            "content": "Add logging import to hello.py",
            "status": "completed",
            "activeForm": "Adding logging import",
        },
        {
            "content": "Add log statements to hello.py",
            "status": "completed",
            "activeForm": "Adding log statements",
        },
        {
            "content": "Test logging output",
            "status": "completed",
            "activeForm": "Testing logging output",
        },
    ]
    b.add_assistant_todowrite(all_done)
    b.add_tool_result_todowrite(old_todos=after_step2, new_todos=all_done)

    b.add_assistant_text("All 3 steps complete. Logging is fully implemented and tested.")

    return b


def create_empty_session_transcript(cwd: str, session_id: str = "phase2-empty") -> TranscriptBuilder:
    """Phase 2.3.1: Empty session — only metadata, no user/assistant messages."""
    config = TranscriptConfig(session_id=session_id, cwd=cwd)
    b = TranscriptBuilder(config)
    b.add_summary("Empty session")
    b.add_file_snapshot()
    return b


def create_large_event_transcripts(cwd: str, count: int = 10) -> list[TranscriptBuilder]:
    """Phase 2.3.2: Generate multiple transcripts for 100+ events.

    Each transcript contains ~10-12 events (file ops, commands, decisions).
    With count=10, this produces ~100-120 events total.

    # WHAT: Creates diverse event types across multiple sessions.
    # WHY: Tests that briefing stays under token budget with large event stores.
    """
    builders = []
    for i in range(count):
        session_id = f"phase2-large-{i:03d}"
        config = TranscriptConfig(session_id=session_id, cwd=cwd)
        b = TranscriptBuilder(config)

        b.add_summary(f"Large event test session {i}")
        b.add_file_snapshot()

        # Generate diverse events
        b.add_user_message(f"Work on feature {i}")

        # File operations (2 events)
        b.add_assistant_write_file(f"{cwd}/src/feature_{i}.py", f"# Feature {i}\n")
        b.add_tool_result_success("File created")
        b.add_assistant_write_file(f"{cwd}/tests/test_feature_{i}.py", f"# Tests for feature {i}\n")
        b.add_tool_result_success("File created")

        # Command (1 event)
        b.add_assistant_bash(f"python -m pytest tests/test_feature_{i}.py -v")
        b.add_tool_result_bash("1 passed in 0.1s")

        # Decision (1 immortal event)
        b.add_assistant_decision(f"Feature {i} uses factory pattern for extensibility")

        # Read (1 event)
        b.add_assistant_read_file(f"{cwd}/src/feature_{i}.py")
        b.add_tool_result_success("# Feature content")

        # Memory tag from user (1 event)
        b.add_user_message_with_memory(
            f"Note about feature {i}",
            f"Feature {i} depends on core module for shared utilities",
        )

        # Plan with completion (2-3 events)
        todos = [
            {
                "content": f"Implement feature {i} core",
                "status": "completed",
                "activeForm": "Implementing core",
            },
            {
                "content": f"Add tests for feature {i}",
                "status": "completed",
                "activeForm": "Adding tests",
            },
        ]
        b.add_assistant_todowrite(todos)
        b.add_tool_result_todowrite(
            old_todos=[
                {
                    "content": f"Implement feature {i} core",
                    "status": "in_progress",
                    "activeForm": "Implementing core",
                },
                {
                    "content": f"Add tests for feature {i}",
                    "status": "pending",
                    "activeForm": "Adding tests",
                },
            ],
            new_todos=todos,
        )

        builders.append(b)

    return builders

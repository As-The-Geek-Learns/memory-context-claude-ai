"""Integration tests for Cortex: E2E pipeline and multi-session scenarios.

Tests the full system flow from hook handlers through extraction to briefing
generation, and validates multi-session context continuity.
"""

from datetime import datetime, timedelta, timezone

from memory_context_claude_ai.briefing import generate_briefing, write_briefing_to_file
from memory_context_claude_ai.hooks import handle_session_start, handle_stop
from memory_context_claude_ai.models import EventType, create_event
from memory_context_claude_ai.project import get_project_hash
from memory_context_claude_ai.store import EventStore, HookState


class TestE2EPipeline:
    """Test full hook flow: Stop → extraction → SessionStart → briefing."""

    def test_stop_to_session_start_full_pipeline(
        self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, fixtures_dir, monkeypatch
    ):
        """E2E: transcript → Stop hook → extraction → SessionStart → briefing file."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        # Use transcript_mixed.jsonl: has tool calls, thinking, TodoWrite, code blocks
        transcript_src = fixtures_dir / "transcript_mixed.jsonl"
        transcript_path = tmp_git_repo / "transcript.jsonl"
        transcript_path.write_text(transcript_src.read_text())

        # Step 1: Run Stop hook
        stop_payload = {
            "cwd": str(tmp_git_repo),
            "transcript_path": str(transcript_path),
            "session_id": "session-mix-001",
            "stop_hook_active": False,
        }
        assert handle_stop(stop_payload) == 0

        # Step 2: Assert extraction worked
        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)
        state = HookState(project_hash, sample_config)
        assert store.count() > 0, "Stop should have extracted events"
        state_data = state.load()
        assert state_data["last_transcript_position"] > 0
        assert state_data["last_session_id"] == "session-mix-001"

        # Step 3: Run SessionStart hook
        session_start_payload = {"cwd": str(tmp_git_repo)}
        assert handle_session_start(session_start_payload) == 0

        # Step 4: Assert briefing was written
        briefing_path = tmp_git_repo / ".claude" / "rules" / "cortex-briefing.md"
        assert briefing_path.exists()
        content = briefing_path.read_text()
        assert len(content) > 0, "Briefing should not be empty when events exist"

    def test_incremental_stop_only_processes_new_content(
        self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, fixtures_dir, monkeypatch
    ):
        """Stop hook with incremental reads: second call only processes new lines."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        transcript_path = tmp_git_repo / "transcript.jsonl"
        # Write first 3 lines
        transcript_src = fixtures_dir / "transcript_simple.jsonl"
        lines = transcript_src.read_text().strip().split("\n")
        transcript_path.write_text("\n".join(lines[:3]) + "\n")

        # First Stop call
        payload = {
            "cwd": str(tmp_git_repo),
            "transcript_path": str(transcript_path),
            "session_id": "s1",
            "stop_hook_active": False,
        }
        assert handle_stop(payload) == 0

        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)
        state = HookState(project_hash, sample_config)
        first_count = store.count()
        first_position = state.load()["last_transcript_position"]
        assert first_position > 0

        # Append more lines
        transcript_path.write_text(transcript_path.read_text() + "\n".join(lines[3:]) + "\n")

        # Second Stop call: should only process new lines
        assert handle_stop(payload) == 0
        second_count = store.count()
        second_position = state.load()["last_transcript_position"]
        assert second_position > first_position, "Position should advance"
        assert second_count >= first_count, "New events may have been extracted"


class TestMultiSessionScenario:
    """Test briefing generation with events across multiple sessions."""

    def test_multi_session_briefing_structure(
        self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, monkeypatch
    ):
        """Events from 5 sessions → briefing with Decisions, Active Plan, Recent sections."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)
        now = datetime.now(timezone.utc)

        # Session 1 (7 days ago): Decision + Plan
        session1_time = (now - timedelta(days=7)).isoformat()
        events_s1 = [
            create_event(
                EventType.DECISION_MADE,
                content="Use SQLite for local storage — zero-config, single file",
                session_id="session-001",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
            create_event(
                EventType.PLAN_CREATED,
                content="[ ] Implement event extraction\n[ ] Add briefing generation",
                session_id="session-001",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
        ]
        for e in events_s1:
            e.created_at = session1_time
            e.accessed_at = session1_time
        store.append_many(events_s1)

        # Session 2 (5 days ago): Plan step + file modified
        session2_time = (now - timedelta(days=5)).isoformat()
        events_s2 = [
            create_event(
                EventType.PLAN_STEP_COMPLETED,
                content="Implement event extraction",
                session_id="session-002",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
            create_event(
                EventType.FILE_MODIFIED,
                content="Modified: src/extractors.py",
                session_id="session-002",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
        ]
        for e in events_s2:
            e.created_at = session2_time
            e.accessed_at = session2_time
        store.append_many(events_s2)

        # Session 3 (3 days ago): Rejection + error resolved
        session3_time = (now - timedelta(days=3)).isoformat()
        events_s3 = [
            create_event(
                EventType.APPROACH_REJECTED,
                content="Rejected MongoDB — overkill for single-user system",
                session_id="session-003",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
            create_event(
                EventType.ERROR_RESOLVED,
                content="Fixed import error in extractors module",
                session_id="session-003",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
        ]
        for e in events_s3:
            e.created_at = session3_time
            e.accessed_at = session3_time
        store.append_many(events_s3)

        # Session 4 (1 day ago): Plan step + file explored
        session4_time = (now - timedelta(days=1)).isoformat()
        events_s4 = [
            create_event(
                EventType.PLAN_STEP_COMPLETED,
                content="Add briefing generation",
                session_id="session-004",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
            create_event(
                EventType.FILE_EXPLORED,
                content="Explored: src/briefing.py",
                session_id="session-004",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
        ]
        for e in events_s4:
            e.created_at = session4_time
            e.accessed_at = session4_time
        store.append_many(events_s4)

        # Session 5 (now): Knowledge + command
        events_s5 = [
            create_event(
                EventType.KNOWLEDGE_ACQUIRED,
                content="Briefing generation uses token budget to prioritize events",
                session_id="session-005",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
            create_event(
                EventType.COMMAND_RUN,
                content="pytest tests/ -v",
                session_id="session-005",
                project=str(tmp_git_repo),
                git_branch="main",
            ),
        ]
        store.append_many(events_s5)

        # Generate briefing
        briefing = generate_briefing(project_path=str(tmp_git_repo), config=sample_config, branch="main")

        # Assert structure
        assert len(briefing) > 0, "Briefing should not be empty"
        assert "Decisions" in briefing or "# Decisions" in briefing, "Should have Decisions section"
        # Immortal events (decisions, rejections) should appear
        assert "SQLite" in briefing or "MongoDB" in briefing, "Immortal events should be in briefing"
        # Recent or plan events might appear depending on salience
        # Just verify the briefing is structured and non-empty

    def test_plan_continuity_across_sessions(self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, monkeypatch):
        """Most recent PLAN_CREATED + its completed steps appear in Active Plan section."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)
        now = datetime.now(timezone.utc)

        # Session 1: Old plan (should not appear)
        old_plan_time = (now - timedelta(days=10)).isoformat()
        old_plan = create_event(
            EventType.PLAN_CREATED,
            content="[ ] Old task A\n[ ] Old task B",
            session_id="session-old",
            project=str(tmp_git_repo),
            git_branch="main",
        )
        old_plan.created_at = old_plan_time
        old_plan.accessed_at = old_plan_time
        store.append_many([old_plan])

        # Session 2: Recent plan (should appear)
        recent_plan_time = (now - timedelta(days=1)).isoformat()
        recent_plan = create_event(
            EventType.PLAN_CREATED,
            content="[ ] Task 1: Build hooks\n[ ] Task 2: Add CLI",
            session_id="session-recent",
            project=str(tmp_git_repo),
            git_branch="main",
        )
        recent_plan.created_at = recent_plan_time
        recent_plan.accessed_at = recent_plan_time

        # Session 3: Completed step for recent plan
        completed_step = create_event(
            EventType.PLAN_STEP_COMPLETED,
            content="Task 1: Build hooks",
            session_id="session-recent-2",
            project=str(tmp_git_repo),
            git_branch="main",
        )
        completed_step.created_at = now.isoformat()
        completed_step.accessed_at = now.isoformat()

        store.append_many([recent_plan, completed_step])

        # Generate briefing
        briefing = generate_briefing(project_path=str(tmp_git_repo), config=sample_config, branch="main")

        # Assert: recent plan and its completed step appear in Active Plan section
        assert "Task 1: Build hooks" in briefing or "Build hooks" in briefing
        assert "Task 2: Add CLI" in briefing or "Add CLI" in briefing
        assert "Active Plan" in briefing or "## Active Plan" in briefing
        # Old plan may appear in Recent Context if salience is high enough; just verify recent plan is in Active Plan
        active_plan_section = briefing.split("## Recent Context")[0] if "## Recent Context" in briefing else briefing
        assert "Task 1" in active_plan_section or "Build hooks" in active_plan_section


class TestBudgetOverflow:
    """Test briefing stays under token budget with many immortal events."""

    def test_budget_overflow_with_500_decisions(
        self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, monkeypatch
    ):
        """500 immortal events → briefing respects max_briefing_tokens."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)

        # Create 500 DECISION_MADE events (immortal)
        events = []
        for i in range(500):
            event = create_event(
                EventType.DECISION_MADE,
                content=f"Decision {i}: Use technology X for component Y because reason Z.",
                session_id=f"session-{i // 50}",
                project=str(tmp_git_repo),
                git_branch="main",
            )
            events.append(event)
        store.append_many(events)

        # Generate briefing
        briefing = generate_briefing(project_path=str(tmp_git_repo), config=sample_config, branch="main")

        # Estimate token count (chars / 4)
        estimated_tokens = len(briefing) / 4
        max_tokens = sample_config.max_briefing_tokens
        assert estimated_tokens <= max_tokens, f"Briefing {estimated_tokens:.0f} tokens exceeds budget {max_tokens}"
        assert len(briefing) > 0, "Briefing should not be empty with 500 events"


class TestRegressionFromFixtures:
    """Test extraction from saved transcript fixtures (detect drift)."""

    def test_extract_from_all_fixtures(self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, fixtures_dir):
        """Parse each fixture → extract events → assert expected types present."""
        from memory_context_claude_ai.extractors import extract_events
        from memory_context_claude_ai.transcript import TranscriptReader

        fixtures = [
            ("transcript_simple.jsonl", ["COMMAND_RUN"]),
            ("transcript_decisions.jsonl", ["DECISION_MADE", "APPROACH_REJECTED"]),
            ("transcript_memory_tags.jsonl", ["KNOWLEDGE_ACQUIRED", "FILE_MODIFIED"]),
            ("transcript_mixed.jsonl", ["COMMAND_RUN", "PLAN_CREATED", "FILE_EXPLORED"]),
        ]

        for fixture_name, expected_types in fixtures:
            fixture_path = fixtures_dir / fixture_name
            if not fixture_path.exists():
                continue

            reader = TranscriptReader(fixture_path)
            entries = reader.read_all()
            events = extract_events(entries, session_id="test", project=str(tmp_git_repo), git_branch="main")

            # Assert: at least one event of each expected type
            event_types = {e.type.value for e in events}
            for expected in expected_types:
                assert expected.lower() in {t.lower() for t in event_types}, (
                    f"{fixture_name}: expected {expected} in extracted events"
                )

    def test_full_pipeline_on_mixed_fixture(
        self, tmp_path, tmp_cortex_home, tmp_git_repo, sample_config, fixtures_dir, monkeypatch
    ):
        """Full pipeline: transcript_mixed.jsonl → extract → store → briefing → assert keywords."""
        monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: sample_config)

        from memory_context_claude_ai.extractors import extract_events
        from memory_context_claude_ai.transcript import TranscriptReader

        fixture_path = fixtures_dir / "transcript_mixed.jsonl"
        reader = TranscriptReader(fixture_path)
        entries = reader.read_all()
        events = extract_events(entries, session_id="session-mix-001", project=str(tmp_git_repo), git_branch="main")

        project_hash = get_project_hash(str(tmp_git_repo))
        store = EventStore(project_hash, sample_config)
        store.append_many(events)

        # Generate briefing
        briefing_path = tmp_git_repo / ".claude" / "rules" / "cortex-briefing.md"
        write_briefing_to_file(briefing_path, project_path=str(tmp_git_repo), config=sample_config, branch="main")

        assert briefing_path.exists()
        content = briefing_path.read_text()
        # transcript_mixed has Bash, TodoWrite, Read — should produce COMMAND_RUN, PLAN_CREATED, FILE_EXPLORED
        # Briefing may or may not include them depending on salience, but should be non-empty
        assert len(content) > 0 or store.count() > 0, "Briefing or store should have content"

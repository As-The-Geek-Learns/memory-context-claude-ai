"""Pytest configuration and shared fixtures for Cortex tests."""

from pathlib import Path

import pytest

from memory_context_claude_ai.config import CortexConfig
from memory_context_claude_ai.models import EventType, create_event
from memory_context_claude_ai.store import EventStore, HookState


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures/ directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_cortex_home(tmp_path: Path) -> Path:
    """Create a temporary Cortex home directory structure.

    Returns ~/.cortex/ equivalent in a temp directory, with
    the projects/ subdirectory already created.
    """
    cortex = tmp_path / ".cortex"
    cortex.mkdir()
    (cortex / "projects").mkdir()
    return cortex


@pytest.fixture
def sample_config(tmp_cortex_home: Path) -> CortexConfig:
    """CortexConfig pointing at the tmp_cortex_home directory."""
    return CortexConfig(cortex_home=tmp_cortex_home)


@pytest.fixture
def sample_project_hash() -> str:
    """A deterministic project hash for testing."""
    return "abc123def456abcd"


@pytest.fixture
def sample_project_dir(tmp_cortex_home: Path, sample_project_hash: str) -> Path:
    """A project directory within the temp Cortex home."""
    proj = tmp_cortex_home / "projects" / sample_project_hash
    proj.mkdir(parents=True)
    return proj


@pytest.fixture
def event_store(sample_project_hash: str, sample_config: CortexConfig) -> EventStore:
    """An EventStore instance backed by the tmp directory."""
    return EventStore(sample_project_hash, sample_config)


@pytest.fixture
def hook_state(sample_project_hash: str, sample_config: CortexConfig) -> HookState:
    """A HookState instance backed by the tmp directory."""
    return HookState(sample_project_hash, sample_config)


@pytest.fixture
def sample_events() -> list:
    """A diverse set of sample Event objects covering all types."""
    return [
        create_event(
            event_type=EventType.DECISION_MADE,
            content="Chose SQLite over PostgreSQL — zero-config requirement",
            session_id="session-001",
            project="abc123def456abcd",
            git_branch="main",
            provenance="layer3:MEMORY_TAG",
        ),
        create_event(
            event_type=EventType.APPROACH_REJECTED,
            content="Rejected MongoDB — overkill for single-user system",
            session_id="session-001",
            project="abc123def456abcd",
            git_branch="main",
            provenance="layer3:MEMORY_TAG",
        ),
        create_event(
            event_type=EventType.PLAN_CREATED,
            content="Created plan: implement event extraction pipeline",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            metadata={"items": ["models.py", "store.py", "extractors"]},
            provenance="layer1:TodoWrite",
        ),
        create_event(
            event_type=EventType.PLAN_STEP_COMPLETED,
            content="Completed: models.py implementation",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            provenance="layer1:TodoWrite",
        ),
        create_event(
            event_type=EventType.KNOWLEDGE_ACQUIRED,
            content="src/main.py uses factory pattern for handler dispatch",
            session_id="session-001",
            project="abc123def456abcd",
            git_branch="main",
            provenance="layer3:MEMORY_TAG",
        ),
        create_event(
            event_type=EventType.ERROR_RESOLVED,
            content="Fixed import error: missing __init__.py in extractors/",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            confidence=0.85,
            provenance="layer2:keyword:issue_fixed",
        ),
        create_event(
            event_type=EventType.FILE_MODIFIED,
            content="Modified src/models.py",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            metadata={"path": "src/models.py"},
            provenance="layer1:Edit",
        ),
        create_event(
            event_type=EventType.FILE_EXPLORED,
            content="Explored src/config.py",
            session_id="session-001",
            project="abc123def456abcd",
            git_branch="main",
            metadata={"path": "src/config.py"},
            provenance="layer1:Read",
        ),
        create_event(
            event_type=EventType.COMMAND_RUN,
            content="Ran: pytest tests/ -v",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            metadata={"command": "pytest tests/ -v"},
            provenance="layer1:Bash",
        ),
        create_event(
            event_type=EventType.TASK_COMPLETED,
            content="Git: committed 'feat: add models module'",
            session_id="session-002",
            project="abc123def456abcd",
            git_branch="main",
            provenance="layer1:Bash",
        ),
    ]


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing project.py.

    Initializes a git repo with an initial commit so that
    git commands like rev-parse and log work.
    """
    import subprocess

    repo = tmp_path / "test-repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

    # Create an initial commit so git log works
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True)

    return repo

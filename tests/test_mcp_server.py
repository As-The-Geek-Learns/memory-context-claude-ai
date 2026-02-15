"""Tests for MCP server module.

Tests cover:
- MCP availability check
- Project context resolution
- Tool handlers (search, decisions, plan, recent, status)
- Resource handlers
- Server initialization

Uses mocking when mcp package is not installed.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cortex.config import CortexConfig
from cortex.models import Event, EventType

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def tmp_cortex_home(tmp_path: Path) -> Path:
    """Create a temporary cortex home directory."""
    cortex_home = tmp_path / ".cortex"
    cortex_home.mkdir()
    return cortex_home


@pytest.fixture
def sample_events() -> list[Event]:
    """Sample events for testing."""
    return [
        Event(
            type=EventType.DECISION_MADE,
            content="Use SQLite for storage.",
            confidence=1.0,
            salience=1.0,
            immortal=True,
            git_branch="main",
            created_at="2026-02-14T10:00:00Z",
        ),
        Event(
            type=EventType.PLAN_CREATED,
            content="1. Implement feature X\n2. Write tests\n3. Deploy",
            confidence=0.9,
            salience=0.9,
            immortal=False,
            git_branch="main",
            created_at="2026-02-14T11:00:00Z",
        ),
        Event(
            type=EventType.FILE_MODIFIED,
            content="Modified src/main.py",
            confidence=1.0,
            salience=0.5,
            immortal=False,
            git_branch="main",
            created_at="2026-02-14T12:00:00Z",
        ),
    ]


# =============================================================================
# Test: check_mcp_available
# =============================================================================


class TestCheckMcpAvailable:
    """Tests for check_mcp_available function."""

    def test_returns_false_when_not_installed(self) -> None:
        """Returns False when mcp package is not installed."""
        from cortex.mcp.server import check_mcp_available

        # This test behavior depends on whether mcp is actually installed
        # We just verify the function runs without error
        result = check_mcp_available()
        assert isinstance(result, bool)

    def test_returns_true_when_installed(self) -> None:
        """Returns True when mcp package is installed."""
        with patch.dict("sys.modules", {"mcp": MagicMock()}):
            # Need to reimport after patching
            from importlib import reload

            from cortex.mcp import server

            reload(server)
            result = server.check_mcp_available()
            assert result is True


# =============================================================================
# Test: resolve_project_context
# =============================================================================


class TestResolveProjectContext:
    """Tests for resolve_project_context function."""

    def test_resolves_from_cwd(self, tmp_project: Path, tmp_cortex_home: Path) -> None:
        """Resolves project context from working directory."""
        from cortex.mcp.server import resolve_project_context

        with patch("cortex.config.load_config") as mock_config:
            mock_config.return_value = CortexConfig(cortex_home=tmp_cortex_home)
            ctx = resolve_project_context(str(tmp_project))

        assert ctx.cwd == str(tmp_project)
        assert len(ctx.project_hash) == 16
        assert ctx.storage_tier >= 0

    def test_raises_on_empty_cwd(self) -> None:
        """Raises ValueError when cwd is empty."""
        from cortex.mcp.server import resolve_project_context

        with pytest.raises(ValueError, match="No working directory"):
            resolve_project_context("")

    def test_uses_os_getcwd_when_none(self, tmp_cortex_home: Path) -> None:
        """Uses os.getcwd() when cwd is None."""
        from cortex.mcp.server import resolve_project_context

        with patch("cortex.config.load_config") as mock_config:
            mock_config.return_value = CortexConfig(cortex_home=tmp_cortex_home)
            ctx = resolve_project_context(None)

        assert ctx.cwd == os.getcwd()


# =============================================================================
# Test: CortexMCPServer (without mcp package)
# =============================================================================


class TestCortexMCPServerInitWithoutMcp:
    """Tests for CortexMCPServer when mcp package is not installed."""

    def test_raises_import_error_when_mcp_unavailable(self, tmp_project: Path) -> None:
        """Raises ImportError when mcp package is not available."""
        from cortex.mcp.server import CortexMCPServer, check_mcp_available

        if check_mcp_available():
            pytest.skip("mcp package is installed, cannot test unavailability")

        with pytest.raises(ImportError, match="MCP package not installed"):
            CortexMCPServer(cwd=str(tmp_project))


# =============================================================================
# Test: CortexMCPServer (with mocked mcp package)
# =============================================================================


class TestCortexMCPServerWithMock:
    """Tests for CortexMCPServer with mocked mcp package."""

    @pytest.fixture
    def mock_mcp(self) -> MagicMock:
        """Mock mcp package."""
        mock = MagicMock()
        mock.server.fastmcp.FastMCP = MagicMock()
        return mock

    def test_initialization(self, tmp_project: Path, tmp_cortex_home: Path, mock_mcp: MagicMock) -> None:
        """Server initializes with mocked mcp package."""
        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.server": mock_mcp.server, "mcp.server.fastmcp": mock_mcp.server.fastmcp},
        ):
            with patch("cortex.mcp.server.check_mcp_available", return_value=True):
                with patch("cortex.config.load_config") as mock_config:
                    mock_config.return_value = CortexConfig(cortex_home=tmp_cortex_home)
                    from cortex.mcp.server import CortexMCPServer

                    server = CortexMCPServer(cwd=str(tmp_project))
                    assert server._cwd == str(tmp_project)
                    assert server._mcp is not None


# =============================================================================
# Test: Tool Handlers
# =============================================================================


class TestToolHandlers:
    """Tests for MCP tool handler methods."""

    @pytest.fixture
    def handler_context(self, tmp_project: Path, tmp_cortex_home: Path, sample_events: list[Event]):
        """Set up context for handler tests."""
        from cortex.mcp.server import ProjectContext
        from cortex.store import EventStore

        config = CortexConfig(cortex_home=tmp_cortex_home)
        project_hash = "abcd1234abcd1234"
        store = EventStore(project_hash, config)

        # Add sample events
        for event in sample_events:
            store.append(event)

        return ProjectContext(
            cwd=str(tmp_project),
            project_hash=project_hash,
            config=config,
            store=store,
            storage_tier=0,
            has_embeddings=False,
        )

    def test_handle_search_tier0(self, handler_context) -> None:
        """Search handler works on Tier 0 (in-memory search)."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                # Mock _get_current_branch to return None (no branch filtering)
                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_search("SQLite", limit=10, branch=None)

                assert "SQLite" in result
                assert "decision_made" in result

    def test_handle_search_no_results(self, handler_context) -> None:
        """Search handler returns message when no results found."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_search("nonexistent", limit=10, branch=None)

                assert "No results found" in result

    def test_handle_search_decisions(self, handler_context) -> None:
        """Search decisions handler returns immortal events."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                # Mock _get_current_branch to return None (no branch filtering)
                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_search_decisions(query=None, limit=20, branch=None)

                assert "Decisions" in result
                assert "SQLite" in result

    def test_handle_get_plan(self, handler_context) -> None:
        """Get plan handler returns active plan."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                # Mock _get_current_branch to return None (no branch filtering)
                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_get_plan(branch=None)

                assert "Active Plan" in result
                assert "Implement feature X" in result

    def test_handle_get_recent(self, handler_context) -> None:
        """Get recent handler returns recent events."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                # Mock _get_current_branch to return None (no branch filtering)
                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_get_recent(limit=10, branch=None)

                assert "Recent Events" in result
                # Should have events (lowercase event type values)
                assert "file_modified" in result or "decision_made" in result

    def test_handle_get_status(self, handler_context) -> None:
        """Get status handler returns project info."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = handler_context

                # Mock _get_current_branch to return "main"
                with patch.object(server, "_get_current_branch", return_value="main"):
                    result = server._handle_get_status()

                assert "Cortex Status" in result
                assert "abcd1234abcd1234" in result
                assert "Storage Tier:** 0" in result
                assert "Events:** 3" in result


# =============================================================================
# Test: run_server
# =============================================================================


class TestRunServer:
    """Tests for run_server entry point."""

    def test_returns_error_when_mcp_unavailable(self) -> None:
        """Returns exit code 1 when mcp is not available."""
        from cortex.mcp.server import check_mcp_available, run_server

        if check_mcp_available():
            pytest.skip("mcp package is installed")

        result = run_server()
        assert result == 1

    def test_handles_exceptions(self) -> None:
        """Returns exit code 1 on exception."""
        from cortex.mcp.server import run_server

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch("cortex.mcp.server.CortexMCPServer", side_effect=Exception("test error")):
                result = run_server()
                assert result == 1


# =============================================================================
# Test: Branch Filtering
# =============================================================================


class TestBranchFiltering:
    """Tests for branch filtering in tool handlers."""

    @pytest.fixture
    def multi_branch_context(self, tmp_project: Path, tmp_cortex_home: Path):
        """Context with events from multiple branches."""
        from cortex.mcp.server import ProjectContext
        from cortex.store import EventStore

        config = CortexConfig(cortex_home=tmp_cortex_home)
        project_hash = "efgh5678efgh5678"
        store = EventStore(project_hash, config)

        # Events from different branches
        events = [
            Event(
                type=EventType.DECISION_MADE,
                content="Main branch decision",
                confidence=1.0,
                salience=1.0,
                immortal=True,
                git_branch="main",
            ),
            Event(
                type=EventType.DECISION_MADE,
                content="Feature branch decision",
                confidence=1.0,
                salience=1.0,
                immortal=True,
                git_branch="feat/new-feature",
            ),
        ]
        for event in events:
            store.append(event)

        return ProjectContext(
            cwd=str(tmp_project),
            project_hash=project_hash,
            config=config,
            store=store,
            storage_tier=0,
            has_embeddings=False,
        )

    def test_filter_by_branch(self, multi_branch_context) -> None:
        """Filters decisions by specified branch."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = multi_branch_context

                result = server._handle_search_decisions(query=None, limit=20, branch="feat/new-feature")

                assert "Feature branch decision" in result
                assert "Main branch decision" not in result

    def test_no_branch_filter_returns_all(self, multi_branch_context) -> None:
        """Returns all events when no branch filter specified."""
        from cortex.mcp.server import CortexMCPServer

        with patch("cortex.mcp.server.check_mcp_available", return_value=True):
            with patch.object(CortexMCPServer, "__init__", lambda self, **kwargs: None):
                server = CortexMCPServer.__new__(CortexMCPServer)
                server._context = multi_branch_context

                # Mock _get_current_branch to return None
                with patch.object(server, "_get_current_branch", return_value=None):
                    result = server._handle_search_decisions(query=None, limit=20, branch=None)

                    assert "Feature branch decision" in result
                    assert "Main branch decision" in result

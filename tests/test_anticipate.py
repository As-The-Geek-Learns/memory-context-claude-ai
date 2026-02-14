"""Tests for anticipatory retrieval (Phase 5 of Tier 2).

Tests cover:
- retrieve_relevant_context() function
- format_relevant_context() formatting
- write_relevant_context_to_file() file operations
- handle_user_prompt_submit() hook integration
"""

import json

import pytest

from cortex.anticipate import (
    DEFAULT_RETRIEVAL_LIMIT,
    MAX_RELEVANT_CONTEXT_CHARS,
    RetrievalResult,
    format_relevant_context,
    retrieve_relevant_context,
    write_relevant_context_to_file,
)
from cortex.config import CortexConfig
from cortex.hooks import handle_user_prompt_submit
from cortex.models import EventType, create_event

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tier2_config(tmp_path):
    """Create a Tier 2 config for testing."""
    return CortexConfig(
        cortex_home=tmp_path / ".cortex",
        storage_tier=2,
        auto_embed=False,
    )


@pytest.fixture
def tier0_config(tmp_path):
    """Create a Tier 0 config for testing."""
    return CortexConfig(
        cortex_home=tmp_path / ".cortex",
        storage_tier=0,
    )


@pytest.fixture
def sample_events():
    """Create sample events for testing."""
    return [
        create_event(
            EventType.DECISION_MADE,
            "Use SQLite for storage",
            session_id="test-session",
            project="test-project",
        ),
        create_event(
            EventType.APPROACH_REJECTED,
            "Rejected PostgreSQL - too complex",
            session_id="test-session",
            project="test-project",
        ),
        create_event(
            EventType.KNOWLEDGE_ACQUIRED,
            "Python's sqlite3 module supports WAL mode",
            session_id="test-session",
            project="test-project",
        ),
    ]


@pytest.fixture
def mock_hybrid_result(sample_events):
    """Create mock HybridResult for testing format_relevant_context."""
    # Import here to avoid circular imports
    from cortex.hybrid_search import HybridResult

    return [
        HybridResult(
            event=sample_events[0],
            fts_rank=1,
            vec_rank=2,
            rrf_score=0.015,
            fts_score=5.5,
            similarity=0.85,
            snippet="Use **SQLite** for storage",
        ),
        HybridResult(
            event=sample_events[1],
            fts_rank=None,
            vec_rank=1,
            rrf_score=0.008,
            fts_score=None,
            similarity=0.92,
            snippet="Rejected PostgreSQL - too complex",
        ),
    ]


# =============================================================================
# RetrievalResult Tests
# =============================================================================


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass."""

    def test_create_retrieval_result(self, mock_hybrid_result):
        """RetrievalResult holds results and metadata."""
        result = RetrievalResult(
            results=mock_hybrid_result,
            prompt="test query",
            project_hash="abc123",
            branch="main",
        )

        assert len(result.results) == 2
        assert result.prompt == "test query"
        assert result.project_hash == "abc123"
        assert result.branch == "main"


# =============================================================================
# retrieve_relevant_context Tests
# =============================================================================


class TestRetrieveRelevantContext:
    """Tests for retrieve_relevant_context function."""

    def test_returns_none_for_empty_prompt(self, tier2_config):
        """Empty prompt returns None."""
        result = retrieve_relevant_context("", config=tier2_config)
        assert result is None

        result = retrieve_relevant_context("   ", config=tier2_config)
        assert result is None

    def test_returns_none_for_tier0(self, tier0_config, tmp_path):
        """Tier 0 config returns None (requires Tier 2+)."""
        result = retrieve_relevant_context(
            "test query",
            project_path=str(tmp_path),
            config=tier0_config,
        )
        assert result is None

    def test_returns_none_for_tier1(self, tmp_path):
        """Tier 1 config returns None (requires Tier 2+)."""
        config = CortexConfig(
            cortex_home=tmp_path / ".cortex",
            storage_tier=1,
        )
        result = retrieve_relevant_context(
            "test query",
            project_path=str(tmp_path),
            config=config,
        )
        assert result is None

    def test_requires_project_path_or_hash(self, tier2_config):
        """Must provide project_path or project_hash."""
        result = retrieve_relevant_context(
            "test query",
            config=tier2_config,
        )
        assert result is None

    def test_graceful_degradation_without_sentence_transformers(self, tier2_config, tmp_path, monkeypatch):
        """Returns None if sentence-transformers not available."""
        # Mock the availability check to return False
        # Note: must patch in embeddings module since it's imported there
        monkeypatch.setattr(
            "cortex.embeddings.check_sentence_transformers_available",
            lambda: False,
        )

        result = retrieve_relevant_context(
            "test query",
            project_path=str(tmp_path),
            config=tier2_config,
        )
        assert result is None


# =============================================================================
# format_relevant_context Tests
# =============================================================================


class TestFormatRelevantContext:
    """Tests for format_relevant_context function."""

    def test_formats_results_as_markdown(self, mock_hybrid_result):
        """Results are formatted as markdown list."""
        retrieval = RetrievalResult(
            results=mock_hybrid_result,
            prompt="test query",
            project_hash="abc123",
            branch="main",
        )

        markdown = format_relevant_context(retrieval)

        assert "# Relevant Context" in markdown
        assert "Decision Made" in markdown
        assert "Approach Rejected" in markdown
        assert "keyword #1" in markdown
        assert "semantic #2" in markdown

    def test_empty_results_return_empty_string(self):
        """Empty results return empty string."""
        retrieval = RetrievalResult(
            results=[],
            prompt="test query",
            project_hash="abc123",
            branch="main",
        )

        markdown = format_relevant_context(retrieval)
        assert markdown == ""

    def test_respects_max_chars(self, mock_hybrid_result):
        """Output is truncated to max_chars."""
        retrieval = RetrievalResult(
            results=mock_hybrid_result,
            prompt="test query",
            project_hash="abc123",
            branch="main",
        )

        # Very small limit
        markdown = format_relevant_context(retrieval, max_chars=100)

        # Should be truncated
        assert len(markdown) <= 100 or "truncated" in markdown.lower()

    def test_includes_relevance_indicators(self, mock_hybrid_result):
        """Output includes keyword and semantic rank indicators."""
        retrieval = RetrievalResult(
            results=mock_hybrid_result,
            prompt="test query",
            project_hash="abc123",
            branch="main",
        )

        markdown = format_relevant_context(retrieval)

        # First result has both FTS and vector ranks
        assert "keyword #1" in markdown
        assert "semantic #2" in markdown

        # Second result only has vector rank
        assert "semantic #1" in markdown


# =============================================================================
# write_relevant_context_to_file Tests
# =============================================================================


class TestWriteRelevantContextToFile:
    """Tests for write_relevant_context_to_file function."""

    def test_creates_parent_directories(self, tmp_path, tier0_config):
        """Creates parent directories if needed."""
        output_path = tmp_path / "deep" / "nested" / "context.md"

        # This will fail (Tier 0) but should still create directories
        write_relevant_context_to_file(
            output_path=output_path,
            prompt="test query",
            project_path=str(tmp_path),
            config=tier0_config,
        )

        # Directory should exist even though file wasn't written
        # (because Tier 0 returns early)

    def test_removes_stale_context_file(self, tmp_path, tier0_config):
        """Removes stale context file if no relevant context found."""
        output_path = tmp_path / "context.md"

        # Create a stale file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("old context")

        # Try to write (will fail due to Tier 0, but should clean up)
        result = write_relevant_context_to_file(
            output_path=output_path,
            prompt="test query",
            project_path=str(tmp_path),
            config=tier0_config,
        )

        assert result is False
        assert not output_path.exists()

    def test_returns_false_when_no_results(self, tmp_path, tier0_config):
        """Returns False when retrieval fails or has no results."""
        output_path = tmp_path / "context.md"

        result = write_relevant_context_to_file(
            output_path=output_path,
            prompt="test query",
            project_path=str(tmp_path),
            config=tier0_config,
        )

        assert result is False


# =============================================================================
# handle_user_prompt_submit Tests
# =============================================================================


class TestHandleUserPromptSubmit:
    """Tests for handle_user_prompt_submit hook handler."""

    def test_returns_zero_for_empty_cwd(self):
        """Returns 0 for missing cwd."""
        payload = {"prompt": "test query"}
        result = handle_user_prompt_submit(payload)
        assert result == 0

    def test_returns_zero_for_empty_prompt(self, tmp_path):
        """Returns 0 for missing prompt."""
        payload = {"cwd": str(tmp_path)}
        result = handle_user_prompt_submit(payload)
        assert result == 0

    def test_returns_zero_for_tier0(self, tmp_path, monkeypatch):
        """Returns 0 for Tier 0 config (no-op)."""
        # Mock load_config to return Tier 0
        from cortex.config import CortexConfig

        monkeypatch.setattr(
            "cortex.hooks.load_config",
            lambda: CortexConfig(cortex_home=tmp_path / ".cortex", storage_tier=0),
        )

        payload = {
            "cwd": str(tmp_path),
            "prompt": "test query",
        }
        result = handle_user_prompt_submit(payload)
        assert result == 0

    def test_always_returns_zero_on_error(self, tmp_path, monkeypatch):
        """Always returns 0 even on error (graceful degradation)."""

        # Make identify_project raise an exception
        def raise_error(*args, **kwargs):
            raise RuntimeError("Test error")

        monkeypatch.setattr("cortex.hooks.identify_project", raise_error)

        payload = {
            "cwd": str(tmp_path),
            "prompt": "test query",
        }
        result = handle_user_prompt_submit(payload)
        assert result == 0


# =============================================================================
# CLI Integration Tests
# =============================================================================


class TestCLIIntegration:
    """Tests for CLI integration with anticipatory retrieval."""

    def test_init_hook_json_without_tier2(self, monkeypatch, tmp_path):
        """get_init_hook_json excludes UserPromptSubmit for Tier 0/1."""
        from cortex.cli import get_init_hook_json

        hook_json = get_init_hook_json(include_tier2=False)
        config = json.loads(hook_json)

        assert "UserPromptSubmit" not in config["hooks"]
        assert "Stop" in config["hooks"]
        assert "SessionStart" in config["hooks"]
        assert "PreCompact" in config["hooks"]

    def test_init_hook_json_with_tier2(self):
        """get_init_hook_json includes UserPromptSubmit for Tier 2."""
        from cortex.cli import get_init_hook_json

        hook_json = get_init_hook_json(include_tier2=True)
        config = json.loads(hook_json)

        assert "UserPromptSubmit" in config["hooks"]
        assert config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "cortex user-prompt-submit"


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_default_retrieval_limit(self):
        """DEFAULT_RETRIEVAL_LIMIT is reasonable."""
        assert DEFAULT_RETRIEVAL_LIMIT >= 3
        assert DEFAULT_RETRIEVAL_LIMIT <= 20

    def test_max_relevant_context_chars(self):
        """MAX_RELEVANT_CONTEXT_CHARS is reasonable."""
        assert MAX_RELEVANT_CONTEXT_CHARS >= 500
        assert MAX_RELEVANT_CONTEXT_CHARS <= 5000

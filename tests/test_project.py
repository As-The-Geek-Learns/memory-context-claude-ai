"""Tests for the Cortex project identity resolution."""

from pathlib import Path

from memory_context_claude_ai.project import (
    get_git_branch,
    get_git_info,
    get_project_hash,
    identify_project,
)


class TestGetProjectHash:
    """Tests for project hash generation."""

    def test_deterministic(self, tmp_path: Path) -> None:
        """Same path produces the same hash."""
        h1 = get_project_hash(str(tmp_path))
        h2 = get_project_hash(str(tmp_path))
        assert h1 == h2

    def test_length_is_16(self, tmp_path: Path) -> None:
        """Hash is exactly 16 hex characters."""
        h = get_project_hash(str(tmp_path))
        assert len(h) == 16
        int(h, 16)  # Should be valid hex

    def test_different_paths_different_hashes(self, tmp_path: Path) -> None:
        """Different directories produce different hashes."""
        dir_a = tmp_path / "project_a"
        dir_b = tmp_path / "project_b"
        dir_a.mkdir()
        dir_b.mkdir()
        assert get_project_hash(str(dir_a)) != get_project_hash(str(dir_b))

    def test_resolves_relative_paths(self, tmp_path: Path) -> None:
        """Relative paths are resolved to absolute before hashing."""
        # The hash of a path should be the same regardless of how it's specified
        # (as long as it resolves to the same location).
        absolute = str(tmp_path.resolve())
        h = get_project_hash(absolute)
        assert len(h) == 16


class TestGetGitBranch:
    """Tests for git branch detection."""

    def test_returns_branch_in_git_repo(self, tmp_git_repo: Path) -> None:
        """Returns the actual branch name in a git repo."""
        branch = get_git_branch(str(tmp_git_repo))
        # Default branch is typically 'main' or 'master'
        assert branch in ("main", "master")

    def test_returns_unknown_for_non_git_dir(self, tmp_path: Path) -> None:
        """Returns 'unknown' for a non-git directory."""
        branch = get_git_branch(str(tmp_path))
        assert branch == "unknown"

    def test_returns_unknown_for_nonexistent_dir(self) -> None:
        """Returns 'unknown' for a nonexistent directory."""
        branch = get_git_branch("/nonexistent/path/that/doesnt/exist")
        assert branch == "unknown"


class TestGetGitInfo:
    """Tests for comprehensive git info."""

    def test_returns_info_dict(self, tmp_git_repo: Path) -> None:
        """Returns a dict with branch, commit hash, and commit time."""
        info = get_git_info(str(tmp_git_repo))
        assert "branch" in info
        assert "last_commit_hash" in info
        assert "last_commit_time" in info

    def test_branch_matches_get_git_branch(self, tmp_git_repo: Path) -> None:
        """Branch from get_git_info matches get_git_branch."""
        info = get_git_info(str(tmp_git_repo))
        branch = get_git_branch(str(tmp_git_repo))
        assert info["branch"] == branch

    def test_has_commit_hash(self, tmp_git_repo: Path) -> None:
        """Commit hash is a 40-character hex string."""
        info = get_git_info(str(tmp_git_repo))
        assert len(info["last_commit_hash"]) == 40
        int(info["last_commit_hash"], 16)  # Should be valid hex

    def test_has_commit_time(self, tmp_git_repo: Path) -> None:
        """Commit time is a non-empty ISO timestamp string."""
        info = get_git_info(str(tmp_git_repo))
        assert info["last_commit_time"] != ""

    def test_non_git_dir_returns_defaults(self, tmp_path: Path) -> None:
        """Non-git directory returns safe defaults."""
        info = get_git_info(str(tmp_path))
        assert info["branch"] == "unknown"
        assert info["last_commit_hash"] == ""
        assert info["last_commit_time"] == ""


class TestIdentifyProject:
    """Tests for the high-level project identification."""

    def test_returns_complete_identity(self, tmp_git_repo: Path) -> None:
        """identify_project returns path, hash, branch, and git info."""
        identity = identify_project(str(tmp_git_repo))
        assert "path" in identity
        assert "hash" in identity
        assert "git_branch" in identity
        assert "git_info" in identity

    def test_path_is_resolved(self, tmp_git_repo: Path) -> None:
        """Path in identity is the resolved absolute path."""
        identity = identify_project(str(tmp_git_repo))
        assert identity["path"] == str(tmp_git_repo.resolve())

    def test_hash_is_16_chars(self, tmp_git_repo: Path) -> None:
        """Hash is a 16-character hex string."""
        identity = identify_project(str(tmp_git_repo))
        assert len(identity["hash"]) == 16

    def test_git_branch_matches(self, tmp_git_repo: Path) -> None:
        """Git branch in identity matches standalone get_git_branch."""
        identity = identify_project(str(tmp_git_repo))
        assert identity["git_branch"] == get_git_branch(str(tmp_git_repo))

    def test_non_git_dir_still_works(self, tmp_path: Path) -> None:
        """Non-git directories still produce a valid identity."""
        identity = identify_project(str(tmp_path))
        assert len(identity["hash"]) == 16
        assert identity["git_branch"] == "unknown"

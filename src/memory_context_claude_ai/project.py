"""Project identity resolution for Cortex.

Determines the current project's identity (hash, git branch, git info)
from the working directory. Uses subprocess for git operations with
defensive error handling — a non-git directory still works.
"""

import hashlib
import subprocess
from pathlib import Path


def get_project_hash(project_path: str) -> str:
    """Generate a deterministic hash for a project directory.

    Uses SHA-256 of the absolute, resolved path, truncated to 16 hex
    characters. This provides unique project isolation in the global
    ~/.cortex/projects/ directory.

    Args:
        project_path: Path to the project directory.

    Returns:
        16-character hex string identifying this project.
    """
    resolved = str(Path(project_path).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def get_git_branch(project_path: str) -> str:
    """Get the current git branch for a project directory.

    Args:
        project_path: Path to the project directory.

    Returns:
        Branch name string, or "unknown" if not a git repo or on error.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return "unknown"


def get_git_info(project_path: str) -> dict:
    """Get comprehensive git information for a project.

    Returns a dict with branch, last commit hash, and last commit time.
    All fields default to empty strings on failure — this function
    never raises exceptions.

    Args:
        project_path: Path to the project directory.

    Returns:
        Dict with keys: branch, last_commit_hash, last_commit_time
    """
    info = {
        "branch": "unknown",
        "last_commit_hash": "",
        "last_commit_time": "",
    }

    info["branch"] = get_git_branch(project_path)

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H %aI"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(" ", 1)
            if len(parts) >= 1:
                info["last_commit_hash"] = parts[0]
            if len(parts) >= 2:
                info["last_commit_time"] = parts[1]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    return info


def identify_project(cwd: str) -> dict:
    """Identify a project from its working directory.

    Combines path hashing and git info into a single project identity.

    Args:
        cwd: Current working directory (typically from hook payload).

    Returns:
        Dict with keys: path, hash, git_branch, git_info
    """
    resolved_path = str(Path(cwd).resolve())
    return {
        "path": resolved_path,
        "hash": get_project_hash(resolved_path),
        "git_branch": get_git_branch(resolved_path),
        "git_info": get_git_info(resolved_path),
    }

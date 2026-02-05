"""Isolated test environment for Phase 2 automation.

# WHAT: Manages temp directories, git repos, and config isolation.
# WHY: Tests must not pollute the real ~/.cortex/ data. This module
#       creates an ephemeral sandbox with proper git init and
#       config monkeypatching so hooks run against temp storage.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from cortex.config import CortexConfig
from cortex.project import get_project_hash


class TestEnvironment:
    """Isolated test environment with temp directories for Cortex data.

    Creates:
    - A temp project directory with an initialized git repo
    - A temp cortex home directory (simulates ~/.cortex/)
    - A CortexConfig pointing at the temp home
    - Helper methods to run hooks with monkeypatched config
    """

    def __init__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="cortex-phase2-")
        self.project_dir = Path(self._tmpdir) / "cortex-test-project"
        self.cortex_home = Path(self._tmpdir) / ".cortex"
        self.config = CortexConfig(cortex_home=self.cortex_home)

    def setup(self):
        """Initialize directories, git repo, and .claude/rules/ structure."""
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.cortex_home.mkdir(parents=True, exist_ok=True)
        (self.cortex_home / "projects").mkdir(exist_ok=True)

        # WHAT: Initialize a git repo with an initial commit.
        # WHY: identify_project() calls git rev-parse, which needs a repo.
        subprocess.run(["git", "init"], cwd=self.project_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@cortex.dev"],
            cwd=self.project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Cortex Test"],
            cwd=self.project_dir,
            capture_output=True,
        )
        readme = self.project_dir / "README.md"
        readme.write_text("# Cortex Test Project\n")
        subprocess.run(["git", "add", "."], cwd=self.project_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=self.project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-M", "main"],
            cwd=self.project_dir,
            capture_output=True,
        )

        # WHAT: Create the .claude/rules/ directory for briefing output.
        # WHY: handle_session_start writes cortex-briefing.md here.
        (self.project_dir / ".claude" / "rules").mkdir(parents=True, exist_ok=True)

    def get_project_hash(self) -> str:
        """Get the project hash for the test project directory."""
        return get_project_hash(str(self.project_dir))

    def get_briefing_path(self) -> Path:
        """Return .claude/rules/cortex-briefing.md in the project dir."""
        return self.project_dir / ".claude" / "rules" / "cortex-briefing.md"

    def read_briefing(self) -> str:
        """Read the briefing file content, or empty string if missing."""
        path = self.get_briefing_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def run_stop_hook(self, transcript_path: Path, session_id: str) -> int:
        """Run the Stop hook with monkeypatched config.

        # WHAT: Calls handle_stop() directly with a synthetic payload.
        # WHY: Avoids needing a real Claude Code session. The Stop hook
        #       accepts transcript_path in its payload, so we can point
        #       it at our synthetic JSONL file.
        """
        import cortex.hooks

        original_load = cortex.hooks.load_config
        cortex.hooks.load_config = lambda: self.config
        try:
            payload = {
                "cwd": str(self.project_dir),
                "transcript_path": str(transcript_path),
                "session_id": session_id,
                "stop_hook_active": False,
            }
            return cortex.hooks.handle_stop(payload)
        finally:
            cortex.hooks.load_config = original_load

    def run_session_start_hook(self) -> int:
        """Run the SessionStart hook with monkeypatched config.

        # WHAT: Calls handle_session_start() to generate a briefing.
        # WHY: The SessionStart hook writes cortex-briefing.md, which
        #       is the main output a user would check after extraction.
        """
        import cortex.hooks

        original_load = cortex.hooks.load_config
        cortex.hooks.load_config = lambda: self.config
        try:
            payload = {"cwd": str(self.project_dir)}
            return cortex.hooks.handle_session_start(payload)
        finally:
            cortex.hooks.load_config = original_load

    def get_event_store(self):
        """Get an EventStore for the test project."""
        from cortex.store import EventStore

        return EventStore(self.get_project_hash(), self.config)

    def cleanup(self):
        """Remove all temp directories."""
        shutil.rmtree(self._tmpdir, ignore_errors=True)

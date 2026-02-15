"""MCP Server implementation for Cortex.

Exposes Cortex memory capabilities via the Model Context Protocol, allowing
Claude to query memory mid-session. Uses FastMCP for simplified tool/resource
definition with stdio transport for Claude Code integration.

Architecture:
    - Project resolution from cwd (same as hook handlers)
    - Tier-aware capabilities (FTS5 on Tier 1, hybrid on Tier 2+)
    - Tools: cortex_search, cortex_search_decisions, cortex_get_plan, etc.
    - Resources: cortex://status, cortex://decisions, cortex://plan
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex.config import CortexConfig
    from cortex.store import EventStoreBase


def check_mcp_available() -> bool:
    """Check if the mcp package is installed."""
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class ProjectContext:
    """Resolved project context for MCP operations.

    Attributes:
        cwd: Working directory path.
        project_hash: 16-character hex hash identifying the project.
        config: Loaded Cortex configuration.
        store: Event store (tier-aware).
        storage_tier: Current storage tier (0, 1, or 2).
        has_embeddings: Whether embeddings are available (Tier 2+).
    """

    cwd: str
    project_hash: str
    config: "CortexConfig"
    store: "EventStoreBase"
    storage_tier: int
    has_embeddings: bool


def resolve_project_context(cwd: str | None = None) -> ProjectContext:
    """Resolve project context from working directory.

    Args:
        cwd: Working directory. Uses os.getcwd() if None.

    Returns:
        ProjectContext with resolved project identity and store.

    Raises:
        ValueError: If cwd is empty or invalid.
    """
    from cortex.config import load_config
    from cortex.embeddings import check_sentence_transformers_available
    from cortex.migration import detect_tier
    from cortex.project import identify_project
    from cortex.store import create_event_store

    work_dir = (os.getcwd() if cwd is None else cwd).strip()
    if not work_dir:
        raise ValueError("No working directory provided")

    identity = identify_project(work_dir)
    project_hash = identity["hash"]
    config = load_config()

    # Detect actual storage tier from filesystem
    actual_tier = detect_tier(project_hash, config)
    if actual_tier < 0:
        actual_tier = 0  # Treat uninitialized as Tier 0

    store = create_event_store(project_hash, config)

    # Check embedding availability for Tier 2+
    has_embeddings = actual_tier >= 2 and check_sentence_transformers_available()

    return ProjectContext(
        cwd=work_dir,
        project_hash=project_hash,
        config=config,
        store=store,
        storage_tier=actual_tier,
        has_embeddings=has_embeddings,
    )


class CortexMCPServer:
    """MCP Server exposing Cortex memory capabilities.

    Uses FastMCP for tool/resource definition with tier-aware capabilities.
    Designed for stdio transport with Claude Code.

    Usage:
        server = CortexMCPServer()
        server.run()  # Blocks, handles MCP protocol on stdio
    """

    def __init__(self, cwd: str | None = None) -> None:
        """Initialize the MCP server.

        Args:
            cwd: Working directory for project resolution.
                 Uses os.getcwd() if None.
        """
        if not check_mcp_available():
            raise ImportError("MCP package not installed. Install with: pip install 'cortex[tier3]'")

        from mcp.server.fastmcp import FastMCP

        self._cwd = cwd
        self._context: ProjectContext | None = None
        self._mcp = FastMCP("cortex")
        self._register_tools()
        self._register_resources()

    @property
    def context(self) -> ProjectContext:
        """Lazily resolve and cache project context."""
        if self._context is None:
            self._context = resolve_project_context(self._cwd)
        return self._context

    def _register_tools(self) -> None:
        """Register MCP tools for memory queries.

        Tools are registered via @mcp.tool() decorator pattern.
        Each tool receives query parameters and returns formatted results.
        """
        mcp = self._mcp

        @mcp.tool()
        async def cortex_search(query: str, limit: int = 10, branch: str | None = None) -> str:
            """Search Cortex memory using hybrid FTS + vector search.

            Args:
                query: Search query text.
                limit: Maximum number of results (default 10).
                branch: Filter by git branch (default: current branch).

            Returns:
                Formatted search results with event content and metadata.
            """
            return self._handle_search(query, limit, branch)

        @mcp.tool()
        async def cortex_search_decisions(query: str | None = None, limit: int = 20, branch: str | None = None) -> str:
            """Search immortal decisions and rejections.

            Args:
                query: Optional search query to filter decisions.
                limit: Maximum number of results (default 20).
                branch: Filter by git branch (default: current branch).

            Returns:
                Formatted list of decisions with reasoning.
            """
            return self._handle_search_decisions(query, limit, branch)

        @mcp.tool()
        async def cortex_get_plan(branch: str | None = None) -> str:
            """Get the active work plan and completed steps.

            Args:
                branch: Filter by git branch (default: current branch).

            Returns:
                Active plan with completed/pending steps.
            """
            return self._handle_get_plan(branch)

        @mcp.tool()
        async def cortex_get_recent(limit: int = 10, branch: str | None = None) -> str:
            """Get recent events ordered by salience and recency.

            Args:
                limit: Maximum number of results (default 10).
                branch: Filter by git branch (default: current branch).

            Returns:
                Recent events with content and metadata.
            """
            return self._handle_get_recent(limit, branch)

        @mcp.tool()
        async def cortex_get_status() -> str:
            """Get Cortex project status and capabilities.

            Returns:
                Project info including hash, tier, event count, capabilities.
            """
            return self._handle_get_status()

    def _register_resources(self) -> None:
        """Register MCP resources for read-only data access.

        Resources use URI scheme cortex:// and return structured data.
        """
        mcp = self._mcp

        @mcp.resource("cortex://status")
        async def status_resource() -> str:
            """Project metadata and status."""
            return self._handle_get_status()

        @mcp.resource("cortex://decisions")
        async def decisions_resource() -> str:
            """All immortal decisions in markdown format."""
            return self._handle_search_decisions(query=None, limit=100, branch=None)

        @mcp.resource("cortex://plan")
        async def plan_resource() -> str:
            """Active work plan in markdown format."""
            return self._handle_get_plan(branch=None)

    def _get_current_branch(self) -> str | None:
        """Get current git branch from project context."""
        from cortex.project import get_git_info

        git_info = get_git_info(self.context.cwd)
        return git_info.get("branch")

    def _handle_search(self, query: str, limit: int = 10, branch: str | None = None) -> str:
        """Handle search tool invocation."""
        ctx = self.context
        branch = branch or self._get_current_branch()

        # Use hybrid search on Tier 2+, FTS5 on Tier 1
        if ctx.storage_tier >= 2 and ctx.has_embeddings:
            from cortex.hybrid_search import hybrid_search

            results = hybrid_search(
                ctx.store._conn,  # type: ignore[attr-defined]
                query,
                limit=limit,
                git_branch=branch,
            )
            if not results:
                return f"No results found for '{query}'"

            lines = [f"## Search Results for '{query}'\n"]
            for i, r in enumerate(results, 1):
                event = r.event
                lines.append(f"### {i}. {event.type.value}")
                lines.append(f"**Score:** {r.rrf_score:.3f} | **Branch:** {event.git_branch or 'unknown'}")
                lines.append(f"**Created:** {event.created_at[:19] if event.created_at else 'unknown'}")
                lines.append(f"\n{event.content}\n")
            return "\n".join(lines)

        elif ctx.storage_tier >= 1:
            from cortex.search import search

            results = search(
                ctx.store._conn,  # type: ignore[attr-defined]
                query,
                limit=limit,
                git_branch=branch,
            )
            if not results:
                return f"No results found for '{query}'"

            lines = [f"## Search Results for '{query}'\n"]
            for i, r in enumerate(results, 1):
                event = r.event
                lines.append(f"### {i}. {event.type.value}")
                lines.append(f"**Score:** {r.score:.3f} | **Branch:** {event.git_branch or 'unknown'}")
                if r.snippet:
                    lines.append(f"**Snippet:** ...{r.snippet}...")
                lines.append(f"\n{event.content}\n")
            return "\n".join(lines)

        else:
            # Tier 0: Simple in-memory search
            events = ctx.store.load_recent(n=100)
            query_lower = query.lower()
            matches = [e for e in events if query_lower in e.content.lower()][:limit]
            if not matches:
                return f"No results found for '{query}'"

            lines = [f"## Search Results for '{query}'\n"]
            for i, event in enumerate(matches, 1):
                lines.append(f"### {i}. {event.type.value}")
                lines.append(f"**Branch:** {event.git_branch or 'unknown'}")
                lines.append(f"\n{event.content}\n")
            return "\n".join(lines)

    def _handle_search_decisions(self, query: str | None, limit: int = 20, branch: str | None = None) -> str:
        """Handle search_decisions tool invocation."""
        ctx = self.context
        branch = branch or self._get_current_branch()

        # Load immortal events (decisions)
        immortal_events = ctx.store.load_immortal()

        # Filter by branch if specified
        if branch:
            immortal_events = [e for e in immortal_events if e.git_branch == branch]

        # Filter by query if provided
        if query:
            query_lower = query.lower()
            immortal_events = [e for e in immortal_events if query_lower in e.content.lower()]

        immortal_events = immortal_events[:limit]

        if not immortal_events:
            return "No decisions found."

        lines = ["## Decisions\n"]
        for i, event in enumerate(immortal_events, 1):
            lines.append(f"### {i}. {event.type.value}")
            lines.append(f"**Branch:** {event.git_branch or 'unknown'} | **Confidence:** {event.confidence:.2f}")
            lines.append(f"\n{event.content}\n")
        return "\n".join(lines)

    def _handle_get_plan(self, branch: str | None = None) -> str:
        """Handle get_plan tool invocation."""
        from cortex.models import EventType

        ctx = self.context
        branch = branch or self._get_current_branch()

        # Load plan-related events
        plan_created = ctx.store.load_by_type(EventType.PLAN_CREATED)
        plan_steps = ctx.store.load_by_type(EventType.PLAN_STEP_COMPLETED)

        # Filter by branch
        if branch:
            plan_created = [e for e in plan_created if e.git_branch == branch]
            plan_steps = [e for e in plan_steps if e.git_branch == branch]

        if not plan_created:
            return "No active plan found."

        # Get most recent plan
        latest_plan = max(plan_created, key=lambda e: e.created_at or "")

        lines = ["## Active Plan\n"]
        lines.append(f"**Created:** {latest_plan.created_at[:19] if latest_plan.created_at else 'unknown'}")
        lines.append(f"**Branch:** {latest_plan.git_branch or 'unknown'}\n")
        lines.append(latest_plan.content)

        if plan_steps:
            lines.append("\n### Completed Steps\n")
            for step in plan_steps:
                lines.append(f"- {step.content}")

        return "\n".join(lines)

    def _handle_get_recent(self, limit: int = 10, branch: str | None = None) -> str:
        """Handle get_recent tool invocation."""
        ctx = self.context
        branch = branch or self._get_current_branch()

        events = ctx.store.load_recent(n=limit * 2)  # Fetch extra for filtering

        # Filter by branch
        if branch:
            events = [e for e in events if e.git_branch == branch]

        events = events[:limit]

        if not events:
            return "No recent events found."

        lines = ["## Recent Events\n"]
        for i, event in enumerate(events, 1):
            lines.append(f"### {i}. {event.type.value}")
            lines.append(f"**Salience:** {event.salience:.2f} | **Branch:** {event.git_branch or 'unknown'}")
            lines.append(f"**Created:** {event.created_at[:19] if event.created_at else 'unknown'}")
            lines.append(f"\n{event.content}\n")
        return "\n".join(lines)

    def _handle_get_status(self) -> str:
        """Handle get_status tool invocation."""
        ctx = self.context

        tier_names = {0: "JSON", 1: "SQLite + FTS5", 2: "SQLite + Embeddings"}
        tier_name = tier_names.get(ctx.storage_tier, f"Unknown ({ctx.storage_tier})")

        lines = [
            "## Cortex Status\n",
            f"**Project:** {ctx.cwd}",
            f"**Hash:** {ctx.project_hash}",
            f"**Storage Tier:** {ctx.storage_tier} ({tier_name})",
            f"**Events:** {ctx.store.count()}",
        ]

        # Tier 2+ specific info
        if ctx.storage_tier >= 2:
            from cortex.sqlite_store import SQLiteEventStore

            if isinstance(ctx.store, SQLiteEventStore):
                embedding_count = ctx.store.count_embeddings()
                lines.append(f"**Embeddings:** {embedding_count}")
                lines.append(f"**Hybrid Search:** {'available' if ctx.has_embeddings else 'unavailable'}")

        # Current branch
        branch = self._get_current_branch()
        if branch:
            lines.append(f"**Current Branch:** {branch}")

        return "\n".join(lines)

    def run(self) -> None:
        """Run the MCP server with stdio transport.

        Blocks until the server is terminated. Handles MCP protocol
        messages on stdin/stdout.
        """
        self._mcp.run(transport="stdio")


def run_server(cwd: str | None = None) -> int:
    """Entry point for 'cortex mcp-server' command.

    Args:
        cwd: Working directory. Uses os.getcwd() if None.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    try:
        if not check_mcp_available():
            print(
                "Error: MCP package not installed. Install with: pip install 'cortex[tier3]'",
                file=sys.stderr,
            )
            return 1

        server = CortexMCPServer(cwd=cwd)
        server.run()
        return 0

    except Exception as e:
        print(f"Cortex MCP server error: {e}", file=sys.stderr)
        return 1

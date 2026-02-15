"""Cortex MCP Server — Mid-session memory queries via Model Context Protocol.

This module provides an MCP server that exposes Cortex memory capabilities
as tools and resources that Claude can query during a session.

Usage:
    cortex mcp-server       # Start MCP server (stdio transport)

The server detects the project from cwd and adapts capabilities based on
the storage tier (Tier 1: FTS5, Tier 2+: hybrid search).

Public API:
    - CortexMCPServer: Main server class
    - run_server: Entry point for CLI
    - check_mcp_available: Check if mcp package is installed
"""

from cortex.mcp.server import (
    CortexMCPServer,
    check_mcp_available,
    run_server,
)

__all__ = [
    "CortexMCPServer",
    "check_mcp_available",
    "run_server",
]

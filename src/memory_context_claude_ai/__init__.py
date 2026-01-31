"""Cortex: Event-sourced memory for Claude Code.

Provides persistent cross-session memory by capturing events from Claude Code
hooks (Stop, SessionStart, PreCompact) and generating context briefings that
are automatically loaded at session start.

Public API:
    - Event, EventType, create_event: Core event model
    - CortexConfig, load_config, save_config: Configuration
    - EventStore, HookState: Storage
    - identify_project, get_project_hash: Project identity
"""

__version__ = "0.1.0"

from memory_context_claude_ai.config import CortexConfig, load_config, save_config
from memory_context_claude_ai.models import Event, EventType, create_event
from memory_context_claude_ai.project import get_project_hash, identify_project
from memory_context_claude_ai.store import EventStore, HookState

__all__ = [
    "CortexConfig",
    "Event",
    "EventStore",
    "EventType",
    "HookState",
    "create_event",
    "get_project_hash",
    "identify_project",
    "load_config",
    "save_config",
]

"""Cortex: Event-sourced memory for Claude Code.

Provides persistent cross-session memory by capturing events from Claude Code
hooks (Stop, SessionStart, PreCompact) and generating context briefings that
are automatically loaded at session start.

Public API:
    - Event, EventType, create_event: Core event model
    - CortexConfig, load_config, save_config: Configuration
    - EventStore, HookState: Storage
    - identify_project, get_project_hash: Project identity
    - TranscriptEntry, TranscriptReader: Transcript parsing
    - ToolCall, ToolResult: Tool interaction models
    - extract_text_content, extract_thinking_content: Content extraction
    - extract_tool_calls, extract_tool_results: Tool extraction
    - strip_code_blocks: Code block removal for keyword matching
    - find_transcript_path, find_latest_transcript: Transcript discovery
    - extract_events: Three-layer extraction pipeline
    - extract_structural, extract_semantic, extract_explicit: Individual layers
"""

__version__ = "0.1.0"

from memory_context_claude_ai.config import CortexConfig, load_config, save_config
from memory_context_claude_ai.extractors import (
    extract_events,
    extract_explicit,
    extract_semantic,
    extract_structural,
)
from memory_context_claude_ai.models import Event, EventType, create_event
from memory_context_claude_ai.project import get_project_hash, identify_project
from memory_context_claude_ai.store import EventStore, HookState
from memory_context_claude_ai.transcript import (
    ToolCall,
    ToolResult,
    TranscriptEntry,
    TranscriptReader,
    extract_text_content,
    extract_thinking_content,
    extract_tool_calls,
    extract_tool_results,
    find_latest_transcript,
    find_transcript_path,
    strip_code_blocks,
)

__all__ = [
    "CortexConfig",
    "Event",
    "EventStore",
    "EventType",
    "HookState",
    "ToolCall",
    "ToolResult",
    "TranscriptEntry",
    "TranscriptReader",
    "create_event",
    "extract_events",
    "extract_explicit",
    "extract_semantic",
    "extract_structural",
    "extract_text_content",
    "extract_thinking_content",
    "extract_tool_calls",
    "extract_tool_results",
    "find_latest_transcript",
    "find_transcript_path",
    "get_project_hash",
    "identify_project",
    "load_config",
    "save_config",
    "strip_code_blocks",
]

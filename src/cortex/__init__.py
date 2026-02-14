"""Cortex: Event-sourced memory for Claude Code.

Provides persistent cross-session memory by capturing events from Claude Code
hooks (Stop, SessionStart, PreCompact) and generating context briefings that
are automatically loaded at session start.

Public API:
    - Event, EventType, create_event: Core event model
    - CortexConfig, load_config, save_config: Configuration
    - EventStoreBase, EventStore, SQLiteEventStore: Storage backends
    - create_event_store: Factory for tier-aware store instantiation
    - HookState: Hook execution state
    - identify_project, get_project_hash: Project identity
    - TranscriptEntry, TranscriptReader: Transcript parsing
    - ToolCall, ToolResult: Tool interaction models
    - extract_text_content, extract_thinking_content: Content extraction
    - extract_tool_calls, extract_tool_results: Tool extraction
    - strip_code_blocks: Code block removal for keyword matching
    - find_transcript_path, find_latest_transcript: Transcript discovery
    - extract_events: Three-layer extraction pipeline
    - extract_structural, extract_semantic, extract_explicit: Individual layers
    - generate_briefing, write_briefing_to_file: Briefing generation
    - read_payload, handle_stop, handle_precompact, handle_session_start: Hook handlers
    - cmd_reset, cmd_status, cmd_init, get_init_hook_json: CLI commands
    - SearchResult, search, search_by_type: FTS5 full-text search
    - Snapshot, save_snapshot, get_valid_snapshot: Briefing snapshot caching
    - MigrationResult, upgrade, detect_tier, get_migration_status, rollback: Tier migration
    - EmbeddingEngine, embed, embed_batch: Vector embedding generation (Tier 2)
    - VectorSearchResult, search_similar, backfill_embeddings: Vector search (Tier 2)
    - HybridResult, hybrid_search, search_semantic: Hybrid FTS + vector search (Tier 2)
"""

__version__ = "0.1.0"

from cortex.briefing import generate_briefing, write_briefing_to_file
from cortex.cli import cmd_init, cmd_reset, cmd_status, get_init_hook_json
from cortex.config import CortexConfig, load_config, save_config
from cortex.embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingEngine,
    check_sentence_transformers_available,
    embed,
    embed_batch,
    get_embedding_engine,
)
from cortex.extractors import (
    extract_events,
    extract_explicit,
    extract_semantic,
    extract_structural,
)
from cortex.hooks import (
    handle_precompact,
    handle_session_start,
    handle_stop,
    read_payload,
)
from cortex.hybrid_search import (
    DEFAULT_RRF_K,
    HybridResult,
    hybrid_search,
    search_semantic,
)
from cortex.migration import (
    MigrationResult,
    detect_tier,
    get_migration_status,
    rollback,
    upgrade,
)
from cortex.models import Event, EventType, create_event
from cortex.project import get_project_hash, identify_project
from cortex.search import (
    SearchResult,
    get_similar_events,
    rebuild_fts_index,
    search,
    search_by_type,
    search_decisions,
    search_knowledge,
)
from cortex.snapshot import (
    Snapshot,
    cleanup_expired_snapshots,
    get_snapshot_stats,
    get_valid_snapshot,
    invalidate_snapshots,
    save_snapshot,
)
from cortex.sqlite_store import SQLiteEventStore
from cortex.store import EventStore, EventStoreBase, HookState, create_event_store
from cortex.transcript import (
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
from cortex.vec import (
    VectorSearchResult,
    backfill_embeddings,
    count_embeddings,
    get_embedding,
    search_similar,
    store_embedding,
)

__all__ = [
    "CortexConfig",
    "DEFAULT_RRF_K",
    "EMBEDDING_DIMENSION",
    "EmbeddingEngine",
    "Event",
    "EventStore",
    "EventStoreBase",
    "EventType",
    "HookState",
    "HybridResult",
    "MigrationResult",
    "SQLiteEventStore",
    "SearchResult",
    "Snapshot",
    "check_sentence_transformers_available",
    "cleanup_expired_snapshots",
    "create_event_store",
    "detect_tier",
    "embed",
    "embed_batch",
    "get_embedding_engine",
    "get_migration_status",
    "rollback",
    "upgrade",
    "ToolCall",
    "ToolResult",
    "TranscriptEntry",
    "TranscriptReader",
    "cmd_init",
    "cmd_reset",
    "cmd_status",
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
    "generate_briefing",
    "get_init_hook_json",
    "get_project_hash",
    "get_similar_events",
    "get_snapshot_stats",
    "get_valid_snapshot",
    "handle_precompact",
    "handle_session_start",
    "handle_stop",
    "identify_project",
    "invalidate_snapshots",
    "load_config",
    "read_payload",
    "rebuild_fts_index",
    "save_config",
    "save_snapshot",
    "search",
    "search_by_type",
    "search_decisions",
    "search_knowledge",
    "store_embedding",
    "strip_code_blocks",
    "write_briefing_to_file",
    "VectorSearchResult",
    "backfill_embeddings",
    "count_embeddings",
    "get_embedding",
    "hybrid_search",
    "search_semantic",
    "search_similar",
]

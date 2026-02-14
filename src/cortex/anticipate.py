"""Anticipatory retrieval for Cortex (Tier 2+).

Uses the UserPromptSubmit hook to proactively retrieve relevant context
before Claude processes the user's message. Embeds the user's prompt and
performs hybrid search (FTS5 + vector similarity) to find related events.

This implements "Dual-Mind"-style anticipatory loading without secondary
LLM calls — all retrieval is local via embeddings and SQLite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.config import CortexConfig, load_config
from cortex.project import get_project_hash, identify_project
from cortex.store import create_event_store

if TYPE_CHECKING:
    from cortex.hybrid_search import HybridResult

logger = logging.getLogger(__name__)

# WHAT: Default limit for relevant context retrieval.
# WHY: Balance between context richness and token budget.
DEFAULT_RETRIEVAL_LIMIT = 5

# WHAT: Maximum characters for relevant context section.
# WHY: Keep anticipatory context focused; main briefing has the overview.
MAX_RELEVANT_CONTEXT_CHARS = 2000


@dataclass
class RetrievalResult:
    """Result of anticipatory retrieval.

    Attributes:
        results: List of HybridResult objects from search.
        prompt: The original user prompt that was searched.
        project_hash: Project identifier.
        branch: Git branch used for search filter.
    """

    results: list["HybridResult"]
    prompt: str
    project_hash: str
    branch: str


def retrieve_relevant_context(
    prompt: str,
    project_path: str | None = None,
    project_hash: str | None = None,
    config: CortexConfig | None = None,
    branch: str | None = None,
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
) -> RetrievalResult | None:
    """Retrieve events relevant to the user's prompt.

    Embeds the prompt and performs hybrid search to find semantically
    and keyword-similar events. Requires Tier 2 (storage_tier >= 2)
    and sentence-transformers to be available.

    Args:
        prompt: The user's message text from UserPromptSubmit hook.
        project_path: Project directory path (used if project_hash not set).
        project_hash: 16-char project hash (preferred over project_path).
        config: Optional config. Defaults to load_config().
        branch: Optional git branch filter. If None, auto-detected.
        limit: Maximum results to return (default 5).

    Returns:
        RetrievalResult with relevant events, or None if:
        - Tier < 2 (requires embedding support)
        - sentence-transformers not available
        - Prompt is empty
        - No relevant results found
    """
    if not prompt or not prompt.strip():
        return None

    config = config or load_config()

    # WHAT: Require Tier 2+ for anticipatory retrieval.
    # WHY: Needs embeddings and hybrid search capabilities.
    if config.storage_tier < 2:
        logger.debug("Anticipatory retrieval requires Tier 2+")
        return None

    # Resolve project identity
    if project_hash is None:
        if project_path is None:
            return None
        project_hash = get_project_hash(project_path)

    # Auto-detect branch if not provided
    if branch is None and project_path:
        identity = identify_project(project_path)
        branch = identity.get("git_branch") or ""

    # WHAT: Check for embedding availability.
    # WHY: Graceful degradation if sentence-transformers not installed.
    from cortex.embeddings import check_sentence_transformers_available, embed

    if not check_sentence_transformers_available():
        logger.debug("sentence-transformers not available for anticipatory retrieval")
        return None

    # Get store and verify it's SQLiteEventStore
    store = create_event_store(project_hash, config)

    # WHAT: Import here to avoid circular imports.
    # WHY: sqlite_store imports from other modules that might import this.
    from cortex.sqlite_store import SQLiteEventStore

    if not isinstance(store, SQLiteEventStore):
        logger.debug("Anticipatory retrieval requires SQLiteEventStore")
        return None

    # Generate embedding for the prompt
    query_embedding = embed(prompt)
    if query_embedding is None:
        logger.debug("Failed to generate embedding for prompt")
        return None

    # Perform hybrid search
    results = store.hybrid_search(
        query=prompt,
        query_embedding=query_embedding,
        limit=limit,
        branch=branch or None,
    )

    if not results:
        return None

    return RetrievalResult(
        results=results,
        prompt=prompt,
        project_hash=project_hash,
        branch=branch or "",
    )


def format_relevant_context(
    retrieval: RetrievalResult,
    max_chars: int = MAX_RELEVANT_CONTEXT_CHARS,
) -> str:
    """Format retrieval results as markdown for injection into context.

    Args:
        retrieval: RetrievalResult from retrieve_relevant_context().
        max_chars: Maximum characters for the output.

    Returns:
        Markdown string with relevant context section.
    """
    if not retrieval.results:
        return ""

    parts: list[str] = []
    used = 0

    header = "# Relevant Context\n\n"
    header += "_Anticipatory retrieval based on your message:_\n\n"

    if len(header) > max_chars:
        return ""

    parts.append(header)
    used += len(header)

    for result in retrieval.results:
        event = result.event

        # Format: event type, snippet, relevance indicator
        type_label = event.type.value.replace("_", " ").title()

        # Use snippet if available, otherwise truncate content
        content = result.snippet or event.content[:150]
        if len(content) > 150:
            content = content[:147] + "..."

        # Build relevance indicator
        relevance_parts = []
        if result.fts_rank is not None:
            relevance_parts.append(f"keyword #{result.fts_rank}")
        if result.vec_rank is not None:
            relevance_parts.append(f"semantic #{result.vec_rank}")
        relevance = f" ({', '.join(relevance_parts)})" if relevance_parts else ""

        line = f"- **{type_label}**{relevance}: {content}\n"

        if used + len(line) > max_chars:
            # Add truncation notice if we're cutting off results
            truncated = f"\n_({len(retrieval.results) - len(parts) + 1} more results truncated)_\n"
            if used + len(truncated) <= max_chars:
                parts.append(truncated)
            break

        parts.append(line)
        used += len(line)

    return "".join(parts)


def write_relevant_context_to_file(
    output_path: str | Path,
    prompt: str,
    project_path: str | None = None,
    project_hash: str | None = None,
    config: CortexConfig | None = None,
    branch: str | None = None,
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
) -> bool:
    """Retrieve relevant context and write to file.

    This is the main entry point for the UserPromptSubmit hook.
    Writes to .claude/rules/cortex-relevant-context.md by default.

    Args:
        output_path: File path to write the markdown.
        prompt: The user's message text.
        project_path: Project directory path.
        project_hash: 16-char project hash.
        config: Optional config.
        branch: Optional git branch filter.
        limit: Maximum results to return.

    Returns:
        True if relevant context was written, False otherwise.
    """
    output_path = Path(output_path)

    retrieval = retrieve_relevant_context(
        prompt=prompt,
        project_path=project_path,
        project_hash=project_hash,
        config=config,
        branch=branch,
        limit=limit,
    )

    if retrieval is None or not retrieval.results:
        # WHAT: Remove stale context file if no relevant context found.
        # WHY: Prevents old context from bleeding into new prompts.
        if output_path.exists():
            output_path.unlink()
        return False

    content = format_relevant_context(retrieval)
    if not content:
        if output_path.exists():
            output_path.unlink()
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return True

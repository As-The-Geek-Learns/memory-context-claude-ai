"""Hybrid search combining FTS5 and vector similarity.

Implements Reciprocal Rank Fusion (RRF) to combine keyword-based
FTS5 search with semantic vector similarity search. This provides
better retrieval than either method alone.

RRF formula: score = sum(weight / (k + rank)) for each search method
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from cortex.models import Event, EventType
from cortex.search import SearchResult, search
from cortex.vec import VectorSearchResult, search_similar

logger = logging.getLogger(__name__)

# WHAT: Default RRF k parameter.
# WHY: k=60 is the standard value from the original RRF paper.
# Higher k reduces the impact of high ranks, lower k amplifies them.
DEFAULT_RRF_K = 60


@dataclass
class HybridResult:
    """Result from hybrid FTS5 + vector search.

    Attributes:
        event: The matched Event object.
        fts_rank: Rank in FTS5 results (1-indexed, None if not in FTS results).
        vec_rank: Rank in vector results (1-indexed, None if not in vec results).
        rrf_score: Combined Reciprocal Rank Fusion score (higher = more relevant).
        fts_score: BM25 score from FTS5 search (None if not in FTS results).
        similarity: Vector similarity score 0-1 (None if not in vec results).
        snippet: Content excerpt with highlighted matches from FTS5.
    """

    event: Event
    fts_rank: int | None
    vec_rank: int | None
    rrf_score: float
    fts_score: float | None
    similarity: float | None
    snippet: str


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: list[float] | None = None,
    limit: int = 10,
    k: int = DEFAULT_RRF_K,
    fts_weight: float = 0.5,
    vec_weight: float = 0.5,
    event_type: EventType | None = None,
    branch: str | None = None,
    min_confidence: float = 0.0,
) -> list[HybridResult]:
    """Combine FTS5 and vector search using Reciprocal Rank Fusion.

    RRF merges ranked lists from different retrieval methods into a single
    ranking. The formula is: score = sum(weight / (k + rank)) for each method.

    Args:
        conn: SQLite connection with initialized schema.
        query: Text query for FTS5 search.
        query_embedding: Embedding vector for similarity search.
            If None, performs FTS5-only search.
        limit: Maximum results to return (default 10).
        k: RRF k parameter (default 60). Higher k = more uniform weighting.
        fts_weight: Weight for FTS5 results (default 0.5).
        vec_weight: Weight for vector results (default 0.5).
        event_type: Optional filter by event type.
        branch: Optional filter by git branch.
        min_confidence: Minimum confidence threshold for events.

    Returns:
        List of HybridResult objects sorted by RRF score (highest first).
    """
    # Collect FTS5 results
    fts_results: list[SearchResult] = []
    if query.strip():
        fts_results = search(
            conn,
            query,
            limit=limit * 2,  # Fetch more for fusion
            event_type=event_type,
            branch=branch,
        )

    # Collect vector results
    vec_results: list[VectorSearchResult] = []
    if query_embedding is not None:
        vec_results = search_similar(
            conn,
            query_embedding,
            limit=limit * 2,  # Fetch more for fusion
            event_type=event_type.value if event_type else None,
            git_branch=branch,
            min_confidence=min_confidence,
        )

    # If no embedding provided, return FTS-only results
    if not vec_results and fts_results:
        return _fts_only_results(fts_results, k, fts_weight, limit)

    # If no query provided, return vector-only results
    if not fts_results and vec_results:
        return _vec_only_results(conn, vec_results, k, vec_weight, limit)

    # If both empty, return empty
    if not fts_results and not vec_results:
        return []

    # Build ID -> result maps for fusion
    fts_map: dict[str, tuple[int, SearchResult]] = {}
    for rank, result in enumerate(fts_results, start=1):
        fts_map[result.event.id] = (rank, result)

    vec_map: dict[str, tuple[int, VectorSearchResult]] = {}
    for rank, vec_result in enumerate(vec_results, start=1):
        vec_map[vec_result.event_id] = (rank, vec_result)

    # Collect all unique event IDs
    all_event_ids = set(fts_map.keys()) | set(vec_map.keys())

    # Compute RRF scores
    hybrid_results: list[HybridResult] = []
    for event_id in all_event_ids:
        fts_rank: int | None = None
        fts_score: float | None = None
        fts_snippet: str = ""
        event: Event | None = None

        vec_rank: int | None = None
        similarity: float | None = None

        # Get FTS5 data
        if event_id in fts_map:
            fts_rank, fts_result = fts_map[event_id]
            fts_score = fts_result.score
            fts_snippet = fts_result.snippet
            event = fts_result.event

        # Get vector data
        if event_id in vec_map:
            vec_rank, vec_result = vec_map[event_id]
            similarity = vec_result.similarity

        # If event not yet loaded (vector-only), load it
        if event is None:
            event = _load_event(conn, event_id)
            if event is None:
                continue  # Skip if event can't be loaded

        # Compute RRF score
        rrf_score = _compute_rrf_score(
            fts_rank=fts_rank,
            vec_rank=vec_rank,
            k=k,
            fts_weight=fts_weight,
            vec_weight=vec_weight,
        )

        # Use FTS snippet if available, otherwise use content preview
        snippet = fts_snippet if fts_snippet else event.content[:150]

        hybrid_results.append(
            HybridResult(
                event=event,
                fts_rank=fts_rank,
                vec_rank=vec_rank,
                rrf_score=rrf_score,
                fts_score=fts_score,
                similarity=similarity,
                snippet=snippet,
            )
        )

    # Sort by RRF score (descending) and limit
    hybrid_results.sort(key=lambda r: r.rrf_score, reverse=True)
    return hybrid_results[:limit]


def search_semantic(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    event_type: EventType | None = None,
    branch: str | None = None,
    min_confidence: float = 0.0,
) -> list[HybridResult]:
    """Pure vector similarity search without keyword matching.

    Use this when you have a query embedding and want semantic similarity
    without FTS5 keyword matching.

    Args:
        conn: SQLite connection with initialized schema.
        query_embedding: Embedding vector to search for similar events.
        limit: Maximum results to return (default 10).
        event_type: Optional filter by event type.
        branch: Optional filter by git branch.
        min_confidence: Minimum confidence threshold for events.

    Returns:
        List of HybridResult objects sorted by similarity (highest first).
    """
    vec_results = search_similar(
        conn,
        query_embedding,
        limit=limit,
        event_type=event_type.value if event_type else None,
        git_branch=branch,
        min_confidence=min_confidence,
    )

    if not vec_results:
        return []

    hybrid_results: list[HybridResult] = []
    for rank, vec_result in enumerate(vec_results, start=1):
        event = _load_event(conn, vec_result.event_id)
        if event is None:
            continue

        hybrid_results.append(
            HybridResult(
                event=event,
                fts_rank=None,
                vec_rank=rank,
                rrf_score=vec_result.similarity,  # Use similarity as score
                fts_score=None,
                similarity=vec_result.similarity,
                snippet=event.content[:150],
            )
        )

    return hybrid_results[:limit]


def _compute_rrf_score(
    fts_rank: int | None,
    vec_rank: int | None,
    k: int,
    fts_weight: float,
    vec_weight: float,
) -> float:
    """Compute Reciprocal Rank Fusion score.

    RRF formula: score = sum(weight / (k + rank)) for each method.

    Args:
        fts_rank: Rank in FTS5 results (1-indexed, or None).
        vec_rank: Rank in vector results (1-indexed, or None).
        k: RRF k parameter.
        fts_weight: Weight for FTS5 contribution.
        vec_weight: Weight for vector contribution.

    Returns:
        Combined RRF score.
    """
    score = 0.0

    if fts_rank is not None:
        score += fts_weight / (k + fts_rank)

    if vec_rank is not None:
        score += vec_weight / (k + vec_rank)

    return score


def _fts_only_results(
    fts_results: list[SearchResult],
    k: int,
    fts_weight: float,
    limit: int,
) -> list[HybridResult]:
    """Convert FTS-only results to HybridResult format.

    Args:
        fts_results: List of FTS5 search results.
        k: RRF k parameter.
        fts_weight: Weight for FTS5 contribution.
        limit: Maximum results to return.

    Returns:
        List of HybridResult objects.
    """
    results = []
    for rank, fts_result in enumerate(fts_results, start=1):
        rrf_score = fts_weight / (k + rank)
        results.append(
            HybridResult(
                event=fts_result.event,
                fts_rank=rank,
                vec_rank=None,
                rrf_score=rrf_score,
                fts_score=fts_result.score,
                similarity=None,
                snippet=fts_result.snippet,
            )
        )

    return results[:limit]


def _vec_only_results(
    conn: sqlite3.Connection,
    vec_results: list[VectorSearchResult],
    k: int,
    vec_weight: float,
    limit: int,
) -> list[HybridResult]:
    """Convert vector-only results to HybridResult format.

    Args:
        conn: SQLite connection for loading event data.
        vec_results: List of vector search results.
        k: RRF k parameter.
        vec_weight: Weight for vector contribution.
        limit: Maximum results to return.

    Returns:
        List of HybridResult objects.
    """
    results = []
    for rank, vec_result in enumerate(vec_results, start=1):
        event = _load_event(conn, vec_result.event_id)
        if event is None:
            continue

        rrf_score = vec_weight / (k + rank)
        results.append(
            HybridResult(
                event=event,
                fts_rank=None,
                vec_rank=rank,
                rrf_score=rrf_score,
                fts_score=None,
                similarity=vec_result.similarity,
                snippet=event.content[:150],
            )
        )

    return results[:limit]


def _load_event(conn: sqlite3.Connection, event_id: str) -> Event | None:
    """Load a single event by ID.

    Args:
        conn: SQLite connection.
        event_id: Event ID to load.

    Returns:
        Event object or None if not found.
    """
    import json

    cursor = conn.execute(
        "SELECT * FROM events WHERE id = ?",
        (event_id,),
    )
    row = cursor.fetchone()

    if row is None:
        return None

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata else {}

    return Event(
        id=row["id"],
        session_id=row["session_id"] or "",
        project=row["project"] or "",
        git_branch=row["git_branch"] or "",
        type=EventType(row["type"]),
        content=row["content"] or "",
        metadata=metadata,
        salience=row["salience"],
        confidence=row["confidence"],
        created_at=row["created_at"],
        accessed_at=row["accessed_at"],
        access_count=row["access_count"],
        immortal=bool(row["immortal"]),
        provenance=row["provenance"] or "",
    )

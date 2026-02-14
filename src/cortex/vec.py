"""Vector operations for Cortex Tier 2.

Provides vector storage and similarity search using sqlite-vec.
Embeddings are stored as BLOBs in the events table and queried
using sqlite-vec's distance functions.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from collections.abc import Callable
from dataclasses import dataclass

from cortex.db import check_vec_available, load_vec_extension

logger = logging.getLogger(__name__)


@dataclass
class VectorSearchResult:
    """Result from a vector similarity search."""

    event_id: str
    distance: float  # Lower is more similar (L2 distance)
    similarity: float  # Higher is more similar (converted from distance)


def serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding to bytes for SQLite BLOB storage.

    Uses little-endian float32 format, matching sqlite-vec expectations.

    Args:
        embedding: List of floats (typically 384 dimensions).

    Returns:
        Bytes representation of the embedding.
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)


def deserialize_embedding(blob: bytes) -> list[float]:
    """Deserialize embedding from SQLite BLOB.

    Args:
        blob: Bytes from SQLite BLOB column.

    Returns:
        List of floats.
    """
    count = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"<{count}f", blob))


def store_embedding(
    conn: sqlite3.Connection,
    event_id: str,
    embedding: list[float],
) -> bool:
    """Store an embedding for an event.

    Args:
        conn: SQLite connection.
        event_id: Event ID to update.
        embedding: Embedding vector to store.

    Returns:
        True if stored successfully, False otherwise.
    """
    try:
        blob = serialize_embedding(embedding)
        conn.execute(
            "UPDATE events SET embedding = ? WHERE id = ?",
            (blob, event_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to store embedding for {event_id}: {e}")
        return False


def get_embedding(conn: sqlite3.Connection, event_id: str) -> list[float] | None:
    """Retrieve an embedding for an event.

    Args:
        conn: SQLite connection.
        event_id: Event ID to retrieve.

    Returns:
        Embedding vector or None if not found.
    """
    cursor = conn.execute(
        "SELECT embedding FROM events WHERE id = ?",
        (event_id,),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return deserialize_embedding(row[0])


def search_similar(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    event_type: str | None = None,
    git_branch: str | None = None,
    min_confidence: float = 0.0,
) -> list[VectorSearchResult]:
    """Search for events similar to a query embedding.

    Uses sqlite-vec for efficient vector similarity search.
    Falls back to brute-force search if sqlite-vec is unavailable.

    Args:
        conn: SQLite connection.
        query_embedding: Query vector to search for.
        limit: Maximum number of results.
        event_type: Optional filter by event type.
        git_branch: Optional filter by git branch.
        min_confidence: Minimum confidence threshold.

    Returns:
        List of VectorSearchResult sorted by similarity (highest first).
    """
    if check_vec_available():
        return _search_similar_vec(conn, query_embedding, limit, event_type, git_branch, min_confidence)
    else:
        return _search_similar_brute(conn, query_embedding, limit, event_type, git_branch, min_confidence)


def _search_similar_vec(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int,
    event_type: str | None,
    git_branch: str | None,
    min_confidence: float,
) -> list[VectorSearchResult]:
    """Vector search using sqlite-vec extension."""
    if not load_vec_extension(conn):
        logger.warning("Failed to load sqlite-vec, falling back to brute force")
        return _search_similar_brute(conn, query_embedding, limit, event_type, git_branch, min_confidence)

    query_blob = serialize_embedding(query_embedding)

    # Build query with filters
    where_clauses = ["embedding IS NOT NULL"]
    params: list = []

    if event_type:
        where_clauses.append("type = ?")
        params.append(event_type)
    if git_branch:
        where_clauses.append("git_branch = ?")
        params.append(git_branch)
    if min_confidence > 0:
        where_clauses.append("confidence >= ?")
        params.append(min_confidence)

    where_sql = " AND ".join(where_clauses)

    # Use vec_distance_L2 for Euclidean distance
    query = f"""
        SELECT id, vec_distance_L2(embedding, ?) as distance
        FROM events
        WHERE {where_sql}
        ORDER BY distance ASC
        LIMIT ?
    """
    params = [query_blob] + params + [limit]

    try:
        cursor = conn.execute(query, params)
        results = []
        for row in cursor.fetchall():
            distance = row[1]
            # Convert L2 distance to similarity score (0-1 range)
            # Using exponential decay: similarity = exp(-distance)
            similarity = _distance_to_similarity(distance)
            results.append(
                VectorSearchResult(
                    event_id=row[0],
                    distance=distance,
                    similarity=similarity,
                )
            )
        return results
    except sqlite3.OperationalError as e:
        logger.warning(f"sqlite-vec query failed: {e}, falling back to brute force")
        return _search_similar_brute(conn, query_embedding, limit, event_type, git_branch, min_confidence)


def _search_similar_brute(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int,
    event_type: str | None,
    git_branch: str | None,
    min_confidence: float,
) -> list[VectorSearchResult]:
    """Brute-force vector search (fallback when sqlite-vec unavailable)."""
    import numpy as np

    query_vec = np.array(query_embedding)

    # Build query with filters
    where_clauses = ["embedding IS NOT NULL"]
    params: list = []

    if event_type:
        where_clauses.append("type = ?")
        params.append(event_type)
    if git_branch:
        where_clauses.append("git_branch = ?")
        params.append(git_branch)
    if min_confidence > 0:
        where_clauses.append("confidence >= ?")
        params.append(min_confidence)

    where_sql = " AND ".join(where_clauses)
    query = f"SELECT id, embedding FROM events WHERE {where_sql}"

    cursor = conn.execute(query, params)
    results = []

    for row in cursor.fetchall():
        event_id = row[0]
        embedding = deserialize_embedding(row[1])
        event_vec = np.array(embedding)

        # L2 (Euclidean) distance
        distance = float(np.linalg.norm(query_vec - event_vec))
        similarity = _distance_to_similarity(distance)

        results.append(
            VectorSearchResult(
                event_id=event_id,
                distance=distance,
                similarity=similarity,
            )
        )

    # Sort by distance (ascending) and limit
    results.sort(key=lambda r: r.distance)
    return results[:limit]


def _distance_to_similarity(distance: float) -> float:
    """Convert L2 distance to similarity score (0-1 range).

    Uses exponential decay: similarity = exp(-distance / scale)
    For normalized embeddings, typical distances are 0-2.

    Args:
        distance: L2 (Euclidean) distance.

    Returns:
        Similarity score between 0 and 1.
    """
    import math

    # Scale factor tuned for normalized embeddings
    # Distance 0 -> similarity 1.0
    # Distance 1 -> similarity ~0.61
    # Distance 2 -> similarity ~0.37
    return math.exp(-distance)


def count_embeddings(conn: sqlite3.Connection) -> int:
    """Count events with embeddings.

    Args:
        conn: SQLite connection.

    Returns:
        Number of events with non-null embeddings.
    """
    cursor = conn.execute("SELECT COUNT(*) FROM events WHERE embedding IS NOT NULL")
    return cursor.fetchone()[0]


def get_events_without_embeddings(
    conn: sqlite3.Connection,
    limit: int = 100,
) -> list[tuple[str, str]]:
    """Get events that need embeddings generated.

    Args:
        conn: SQLite connection.
        limit: Maximum number of events to return.

    Returns:
        List of (event_id, content) tuples.
    """
    cursor = conn.execute(
        """
        SELECT id, content FROM events
        WHERE embedding IS NULL AND content != ''
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]


def backfill_embeddings(
    conn: sqlite3.Connection,
    batch_size: int = 32,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    """Generate embeddings for all events that don't have them.

    Args:
        conn: SQLite connection.
        batch_size: Number of events to process at once.
        progress_callback: Optional callback(done, total) for progress.

    Returns:
        Number of embeddings generated.
    """
    from cortex.embeddings import EmbeddingEngine

    engine = EmbeddingEngine()
    if not engine.is_available():
        logger.warning("Embedding engine not available, cannot backfill")
        return 0

    # Count total events needing embeddings
    cursor = conn.execute("SELECT COUNT(*) FROM events WHERE embedding IS NULL AND content != ''")
    total = cursor.fetchone()[0]

    if total == 0:
        return 0

    generated = 0
    while True:
        events = get_events_without_embeddings(conn, limit=batch_size)
        if not events:
            break

        ids = [e[0] for e in events]
        contents = [e[1] for e in events]

        embeddings = engine.embed_batch(contents)

        for event_id, embedding in zip(ids, embeddings, strict=True):
            if embedding is not None:
                store_embedding(conn, event_id, embedding)
                generated += 1

        if progress_callback:
            progress_callback(generated, total)

    return generated

"""FTS5 full-text search for Cortex events.

Provides BM25-ranked keyword search over event content with:
- Optional type and branch filters
- Snippet generation with match highlighting
- Relevance scoring

Requires SQLite with FTS5 support (Python 3.11+ typically includes this).
"""

import re
import sqlite3
from dataclasses import dataclass

from cortex.models import Event, EventType


@dataclass
class SearchResult:
    """A search result with relevance metadata.

    Attributes:
        event: The matched Event object.
        score: BM25 relevance score (higher = more relevant).
        snippet: Content excerpt with matches highlighted using **markers**.
    """

    event: Event
    score: float
    snippet: str


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    event_type: EventType | None = None,
    branch: str | None = None,
) -> list[SearchResult]:
    """Search events using FTS5 full-text search with BM25 ranking.

    Args:
        conn: SQLite connection with initialized schema.
        query: Search query (supports FTS5 syntax: AND, OR, NOT, "phrase").
        limit: Maximum results to return (default 20).
        event_type: Optional filter by event type.
        branch: Optional filter by git branch.

    Returns:
        List of SearchResult objects sorted by relevance (highest first).
    """
    if not query.strip():
        return []

    # WHAT: Escape special FTS5 characters that could break queries.
    # WHY: User input may contain quotes, parentheses, etc.
    safe_query = _escape_fts_query(query)

    # Build the query with optional filters
    sql = """
        SELECT
            e.*,
            bm25(events_fts) AS score,
            snippet(events_fts, 0, '**', '**', '...', 32) AS snippet
        FROM events_fts
        JOIN events e ON events_fts.rowid = e.rowid
        WHERE events_fts MATCH ?
    """
    params: list = [safe_query]

    if event_type is not None:
        sql += " AND e.type = ?"
        params.append(event_type.value)

    if branch is not None:
        sql += " AND (e.git_branch = ? OR e.git_branch = '' OR e.git_branch IS NULL)"
        params.append(branch)

    sql += " ORDER BY score LIMIT ?"
    params.append(limit)

    try:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        # WHAT: Handle FTS5 query syntax errors gracefully.
        # WHY: Invalid user queries shouldn't crash the search.
        if "fts5" in str(e).lower() or "syntax" in str(e).lower():
            return []
        raise

    return [_row_to_search_result(row) for row in rows]


def search_by_type(
    conn: sqlite3.Connection,
    query: str,
    event_type: EventType,
    limit: int = 20,
) -> list[SearchResult]:
    """Search events filtered by type.

    Convenience wrapper around search() with event_type filter.

    Args:
        conn: SQLite connection with initialized schema.
        query: Search query.
        event_type: Filter to this event type only.
        limit: Maximum results to return.

    Returns:
        List of SearchResult objects sorted by relevance.
    """
    return search(conn, query, limit=limit, event_type=event_type)


def search_decisions(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    """Search only decision events.

    Useful for finding past architectural decisions.

    Args:
        conn: SQLite connection with initialized schema.
        query: Search query.
        limit: Maximum results to return.

    Returns:
        List of SearchResult objects for DECISION_MADE events.
    """
    return search(conn, query, limit=limit, event_type=EventType.DECISION_MADE)


def search_knowledge(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    """Search only knowledge events.

    Useful for finding learned facts and discoveries.

    Args:
        conn: SQLite connection with initialized schema.
        query: Search query.
        limit: Maximum results to return.

    Returns:
        List of SearchResult objects for KNOWLEDGE_ACQUIRED events.
    """
    return search(conn, query, limit=limit, event_type=EventType.KNOWLEDGE_ACQUIRED)


def get_similar_events(
    conn: sqlite3.Connection,
    event: Event,
    limit: int = 5,
) -> list[SearchResult]:
    """Find events similar to the given event.

    Extracts key terms from the event's content and searches for
    related events. Excludes the source event from results.

    Args:
        conn: SQLite connection with initialized schema.
        event: Source event to find similar events for.
        limit: Maximum results to return.

    Returns:
        List of SearchResult objects for similar events.
    """
    # Extract meaningful terms from content
    terms = _extract_search_terms(event.content)
    if not terms:
        return []

    # Search using OR to find events matching any term
    query = " OR ".join(terms[:5])  # Limit to top 5 terms
    results = search(conn, query, limit=limit + 1)  # +1 in case source is in results

    # Filter out the source event
    return [r for r in results if r.event.id != event.id][:limit]


def rebuild_fts_index(conn: sqlite3.Connection) -> int:
    """Rebuild the FTS5 index from scratch.

    Use this if the index gets out of sync with the events table.

    Args:
        conn: SQLite connection.

    Returns:
        Number of events indexed.
    """
    # WHAT: Rebuild command repopulates FTS from content table.
    # WHY: Handles corruption or manual edits to events table.
    conn.execute("INSERT INTO events_fts(events_fts) VALUES('rebuild')")
    conn.commit()

    cursor = conn.execute("SELECT COUNT(*) FROM events")
    return cursor.fetchone()[0]


def _escape_fts_query(query: str) -> str:
    """Escape special FTS5 characters in user query.

    FTS5 special characters: " ( ) * - : ^
    We escape them to be treated as literals.

    Args:
        query: Raw user query.

    Returns:
        Escaped query safe for FTS5 MATCH.
    """
    # WHAT: Wrap query in quotes if it contains special chars.
    # WHY: Quoted strings are treated as phrase searches, escaping specials.
    special_chars = set('"():-^')
    has_special = any(c in query for c in special_chars)

    if has_special:
        # Escape internal quotes and wrap in quotes
        escaped = query.replace('"', '""')
        return f'"{escaped}"'

    # For simple queries, just return as-is
    return query


def _extract_search_terms(content: str) -> list[str]:
    """Extract meaningful search terms from content.

    Filters out common stopwords and short terms.

    Args:
        content: Event content text.

    Returns:
        List of search terms, longest first.
    """
    # Simple tokenization: split on non-alphanumeric
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", content)

    # Common stopwords to filter
    stopwords = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "should",
        "can",
        "may",
        "not",
        "but",
        "use",
        "using",
    }

    # Filter and deduplicate
    seen = set()
    terms = []
    for word in words:
        lower = word.lower()
        if lower not in stopwords and lower not in seen:
            seen.add(lower)
            terms.append(word)

    # Sort by length (longer terms are usually more specific)
    return sorted(terms, key=len, reverse=True)


def _row_to_search_result(row: sqlite3.Row) -> SearchResult:
    """Convert a database row to a SearchResult object.

    Args:
        row: SQLite Row with event fields plus score and snippet.

    Returns:
        SearchResult with Event, score, and snippet.
    """
    import json

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata else {}

    event = Event(
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

    return SearchResult(
        event=event,
        score=abs(row["score"]),  # BM25 returns negative scores; flip for intuition
        snippet=row["snippet"] or event.content[:100],
    )

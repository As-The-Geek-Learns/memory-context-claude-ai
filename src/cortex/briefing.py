"""Briefing generation for Cortex.

Converts stored events into a markdown context document loaded at session start
(e.g. .claude/rules/cortex-briefing.md). Respects config briefing budget and
tiered inclusion (immortal, active plan, recent).

Tier 1+ adds snapshot caching for <10ms briefing retrieval on cache hits.
"""

from pathlib import Path

from cortex.config import CortexConfig, load_config
from cortex.models import Event
from cortex.project import get_project_hash
from cortex.store import create_event_store

# Approximate characters per token for budget enforcement (conservative for English/code).
CHARS_PER_TOKEN = 4


def generate_briefing(
    project_hash: str | None = None,
    project_path: str | None = None,
    config: CortexConfig | None = None,
    branch: str | None = None,
    use_cache: bool = True,
) -> str:
    """Generate a markdown briefing from stored events for the given project.

    Uses EventStore.load_for_briefing() and applies the config briefing budget.
    Sections: Decisions & Rejections (immortal), Active Plan, Recent Context.

    For Tier 1+, briefings are cached as snapshots. Set use_cache=False to
    force regeneration.

    Args:
        project_hash: 16-char project hash. If None, project_path must be set.
        project_path: Project directory path. If set, project_hash is derived
                      via get_project_hash(project_path). Ignored if project_hash set.
        config: Optional config. Defaults to load_config().
        branch: Optional git branch filter for events.
        use_cache: Whether to use snapshot cache (Tier 1+ only). Default True.

    Returns:
        Markdown string suitable for cortex-briefing.md.

    Raises:
        ValueError: If neither project_hash nor project_path is provided.
    """
    if project_hash is None and project_path is None:
        raise ValueError("Either project_hash or project_path must be provided")
    if project_hash is None:
        assert project_path is not None  # Guaranteed by check above
        project_hash = get_project_hash(project_path)

    config = config or load_config()
    store = create_event_store(project_hash, config)

    # WHAT: Check for cached snapshot (Tier 1+ only).
    # WHY: Snapshot hits return in <10ms vs ~100ms for full generation.
    if use_cache and config.storage_tier >= 1:
        cached = _get_cached_briefing(store, branch or "")
        if cached is not None:
            return cached

    # Generate briefing from events
    data = store.load_for_briefing(branch=branch)
    immortal = data["immortal"]
    active_plan = data["active_plan"]
    recent = data["recent"]

    markdown = _render_briefing(
        immortal=immortal,
        active_plan=active_plan,
        recent=recent,
        max_chars=config.max_briefing_tokens * CHARS_PER_TOKEN,
        max_full=config.max_full_decisions,
        max_summary=config.max_summary_decisions,
    )

    # WHAT: Cache the generated briefing (Tier 1+ only).
    # WHY: Subsequent requests return instantly until events change.
    if config.storage_tier >= 1:
        _cache_briefing(store, branch or "", markdown, immortal, active_plan, recent, config)

    return markdown


def _get_cached_briefing(store, branch: str) -> str | None:
    """Get cached briefing from snapshot if available.

    Args:
        store: EventStore (must be SQLiteEventStore for Tier 1+).
        branch: Git branch to get snapshot for.

    Returns:
        Cached markdown or None if no valid snapshot exists.
    """
    # WHAT: Import here to avoid circular imports and Tier 0 dependencies.
    # WHY: snapshot module requires SQLite which Tier 0 doesn't use.
    from cortex.snapshot import get_valid_snapshot
    from cortex.sqlite_store import SQLiteEventStore

    if not isinstance(store, SQLiteEventStore):
        return None

    conn = store._get_conn()
    snapshot = get_valid_snapshot(conn, branch)

    if snapshot is not None:
        return snapshot.briefing_markdown

    return None


def _cache_briefing(
    store,
    branch: str,
    markdown: str,
    immortal: list[Event],
    active_plan: list[Event],
    recent: list[Event],
    config: CortexConfig,
) -> None:
    """Cache briefing as a snapshot.

    Args:
        store: EventStore (must be SQLiteEventStore for Tier 1+).
        branch: Git branch this briefing is for.
        markdown: The generated briefing markdown.
        immortal: Immortal events included in briefing.
        active_plan: Active plan events included in briefing.
        recent: Recent events included in briefing.
        config: Config with snapshot_ttl_hours.
    """
    from cortex.snapshot import save_snapshot
    from cortex.sqlite_store import SQLiteEventStore

    if not isinstance(store, SQLiteEventStore):
        return

    # Collect all event IDs included in this briefing
    all_events = immortal + active_plan + recent
    event_ids = [e.id for e in all_events]
    last_event_id = event_ids[0] if event_ids else ""

    conn = store._get_conn()
    save_snapshot(
        conn=conn,
        branch=branch,
        markdown=markdown,
        event_ids=event_ids,
        last_event_id=last_event_id,
        ttl_hours=config.snapshot_ttl_hours,
    )


def _render_briefing(
    immortal: list[Event],
    active_plan: list[Event],
    recent: list[Event],
    max_chars: int,
    max_full: int,
    max_summary: int,
) -> str:
    """Render events into markdown briefing with budget enforcement.

    Args:
        immortal: Immortal events (decisions, rejections).
        active_plan: Active plan events.
        recent: Recent context events.
        max_chars: Maximum characters for the briefing.
        max_full: Maximum full-text decision entries.
        max_summary: Maximum summary-only decision entries.

    Returns:
        Markdown string.
    """
    parts: list[str] = []
    used = 0

    def add(s: str) -> bool:
        nonlocal used
        if used + len(s) > max_chars:
            return False
        parts.append(s)
        used += len(s)
        return True

    # Section: Decisions & Rejections (immortal)
    full_immortal = immortal[:max_full]
    summary_immortal = immortal[max_full : max_full + max_summary] if max_summary else []

    if full_immortal or summary_immortal:
        if not add("# Decisions & Rejections\n\n"):
            return "".join(parts)
        for e in full_immortal:
            line = _format_event_line(e, full=True)
            if not add(line):
                return "".join(parts)
        for e in summary_immortal:
            line = _format_event_line(e, full=False)
            if not add(line):
                return "".join(parts)
        if not add("\n"):
            return "".join(parts)

    # Section: Active Plan
    if active_plan:
        if not add("## Active Plan\n\n"):
            return "".join(parts)
        for e in active_plan:
            line = _format_event_line(e, full=True)
            if not add(line):
                return "".join(parts)
        if not add("\n"):
            return "".join(parts)

    # Section: Recent Context
    if recent:
        if not add("## Recent Context\n\n"):
            return "".join(parts)
        for e in recent:
            line = _format_event_line(e, full=True)
            if not add(line):
                return "".join(parts)

    return "".join(parts)


def _format_event_line(event: Event, full: bool = True) -> str:
    """Format a single event as a markdown list item."""
    if full or not event.content:
        content = event.content.strip() or "(no content)"
        return f"- {content}\n"
    # One-line summary: first line or truncated to 80 chars
    raw = event.content.strip()
    first_line = raw.split("\n")[0][:80] if raw else "(no content)"
    if len(raw.split("\n")[0]) > 80:
        first_line += "..."
    return f"- {first_line}\n"


def write_briefing_to_file(
    output_path: str | Path,
    project_hash: str | None = None,
    project_path: str | None = None,
    config: CortexConfig | None = None,
    branch: str | None = None,
    use_cache: bool = True,
) -> None:
    """Generate a briefing and write it to a file for use by Phase 6 hooks.

    Creates parent directories if needed. Typical output_path:
    .claude/rules/cortex-briefing.md

    Args:
        output_path: File path to write the markdown briefing.
        project_hash: 16-char project hash. If None, project_path must be set.
        project_path: Project directory path (used to derive project_hash if needed).
        config: Optional config. Defaults to load_config().
        branch: Optional git branch filter for events.
        use_cache: Whether to use snapshot cache (Tier 1+ only). Default True.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_briefing(
        project_hash=project_hash,
        project_path=project_path,
        config=config,
        branch=branch,
        use_cache=use_cache,
    )
    output_path.write_text(content, encoding="utf-8")

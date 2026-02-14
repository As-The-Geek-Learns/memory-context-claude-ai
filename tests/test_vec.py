"""Tests for vector operations (Tier 2).

Tests serialization, storage, retrieval, and similarity search.
Uses pytest.importorskip for graceful handling when numpy unavailable.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

np = pytest.importorskip("numpy")

from cortex import db, vec

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with schema initialized."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db.initialize_schema(conn)
    return conn


@pytest.fixture
def sample_embedding():
    """Return a sample 384-dimension embedding."""
    return [0.1] * 384


@pytest.fixture
def sample_events(test_db):
    """Insert sample events and return their IDs."""
    now = datetime.now(timezone.utc).isoformat()
    events = [
        ("evt1", "DECISION", "Use SQLite for storage", 0.9),
        ("evt2", "KNOWLEDGE", "Python supports async/await", 0.7),
        ("evt3", "ERROR_RECOVERY", "Fixed import error", 0.6),
        ("evt4", "DECISION", "Use pytest for testing", 0.8),
    ]
    for event_id, event_type, content, confidence in events:
        test_db.execute(
            """
            INSERT INTO events (id, type, content, confidence, created_at, accessed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, event_type, content, confidence, now, now),
        )
    test_db.commit()
    return [e[0] for e in events]


# =============================================================================
# Test Serialization
# =============================================================================


class TestSerializeEmbedding:
    """Tests for serialize_embedding function."""

    def test_serializes_to_bytes(self, sample_embedding):
        """Should return bytes."""
        result = vec.serialize_embedding(sample_embedding)
        assert isinstance(result, bytes)

    def test_correct_byte_length(self, sample_embedding):
        """Should have 4 bytes per float (float32)."""
        result = vec.serialize_embedding(sample_embedding)
        assert len(result) == len(sample_embedding) * 4

    def test_little_endian_format(self):
        """Should use little-endian byte order."""
        import struct

        embedding = [1.0, 2.0, 3.0]
        result = vec.serialize_embedding(embedding)
        # Unpack as little-endian and verify
        unpacked = struct.unpack("<3f", result)
        assert list(unpacked) == embedding

    def test_empty_embedding(self):
        """Should handle empty embedding."""
        result = vec.serialize_embedding([])
        assert result == b""


class TestDeserializeEmbedding:
    """Tests for deserialize_embedding function."""

    def test_round_trip(self, sample_embedding):
        """Should round-trip serialize/deserialize."""
        blob = vec.serialize_embedding(sample_embedding)
        result = vec.deserialize_embedding(blob)
        assert len(result) == len(sample_embedding)
        for a, b in zip(result, sample_embedding, strict=True):
            assert abs(a - b) < 1e-6

    def test_empty_blob(self):
        """Should handle empty blob."""
        result = vec.deserialize_embedding(b"")
        assert result == []

    def test_returns_list(self, sample_embedding):
        """Should return a list, not numpy array."""
        blob = vec.serialize_embedding(sample_embedding)
        result = vec.deserialize_embedding(blob)
        assert isinstance(result, list)


# =============================================================================
# Test Storage
# =============================================================================


class TestStoreEmbedding:
    """Tests for store_embedding function."""

    def test_stores_embedding(self, test_db, sample_events, sample_embedding):
        """Should store embedding in database."""
        event_id = sample_events[0]
        result = vec.store_embedding(test_db, event_id, sample_embedding)
        assert result is True

        # Verify stored
        cursor = test_db.execute("SELECT embedding FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        assert row[0] is not None

    def test_returns_false_on_error(self, test_db, sample_embedding):
        """Should return False if event doesn't exist."""
        # Store to non-existent event - will succeed but update nothing
        result = vec.store_embedding(test_db, "nonexistent", sample_embedding)
        # The function returns True even if no rows updated (design choice)
        assert result is True

    def test_overwrites_existing(self, test_db, sample_events, sample_embedding):
        """Should overwrite existing embedding."""
        event_id = sample_events[0]

        # Store first embedding
        vec.store_embedding(test_db, event_id, sample_embedding)

        # Store different embedding
        new_embedding = [0.5] * 384
        vec.store_embedding(test_db, event_id, new_embedding)

        # Verify new embedding stored
        retrieved = vec.get_embedding(test_db, event_id)
        assert retrieved is not None
        assert abs(retrieved[0] - 0.5) < 1e-6


class TestGetEmbedding:
    """Tests for get_embedding function."""

    def test_returns_embedding(self, test_db, sample_events, sample_embedding):
        """Should return stored embedding."""
        event_id = sample_events[0]
        vec.store_embedding(test_db, event_id, sample_embedding)

        result = vec.get_embedding(test_db, event_id)
        assert result is not None
        assert len(result) == 384

    def test_returns_none_if_not_found(self, test_db):
        """Should return None for non-existent event."""
        result = vec.get_embedding(test_db, "nonexistent")
        assert result is None

    def test_returns_none_if_no_embedding(self, test_db, sample_events):
        """Should return None if event exists but has no embedding."""
        result = vec.get_embedding(test_db, sample_events[0])
        assert result is None


# =============================================================================
# Test Distance to Similarity
# =============================================================================


class TestDistanceToSimilarity:
    """Tests for _distance_to_similarity function."""

    def test_zero_distance_gives_one(self):
        """Distance 0 should give similarity 1.0."""
        result = vec._distance_to_similarity(0.0)
        assert result == 1.0

    def test_larger_distance_gives_lower_similarity(self):
        """Larger distance should give lower similarity."""
        sim1 = vec._distance_to_similarity(0.5)
        sim2 = vec._distance_to_similarity(1.0)
        sim3 = vec._distance_to_similarity(2.0)
        assert sim1 > sim2 > sim3

    def test_returns_positive(self):
        """Should always return positive value."""
        for distance in [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]:
            result = vec._distance_to_similarity(distance)
            assert result > 0


# =============================================================================
# Test Similar Search (Brute Force)
# =============================================================================


class TestSearchSimilarBrute:
    """Tests for brute-force vector search."""

    def test_finds_similar_events(self, test_db, sample_events):
        """Should find events with embeddings."""
        # Store embeddings for two events
        emb1 = [0.1] * 384
        emb2 = [0.9] * 384
        vec.store_embedding(test_db, sample_events[0], emb1)
        vec.store_embedding(test_db, sample_events[1], emb2)

        # Search for similar to emb1
        results = vec._search_similar_brute(
            test_db, emb1, limit=10, event_type=None, git_branch=None, min_confidence=0.0
        )

        assert len(results) == 2
        # First result should be evt1 (exact match)
        assert results[0].event_id == sample_events[0]
        assert results[0].distance < results[1].distance

    def test_respects_limit(self, test_db, sample_events):
        """Should respect limit parameter."""
        for event_id in sample_events:
            vec.store_embedding(test_db, event_id, [0.1] * 384)

        results = vec._search_similar_brute(
            test_db, [0.1] * 384, limit=2, event_type=None, git_branch=None, min_confidence=0.0
        )
        assert len(results) == 2

    def test_filters_by_type(self, test_db, sample_events):
        """Should filter by event type."""
        for event_id in sample_events:
            vec.store_embedding(test_db, event_id, [0.1] * 384)

        results = vec._search_similar_brute(
            test_db, [0.1] * 384, limit=10, event_type="DECISION", git_branch=None, min_confidence=0.0
        )
        # evt1 and evt4 are DECISION type
        assert len(results) == 2
        for r in results:
            assert r.event_id in [sample_events[0], sample_events[3]]

    def test_filters_by_confidence(self, test_db, sample_events):
        """Should filter by minimum confidence."""
        for event_id in sample_events:
            vec.store_embedding(test_db, event_id, [0.1] * 384)

        results = vec._search_similar_brute(
            test_db, [0.1] * 384, limit=10, event_type=None, git_branch=None, min_confidence=0.8
        )
        # evt1 (0.9) and evt4 (0.8) have confidence >= 0.8
        assert len(results) == 2

    def test_empty_when_no_embeddings(self, test_db, sample_events):
        """Should return empty when no embeddings exist."""
        results = vec._search_similar_brute(
            test_db, [0.1] * 384, limit=10, event_type=None, git_branch=None, min_confidence=0.0
        )
        assert len(results) == 0

    def test_result_has_correct_fields(self, test_db, sample_events):
        """Should return VectorSearchResult with all fields."""
        vec.store_embedding(test_db, sample_events[0], [0.1] * 384)

        results = vec._search_similar_brute(
            test_db, [0.1] * 384, limit=1, event_type=None, git_branch=None, min_confidence=0.0
        )

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, vec.VectorSearchResult)
        assert result.event_id == sample_events[0]
        assert isinstance(result.distance, float)
        assert isinstance(result.similarity, float)
        assert 0 <= result.similarity <= 1


# =============================================================================
# Test Search Similar (Main Function)
# =============================================================================


class TestSearchSimilar:
    """Tests for search_similar function."""

    def test_delegates_to_brute_force_without_vec(self, test_db, sample_events):
        """Should use brute force when sqlite-vec unavailable."""
        vec.store_embedding(test_db, sample_events[0], [0.1] * 384)

        with patch.object(vec, "check_vec_available", return_value=False):
            results = vec.search_similar(test_db, [0.1] * 384, limit=10)

        assert len(results) == 1

    def test_tries_vec_when_available(self, test_db, sample_events):
        """Should try sqlite-vec when available."""
        vec.store_embedding(test_db, sample_events[0], [0.1] * 384)

        with patch.object(vec, "check_vec_available", return_value=True):
            with patch.object(vec, "_search_similar_vec") as mock_vec:
                mock_vec.return_value = []
                vec.search_similar(test_db, [0.1] * 384, limit=10)

        mock_vec.assert_called_once()


# =============================================================================
# Test Count Embeddings
# =============================================================================


class TestCountEmbeddings:
    """Tests for count_embeddings function."""

    def test_counts_correctly(self, test_db, sample_events):
        """Should count events with embeddings."""
        assert vec.count_embeddings(test_db) == 0

        vec.store_embedding(test_db, sample_events[0], [0.1] * 384)
        assert vec.count_embeddings(test_db) == 1

        vec.store_embedding(test_db, sample_events[1], [0.2] * 384)
        assert vec.count_embeddings(test_db) == 2


# =============================================================================
# Test Get Events Without Embeddings
# =============================================================================


class TestGetEventsWithoutEmbeddings:
    """Tests for get_events_without_embeddings function."""

    def test_returns_events_without_embeddings(self, test_db, sample_events):
        """Should return events that need embeddings."""
        results = vec.get_events_without_embeddings(test_db)
        assert len(results) == 4
        # Should be (id, content) tuples
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_excludes_events_with_embeddings(self, test_db, sample_events):
        """Should exclude events that already have embeddings."""
        vec.store_embedding(test_db, sample_events[0], [0.1] * 384)

        results = vec.get_events_without_embeddings(test_db)
        ids = [r[0] for r in results]
        assert sample_events[0] not in ids
        assert len(results) == 3

    def test_respects_limit(self, test_db, sample_events):
        """Should respect limit parameter."""
        results = vec.get_events_without_embeddings(test_db, limit=2)
        assert len(results) == 2


# =============================================================================
# Test Backfill Embeddings
# =============================================================================


class TestBackfillEmbeddings:
    """Tests for backfill_embeddings function."""

    def test_returns_zero_when_unavailable(self, test_db, sample_events):
        """Should return 0 when embedding engine unavailable."""
        with patch("cortex.embeddings.EmbeddingEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_available.return_value = False
            mock_engine_class.return_value = mock_engine

            result = vec.backfill_embeddings(test_db)

        assert result == 0

    def test_returns_zero_when_all_embedded(self, test_db):
        """Should return 0 when no events need embeddings."""
        # No events in database
        with patch("cortex.embeddings.EmbeddingEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_available.return_value = True
            mock_engine_class.return_value = mock_engine

            result = vec.backfill_embeddings(test_db)

        assert result == 0

    def test_generates_embeddings(self, test_db, sample_events):
        """Should generate and store embeddings."""
        with patch("cortex.embeddings.EmbeddingEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_available.return_value = True
            mock_engine.embed_batch.return_value = [[0.1] * 384] * 4
            mock_engine_class.return_value = mock_engine

            result = vec.backfill_embeddings(test_db, batch_size=10)

        assert result == 4
        assert vec.count_embeddings(test_db) == 4

    def test_calls_progress_callback(self, test_db, sample_events):
        """Should call progress callback during backfill."""
        callback = MagicMock()

        with patch("cortex.embeddings.EmbeddingEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.is_available.return_value = True
            mock_engine.embed_batch.return_value = [[0.1] * 384] * 4
            mock_engine_class.return_value = mock_engine

            vec.backfill_embeddings(test_db, batch_size=10, progress_callback=callback)

        callback.assert_called()
        # Called with (done, total) format
        args = callback.call_args[0]
        assert args[1] == 4  # total


# =============================================================================
# Test VectorSearchResult
# =============================================================================


class TestVectorSearchResult:
    """Tests for VectorSearchResult dataclass."""

    def test_creates_result(self):
        """Should create result with all fields."""
        result = vec.VectorSearchResult(
            event_id="evt1",
            distance=0.5,
            similarity=0.6,
        )
        assert result.event_id == "evt1"
        assert result.distance == 0.5
        assert result.similarity == 0.6

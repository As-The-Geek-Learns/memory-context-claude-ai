"""Embedding generation for Cortex Tier 2.

Uses SentenceTransformers for local embedding generation. Gracefully
degrades to None embeddings if the model is unavailable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Default model: small, fast, good quality
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""

    model_name: str = DEFAULT_MODEL_NAME
    cache_dir: str | None = None
    device: str = "cpu"
    normalize: bool = True


def check_sentence_transformers_available() -> bool:
    """Check if sentence-transformers is installed."""
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


class EmbeddingEngine:
    """Generate embeddings using SentenceTransformers.

    Lazily loads the model on first use. If sentence-transformers is not
    installed or the model fails to load, all methods return None gracefully.

    Example:
        engine = EmbeddingEngine()
        if engine.is_available():
            embedding = engine.embed("Hello world")
            embeddings = engine.embed_batch(["Hello", "World"])
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_dir: str | Path | None = None,
        device: str | None = None,
    ):
        """Initialize embedding engine.

        Args:
            model_name: HuggingFace model name or local path.
            cache_dir: Directory to cache downloaded models.
            device: Device to use ('cpu', 'cuda', 'mps'). Auto-detected if None.
        """
        self._model_name = model_name
        self._cache_dir = str(cache_dir) if cache_dir else None
        self._device = device or self._detect_device()
        self._model: SentenceTransformer | None = None
        self._load_attempted = False
        self._load_error: str | None = None

    @staticmethod
    def _detect_device() -> str:
        """Auto-detect best available device."""
        # Check environment override
        env_device = os.environ.get("CORTEX_EMBEDDING_DEVICE")
        if env_device:
            return env_device

        # Default to CPU for reliability
        # Users can set CORTEX_EMBEDDING_DEVICE=cuda or mps if desired
        return "cpu"

    def _load_model(self) -> bool:
        """Load the model, returning True on success."""
        if self._load_attempted:
            return self._model is not None

        self._load_attempted = True

        if not check_sentence_transformers_available():
            self._load_error = "sentence-transformers not installed"
            logger.warning("sentence-transformers not installed. Install with: pip install sentence-transformers")
            return False

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(
                self._model_name,
                cache_folder=self._cache_dir,
                device=self._device,
            )
            logger.info(f"Embedding model loaded on device: {self._device}")
            return True

        except Exception as e:
            self._load_error = str(e)
            logger.error(f"Failed to load embedding model: {e}")
            return False

    @property
    def model(self) -> SentenceTransformer | None:
        """Get the loaded model, loading it if necessary."""
        if not self._load_attempted:
            self._load_model()
        return self._model

    def is_available(self) -> bool:
        """Check if the embedding engine is ready to use."""
        return self.model is not None

    def get_load_error(self) -> str | None:
        """Get the error message if model failed to load."""
        if not self._load_attempted:
            self._load_model()
        return self._load_error

    @property
    def dimension(self) -> int:
        """Return embedding dimension (384 for all-MiniLM-L6-v2)."""
        return EMBEDDING_DIMENSION

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model_name

    def embed(self, text: str) -> list[float] | None:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            List of floats (embedding vector) or None if unavailable.
        """
        if not self.is_available():
            return None

        if not text or not text.strip():
            return None

        try:
            # SentenceTransformer.encode returns numpy array
            assert self._model is not None  # Checked by is_available()
            embedding = self._model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float] | None]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            batch_size: Number of texts to process at once.
            show_progress: Show progress bar (requires tqdm).

        Returns:
            List of embeddings (or None for empty/failed texts).
        """
        if not self.is_available():
            return [None] * len(texts)

        if not texts:
            return []

        # Track which indices have valid text
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_indices.append(i)
                valid_texts.append(text)

        if not valid_texts:
            return [None] * len(texts)

        try:
            assert self._model is not None  # Checked by is_available()
            embeddings = self._model.encode(
                valid_texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=show_progress,
            )

            # Build result list with None for invalid texts
            result: list[list[float] | None] = [None] * len(texts)
            for idx, emb in zip(valid_indices, embeddings, strict=True):
                result[idx] = emb.tolist()

            return result

        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return [None] * len(texts)

    def similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
    ) -> float:
        """Calculate cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector.
            embedding2: Second embedding vector.

        Returns:
            Cosine similarity (-1 to 1, higher is more similar).
        """
        try:
            import numpy as np

            e1 = np.array(embedding1)
            e2 = np.array(embedding2)

            # Cosine similarity for normalized vectors is just dot product
            return float(np.dot(e1, e2))
        except Exception as e:
            logger.error(f"Similarity calculation failed: {e}")
            return 0.0


# Module-level singleton for convenience
_default_engine: EmbeddingEngine | None = None


def get_embedding_engine(
    model_name: str = DEFAULT_MODEL_NAME,
    cache_dir: str | Path | None = None,
) -> EmbeddingEngine:
    """Get or create the default embedding engine.

    Uses a singleton pattern to avoid loading the model multiple times.
    """
    global _default_engine

    if _default_engine is None:
        _default_engine = EmbeddingEngine(
            model_name=model_name,
            cache_dir=cache_dir,
        )
    return _default_engine


def embed(text: str) -> list[float] | None:
    """Convenience function to embed a single text using the default engine."""
    return get_embedding_engine().embed(text)


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float] | None]:
    """Convenience function to embed multiple texts using the default engine."""
    return get_embedding_engine().embed_batch(texts, batch_size=batch_size)

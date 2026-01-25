"""Semantic memory - In-memory vector store for knowledge retrieval."""
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SemanticMemory:
    """In-memory vector store using simple embeddings and cosine similarity."""

    def __init__(self):
        """Initialize semantic memory."""
        self.documents: List[Tuple[str, np.ndarray, Dict[str, Any]]] = []

    def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a document to semantic memory.

        Args:
            text: Document text
            metadata: Optional metadata dict
        """
        embedding = self._embed(text)
        self.documents.append((text, embedding, metadata or {}))
        logger.debug(f"Added document to semantic memory: {text[:50]}...")

    def add_batch(self, documents: List[Dict[str, Any]]) -> None:
        """Add multiple documents.

        Args:
            documents: List of dicts with 'text' and optional 'metadata' keys
        """
        for doc in documents:
            self.add(doc.get('text', ''), doc.get('metadata'))

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents.

        Args:
            query: Search query
            top_k: Number of results to return

        Returns:
            List of dicts with 'text', 'metadata', and 'score' keys
        """
        if not self.documents:
            return []

        query_embedding = self._embed(query)
        scores = []

        for text, doc_embedding, metadata in self.documents:
            score = self._cosine_similarity(query_embedding, doc_embedding)
            scores.append((text, metadata, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[2], reverse=True)

        # Return top_k results
        results = [
            {
                'text': text,
                'metadata': metadata,
                'score': float(score)
            }
            for text, metadata, score in scores[:top_k]
        ]

        logger.debug(f"Semantic search for '{query[:50]}...' returned {len(results)} results")
        return results

    def _embed(self, text: str) -> np.ndarray:
        """Create simple embedding for text.

        For prototype: use character-based hashing for fast, deterministic embeddings.
        In production: use OpenAI embeddings or sentence transformers.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        # Simple bag-of-words style embedding
        # Create a fixed-size vector based on character frequencies and n-grams
        vector_size = 128
        embedding = np.zeros(vector_size)

        # Character frequency features
        text_lower = text.lower()
        for char in text_lower:
            idx = hash(char) % vector_size
            embedding[idx] += 1

        # Bigram features for better semantic capture
        for i in range(len(text_lower) - 1):
            bigram = text_lower[i:i+2]
            idx = hash(bigram) % vector_size
            embedding[idx] += 0.5

        # Word-level features
        words = text_lower.split()
        for word in words:
            idx = hash(word) % vector_size
            embedding[idx] += 2

        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity score (0-1)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def clear(self) -> None:
        """Clear all documents from memory."""
        self.documents = []
        logger.info("Cleared semantic memory")

    def size(self) -> int:
        """Get number of documents in memory.

        Returns:
            Document count
        """
        return len(self.documents)

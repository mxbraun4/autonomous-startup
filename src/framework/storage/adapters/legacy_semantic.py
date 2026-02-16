"""Legacy adapter wrapping src/memory/semantic.py behind protocol methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.framework.contracts import SemanticDocument
from src.memory.semantic import SemanticMemory
from src.utils.logging import get_logger

logger = get_logger(__name__)


class LegacySemanticAdapter:
    """Wraps the existing in-memory SemanticMemory for protocol compatibility."""

    def __init__(self, backend: Optional[SemanticMemory] = None):
        self._backend = backend or SemanticMemory()

    async def sem_add(self, doc: SemanticDocument) -> str:
        self._backend.add(
            text=doc.text,
            metadata={
                "entity_id": doc.entity_id,
                "collection": doc.collection,
                "document_type": doc.document_type,
                "tags": doc.tags,
                "source": doc.source,
                **doc.metadata,
            },
        )
        return doc.entity_id

    async def sem_search(
        self,
        query: str,
        collection: str = "semantic_default",
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SemanticDocument]:
        raw_results = self._backend.search(query, top_k=top_k * 2)
        docs: List[SemanticDocument] = []
        for r in raw_results:
            meta = r.get("metadata", {})
            if meta.get("collection", "semantic_default") != collection:
                continue
            doc = SemanticDocument(
                entity_id=meta.get("entity_id", ""),
                text=r["text"],
                collection=meta.get("collection", "semantic_default"),
                document_type=meta.get("document_type", "general"),
                tags=meta.get("tags", []),
                source=meta.get("source", ""),
            )
            docs.append(doc)
            if len(docs) >= top_k:
                break
        return docs

    async def sem_get(self, entity_id: str) -> Optional[SemanticDocument]:
        for text, _emb, meta in self._backend.documents:
            if meta.get("entity_id") == entity_id:
                return SemanticDocument(
                    entity_id=entity_id,
                    text=text,
                    collection=meta.get("collection", "semantic_default"),
                    document_type=meta.get("document_type", "general"),
                    tags=meta.get("tags", []),
                    source=meta.get("source", ""),
                )
        return None

    async def sem_delete(self, entity_id: str) -> bool:
        for i, (_text, _emb, meta) in enumerate(self._backend.documents):
            if meta.get("entity_id") == entity_id:
                self._backend.documents.pop(i)
                return True
        return False

    async def sem_count(self, collection: str = "semantic_default") -> int:
        count = 0
        for _text, _emb, meta in self._backend.documents:
            if meta.get("collection", "semantic_default") == collection:
                count += 1
        return count

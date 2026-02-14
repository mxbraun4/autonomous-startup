"""ChromaDB-backed semantic memory backend.

Uses ChromaDB PersistentClient with the default ONNX embedding function
(no PyTorch dependency). Switchable to sentence-transformers via config.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import chromadb

from src.framework.contracts import SemanticDocument
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SemanticStoreBackend:
    """ChromaDB persistent store for semantic documents."""

    def __init__(self, persist_dir: str = "data/memory/chroma"):
        os.makedirs(persist_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(path=persist_dir)
        # Cache of collection name -> chromadb.Collection
        self._collections: Dict[str, chromadb.Collection] = {}
        logger.info(f"SemanticStoreBackend initialised (persist_dir={persist_dir})")

    def _get_collection(self, name: str) -> chromadb.Collection:
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[name]

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def sem_add(self, doc: SemanticDocument) -> str:
        col = self._get_collection(doc.collection)
        meta = {
            "document_type": doc.document_type,
            "source": doc.source,
            "tags": ",".join(doc.tags),
            "timestamp_utc": doc.timestamp_utc.isoformat(),
            **{k: str(v) for k, v in doc.metadata.items()},
        }
        col.upsert(
            ids=[doc.entity_id],
            documents=[doc.text],
            metadatas=[meta],
        )
        return doc.entity_id

    async def sem_search(
        self,
        query: str,
        collection: str = "semantic_default",
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SemanticDocument]:
        col = self._get_collection(collection)
        count = col.count()
        if count == 0:
            return []

        effective_k = min(top_k, count)
        where = self._build_where(filters) if filters else None
        results = col.query(
            query_texts=[query],
            n_results=effective_k,
            where=where,
        )

        docs: List[SemanticDocument] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for eid, text, meta in zip(ids, documents, metadatas):
            tags_str = meta.pop("tags", "")
            tags = [t for t in tags_str.split(",") if t] if tags_str else []
            meta.pop("timestamp_utc", None)
            doc = SemanticDocument(
                entity_id=eid,
                text=text or "",
                collection=collection,
                document_type=meta.pop("document_type", "general"),
                source=meta.pop("source", ""),
                tags=tags,
                metadata=meta,
            )
            docs.append(doc)
        return docs

    async def sem_get(self, entity_id: str) -> Optional[SemanticDocument]:
        # Search across all known collections
        for col_name, col in self._collections.items():
            try:
                result = col.get(ids=[entity_id])
                if result["ids"]:
                    meta = result["metadatas"][0] if result["metadatas"] else {}
                    tags_str = meta.pop("tags", "")
                    tags = [t for t in tags_str.split(",") if t] if tags_str else []
                    meta.pop("timestamp_utc", None)
                    return SemanticDocument(
                        entity_id=entity_id,
                        text=result["documents"][0] if result["documents"] else "",
                        collection=col_name,
                        document_type=meta.pop("document_type", "general"),
                        source=meta.pop("source", ""),
                        tags=tags,
                        metadata=meta,
                    )
            except Exception:
                continue
        return None

    async def sem_delete(self, entity_id: str) -> bool:
        for col in self._collections.values():
            try:
                existing = col.get(ids=[entity_id])
                if existing["ids"]:
                    col.delete(ids=[entity_id])
                    return True
            except Exception:
                continue
        return False

    async def sem_count(self, collection: str = "semantic_default") -> int:
        col = self._get_collection(collection)
        return col.count()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a flat dict of filters into a ChromaDB where clause."""
        if not filters:
            return None
        conditions = []
        for key, value in filters.items():
            conditions.append({key: {"$eq": str(value)}})
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

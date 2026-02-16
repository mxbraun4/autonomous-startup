"""In-memory per-agent working memory with relevance scoring and TTL."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.framework.contracts import WorkingMemoryItem
from src.framework.types import ItemType
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Rough estimate: 1 token ~ 4 characters
_CHARS_PER_TOKEN = 4


class WorkingMemoryBackend:
    """Per-agent in-memory store with time-decay relevance and TTL eviction."""

    def __init__(self, decay_rate: float = 0.95):
        # agent_id -> { entity_id -> WorkingMemoryItem }
        self._store: Dict[str, Dict[str, WorkingMemoryItem]] = {}
        self._decay_rate = decay_rate

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def put(self, item: WorkingMemoryItem) -> str:
        bucket = self._store.setdefault(item.agent_id, {})
        bucket[item.entity_id] = item
        return item.entity_id

    def get(self, agent_id: str, entity_id: str) -> Optional[WorkingMemoryItem]:
        bucket = self._store.get(agent_id, {})
        item = bucket.get(entity_id)
        if item is None:
            return None
        if self._is_expired(item):
            del bucket[entity_id]
            return None
        return item

    def list_items(
        self,
        agent_id: str,
        item_type: Optional[ItemType] = None,
    ) -> List[WorkingMemoryItem]:
        self._evict_expired(agent_id)
        bucket = self._store.get(agent_id, {})
        items = list(bucket.values())
        if item_type is not None:
            items = [i for i in items if i.item_type == item_type]
        return items

    def remove(self, agent_id: str, entity_id: str) -> bool:
        bucket = self._store.get(agent_id, {})
        if entity_id in bucket:
            del bucket[entity_id]
            return True
        return False

    def clear(self, agent_id: str) -> int:
        bucket = self._store.pop(agent_id, {})
        return len(bucket)

    # ------------------------------------------------------------------
    # Relevance scoring
    # ------------------------------------------------------------------

    def effective_relevance(self, item: WorkingMemoryItem) -> float:
        """Relevance with time decay: score * decay_rate ^ minutes_old."""
        age_minutes = (
            datetime.now(timezone.utc) - item.timestamp_utc
        ).total_seconds() / 60.0
        decay = math.pow(self._decay_rate, age_minutes)
        return item.relevance_score * decay

    # ------------------------------------------------------------------
    # Token-budgeted prompt packing
    # ------------------------------------------------------------------

    def get_context_for_prompt(self, agent_id: str, max_tokens: int = 4000) -> str:
        """Pack most-relevant items into a prompt string within budget.

        Uses a greedy approach: sort by effective relevance descending,
        append items until the token budget is exhausted.
        """
        self._evict_expired(agent_id)
        bucket = self._store.get(agent_id, {})
        if not bucket:
            return ""

        scored = [
            (self.effective_relevance(item), item) for item in bucket.values()
        ]
        scored.sort(key=lambda t: t[0], reverse=True)

        max_chars = max_tokens * _CHARS_PER_TOKEN
        parts: List[str] = []
        used = 0

        for _score, item in scored:
            line = self._format_item(item)
            length = len(line)
            if used + length > max_chars:
                break
            parts.append(line)
            used += length

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Checkpoint support
    # ------------------------------------------------------------------

    def save_checkpoint(self, path: str) -> None:
        data: Dict[str, list] = {}
        for agent_id, bucket in self._store.items():
            data[agent_id] = [item.model_dump(mode="json") for item in bucket.values()]
        with open(path, "w") as f:
            json.dump(data, f, default=str)
        logger.info(f"Working memory checkpoint saved to {path}")

    def load_checkpoint(self, path: str) -> None:
        with open(path, "r") as f:
            data = json.load(f)
        self._store.clear()
        for agent_id, items_data in data.items():
            bucket: Dict[str, WorkingMemoryItem] = {}
            for raw in items_data:
                item = WorkingMemoryItem.model_validate(raw)
                bucket[item.entity_id] = item
            self._store[agent_id] = bucket
        logger.info(f"Working memory checkpoint loaded from {path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_expired(item: WorkingMemoryItem) -> bool:
        if item.ttl_seconds is None:
            return False
        age = (datetime.now(timezone.utc) - item.timestamp_utc).total_seconds()
        return age > item.ttl_seconds

    def _evict_expired(self, agent_id: str) -> None:
        bucket = self._store.get(agent_id, {})
        expired = [eid for eid, item in bucket.items() if self._is_expired(item)]
        for eid in expired:
            del bucket[eid]

    @staticmethod
    def _format_item(item: WorkingMemoryItem) -> str:
        content_str = json.dumps(item.content, default=str)
        return f"[{item.item_type.value}] {content_str}"

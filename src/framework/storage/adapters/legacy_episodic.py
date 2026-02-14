"""Legacy adapter wrapping src/memory/episodic.py behind protocol methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.framework.contracts import Episode
from src.framework.types import EpisodeType
from src.memory.episodic import EpisodicMemory
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _safe_episode_type(raw: str) -> EpisodeType:
    try:
        return EpisodeType(raw)
    except ValueError:
        return EpisodeType.GENERAL


class LegacyEpisodicAdapter:
    """Wraps the existing SQLite EpisodicMemory for protocol compatibility."""

    def __init__(self, backend: Optional[EpisodicMemory] = None, db_path: str = "data/memory/episodic.db"):
        self._backend = backend or EpisodicMemory(db_path)

    async def ep_record(self, episode: Episode) -> str:
        row_id = self._backend.record(
            agent_id=episode.agent_id,
            episode_type=episode.episode_type.value,
            context=episode.context,
            outcome=episode.outcome,
            success=episode.success,
            iteration=episode.iteration,
        )
        # Store entity_id mapping in metadata for later retrieval
        return episode.entity_id

    async def ep_get(self, entity_id: str) -> Optional[Episode]:
        # Legacy store doesn't support lookup by entity_id; scan recent rows
        rows = self._backend.search_similar(limit=500)
        for r in rows:
            if str(r.get("id")) == entity_id:
                return self._row_to_episode(r)
        return None

    async def ep_search_similar(
        self,
        query: str,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        top_k: int = 10,
    ) -> List[Episode]:
        keywords = query.split() if query else None
        rows = self._backend.search_similar(
            agent_id=agent_id,
            episode_type=episode_type.value if episode_type else None,
            context_keywords=keywords,
            limit=top_k,
        )
        return [self._row_to_episode(r) for r in rows]

    async def ep_search_structured(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Episode]:
        rows = self._backend.search_similar(
            agent_id=agent_id,
            episode_type=episode_type.value if episode_type else None,
            success_only=success_only,
            limit=limit,
        )
        return [self._row_to_episode(r) for r in rows]

    async def ep_get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> float:
        return self._backend.get_success_rate(
            agent_id=agent_id,
            episode_type=episode_type.value if episode_type else None,
        )

    @staticmethod
    def _row_to_episode(row: Dict[str, Any]) -> Episode:
        return Episode(
            entity_id=str(row.get("id", "")),
            agent_id=row.get("agent_id", ""),
            episode_type=_safe_episode_type(row.get("episode_type", "general")),
            context=row.get("context", {}),
            outcome=row.get("outcome", {}),
            success=row.get("success", False),
            iteration=row.get("iteration", 0),
        )

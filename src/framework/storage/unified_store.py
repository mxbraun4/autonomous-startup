"""UnifiedStore - in-process implementation of MemoryStoreProtocol.

Composes episodic, procedural, and consensus memory backends and delegates each method group.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from src.framework.contracts import (
    ConsensusEntry,
    Episode,
    Procedure,
)
from src.framework.storage.protocol import MemoryStoreProtocol
from src.framework.types import EntryType, EpisodeType
from src.utils.logging import get_logger

logger = get_logger(__name__)


class UnifiedStore(MemoryStoreProtocol):
    """In-process facade that routes to tier-specific backends.

    Parameters
    ----------
    data_dir : str
        Root directory for persistent data.
    """

    def __init__(self, data_dir: str = "data/memory"):
        self._data_dir = data_dir
        self._current_run_id: Optional[str] = None

        # Episodic
        from src.framework.storage.backends.episodic_store import EpisodicStoreBackend

        self._episodic = EpisodicStoreBackend(
            db_path=os.path.join(data_dir, "episodic_v2.db"),
            chroma_dir=os.path.join(data_dir, "chroma"),
        )

        # Procedural
        from src.framework.storage.backends.procedural_store import ProceduralStoreBackend

        self._procedural = ProceduralStoreBackend(
            db_path=os.path.join(data_dir, "procedural.db"),
        )

        # Consensus
        from src.framework.storage.backends.consensus_store import ConsensusStoreBackend

        self._consensus = ConsensusStoreBackend(
            db_path=os.path.join(data_dir, "consensus.db"),
        )

        logger.info("UnifiedStore initialised (data_dir=%s)", data_dir)

    # -- context-manager & cleanup ------------------------------------------

    def close(self) -> None:
        """Close all backend connections (idempotent)."""
        for backend in (self._episodic, self._procedural, self._consensus):
            try:
                backend.close()
            except Exception:
                pass

    def __enter__(self) -> "UnifiedStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    async def __aenter__(self) -> "UnifiedStore":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_run(self, run_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self._current_run_id = run_id
        logger.info("Run started: %s", run_id)

    async def end_run(self, run_id: str) -> None:
        self._current_run_id = None
        logger.info("Run ended: %s", run_id)

    # ------------------------------------------------------------------
    # Episodic Memory - delegates to backend
    # ------------------------------------------------------------------

    async def ep_record(self, episode: Episode) -> str:
        if self._current_run_id and not episode.run_id:
            episode.run_id = self._current_run_id
        return await self._episodic.ep_record(episode)

    async def ep_get(self, entity_id: str) -> Optional[Episode]:
        return await self._episodic.ep_get(entity_id)

    async def ep_search_similar(
        self,
        query: str,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        top_k: int = 10,
    ) -> List[Episode]:
        return await self._episodic.ep_search_similar(query, agent_id, episode_type, top_k)

    async def ep_search_structured(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Episode]:
        return await self._episodic.ep_search_structured(agent_id, episode_type, success_only, limit)

    async def ep_get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> float:
        return await self._episodic.ep_get_success_rate(agent_id, episode_type)

    # ------------------------------------------------------------------
    # Procedural Memory - delegates to backend
    # ------------------------------------------------------------------

    async def proc_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float = 0.0,
        created_by: str = "",
        provenance: str = "",
    ) -> Procedure:
        return await self._procedural.proc_save(task_type, workflow, score, created_by, provenance)

    async def proc_get(self, task_type: str) -> Optional[Procedure]:
        return await self._procedural.proc_get(task_type)

    async def proc_get_history(self, task_type: str) -> List[Procedure]:
        return await self._procedural.proc_get_history(task_type)

    async def proc_list_types(self) -> List[str]:
        return await self._procedural.proc_list_types()

    # ------------------------------------------------------------------
    # Consensus Memory - delegates to backend
    # ------------------------------------------------------------------

    async def cons_set(self, entry: ConsensusEntry) -> str:
        if self._current_run_id and not entry.run_id:
            entry.run_id = self._current_run_id
        return await self._consensus.cons_set(entry)

    async def cons_get(self, key: str) -> Optional[ConsensusEntry]:
        return await self._consensus.cons_get(key)

    async def cons_propose(self, entry: ConsensusEntry) -> str:
        if self._current_run_id and not entry.run_id:
            entry.run_id = self._current_run_id
        return await self._consensus.cons_propose(entry)

    async def cons_approve(self, entity_id: str) -> bool:
        return await self._consensus.cons_approve(entity_id)

    async def cons_list(
        self,
        prefix: Optional[str] = None,
        entry_type: Optional[EntryType] = None,
    ) -> List[ConsensusEntry]:
        return await self._consensus.cons_list(prefix, entry_type)

    async def cons_history(self, key: str) -> List[ConsensusEntry]:
        return await self._consensus.cons_history(key)

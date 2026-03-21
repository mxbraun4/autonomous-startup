"""Synchronous wrapper around UnifiedStore for use in CrewAI tools.

CrewAI tool functions are synchronous, so this wrapper runs async methods
via ``asyncio.run()`` (or a private event loop if one is already running).
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
from typing import Any, Dict, List, Optional

from src.framework.contracts import (
    ConsensusEntry,
    Episode,
    Procedure,
)
from src.framework.storage.unified_store import UnifiedStore
from src.framework.types import EntryType, EpisodeType

# Module-level pool reused across all _run() calls when an event loop is
# already running.  Lazily initialised; cleaned up via atexit.
_FALLBACK_POOL: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _get_fallback_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _FALLBACK_POOL
    if _FALLBACK_POOL is None:
        _FALLBACK_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    return _FALLBACK_POOL


def _shutdown_pool() -> None:
    global _FALLBACK_POOL
    if _FALLBACK_POOL is not None:
        _FALLBACK_POOL.shutdown(wait=False)
        _FALLBACK_POOL = None


atexit.register(_shutdown_pool)


def _run(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from synchronous code.

    Uses ``asyncio.run()`` when no loop is running, otherwise dispatches
    to a cached background thread with its own loop so we never nest
    ``run()``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    # An event loop is already running (e.g. Jupyter / some frameworks).
    future = _get_fallback_pool().submit(asyncio.run, coro)
    return future.result()


class SyncUnifiedStore:
    """Synchronous facade over :class:`UnifiedStore`.

    Every method mirrors the async protocol but blocks until complete.
    """

    def __init__(self, store: UnifiedStore):
        self._store = store

    @property
    def async_store(self) -> UnifiedStore:
        """Access the underlying async store if needed."""
        return self._store

    # -- context-manager & cleanup ------------------------------------------

    def close(self) -> None:
        """Close the underlying async store (idempotent)."""
        self._store.close()

    def __enter__(self) -> "SyncUnifiedStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_run(self, run_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        _run(self._store.start_run(run_id, metadata))

    def end_run(self, run_id: str) -> None:
        _run(self._store.end_run(run_id))

    # ------------------------------------------------------------------
    # Episodic Memory
    # ------------------------------------------------------------------

    def ep_record(self, episode: Episode) -> str:
        return _run(self._store.ep_record(episode))

    def ep_get(self, entity_id: str) -> Optional[Episode]:
        return _run(self._store.ep_get(entity_id))

    def ep_search_similar(
        self,
        query: str,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        top_k: int = 10,
    ) -> List[Episode]:
        return _run(self._store.ep_search_similar(query, agent_id, episode_type, top_k))

    def ep_search_structured(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Episode]:
        return _run(self._store.ep_search_structured(agent_id, episode_type, success_only, limit))

    def ep_get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> float:
        return _run(self._store.ep_get_success_rate(agent_id, episode_type))

    # ------------------------------------------------------------------
    # Procedural Memory
    # ------------------------------------------------------------------

    def proc_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float = 0.0,
        created_by: str = "",
        provenance: str = "",
    ) -> Procedure:
        return _run(self._store.proc_save(task_type, workflow, score, created_by, provenance))

    def proc_get(self, task_type: str) -> Optional[Procedure]:
        return _run(self._store.proc_get(task_type))

    def proc_get_history(self, task_type: str) -> List[Procedure]:
        return _run(self._store.proc_get_history(task_type))

    def proc_list_types(self) -> List[str]:
        return _run(self._store.proc_list_types())

    # ------------------------------------------------------------------
    # Consensus Memory
    # ------------------------------------------------------------------

    def cons_set(self, entry: ConsensusEntry) -> str:
        return _run(self._store.cons_set(entry))

    def cons_get(self, key: str) -> Optional[ConsensusEntry]:
        return _run(self._store.cons_get(key))

    def cons_propose(self, entry: ConsensusEntry) -> str:
        return _run(self._store.cons_propose(entry))

    def cons_approve(self, entity_id: str) -> bool:
        return _run(self._store.cons_approve(entity_id))

    def cons_list(
        self,
        prefix: Optional[str] = None,
        entry_type: Optional[EntryType] = None,
    ) -> List[ConsensusEntry]:
        return _run(self._store.cons_list(prefix, entry_type))

    def cons_history(self, key: str) -> List[ConsensusEntry]:
        return _run(self._store.cons_history(key))

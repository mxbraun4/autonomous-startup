"""Legacy adapter wrapping src/memory/procedural.py behind protocol methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.framework.contracts import Procedure, ProcedureVersion
from src.memory.procedural import ProceduralMemory
from src.utils.logging import get_logger

logger = get_logger(__name__)


class LegacyProceduralAdapter:
    """Wraps the existing JSON-based ProceduralMemory for protocol compatibility."""

    def __init__(
        self,
        backend: Optional[ProceduralMemory] = None,
        file_path: str = "data/memory/workflows.json",
    ):
        self._backend = backend or ProceduralMemory(file_path)

    async def proc_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float = 0.0,
        created_by: str = "",
        provenance: str = "",
    ) -> Procedure:
        self._backend.save_workflow(
            task_type=task_type,
            workflow=workflow,
            performance_score=score,
        )
        return await self.proc_get(task_type)  # type: ignore[return-value]

    async def proc_get(self, task_type: str) -> Optional[Procedure]:
        raw = self._backend.get_workflow(task_type)
        if raw is None:
            return None
        version = ProcedureVersion(
            version=1,
            workflow=raw.get("workflow", {}),
            score=raw.get("score", 0.0),
            is_active=True,
        )
        return Procedure(
            task_type=task_type,
            current_version=1,
            versions=[version],
        )

    async def proc_get_history(self, task_type: str) -> List[Procedure]:
        proc = await self.proc_get(task_type)
        return [proc] if proc else []

    async def proc_rollback(self, task_type: str, target_version: int) -> Optional[Procedure]:
        # Legacy store doesn't support versioning; no-op
        logger.warning("proc_rollback not supported on legacy adapter")
        return await self.proc_get(task_type)

    async def proc_list_types(self) -> List[str]:
        return list(self._backend.get_all_workflows().keys())

"""Procedure updater that writes versioned workflows via store API."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from src.framework.contracts import EvaluationResult, Procedure


def _resolve(value: Any) -> Any:
    """Resolve awaitables from sync contexts."""
    if not asyncio.iscoroutine(value):
        return value

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(value)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, value)
        return future.result()


class ProcedureUpdateProposal(BaseModel):
    """Proposed procedure update payload."""

    task_type: str
    workflow: Dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    created_by: str = "procedure_updater"
    provenance: str = ""
    source_evidence: Dict[str, Any] = Field(default_factory=dict)


class ProcedureUpdater:
    """Generate/apply reversible procedural updates through store methods."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def propose_update(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float,
        evaluation_result: Optional[EvaluationResult] = None,
        source_evidence: Optional[Dict[str, Any]] = None,
        created_by: str = "procedure_updater",
    ) -> ProcedureUpdateProposal:
        """Create an update proposal from workflow/evaluation evidence."""
        evidence = dict(source_evidence or {})
        provenance = "manual_update"
        if evaluation_result is not None:
            evidence.setdefault("evaluation_result_id", evaluation_result.entity_id)
            evidence.setdefault("evaluation_status", evaluation_result.overall_status)
            evidence.setdefault("recommended_action", evaluation_result.recommended_action)
            provenance = (
                "evaluation:"
                f"{evaluation_result.overall_status}/"
                f"{evaluation_result.recommended_action}"
            )

        return ProcedureUpdateProposal(
            task_type=task_type,
            workflow=dict(workflow),
            score=float(score),
            created_by=created_by,
            provenance=provenance,
            source_evidence=evidence,
        )

    def apply_update(self, proposal: ProcedureUpdateProposal) -> Procedure:
        """Persist a new procedure version via store proc_save()."""
        result = self._store.proc_save(
            task_type=proposal.task_type,
            workflow=proposal.workflow,
            score=proposal.score,
            created_by=proposal.created_by,
            provenance=proposal.provenance,
        )
        return _resolve(result)

    def rollback(self, task_type: str, target_version: int) -> Optional[Procedure]:
        """Rollback procedure to a prior version via store proc_rollback()."""
        result = self._store.proc_rollback(task_type, target_version)
        return _resolve(result)


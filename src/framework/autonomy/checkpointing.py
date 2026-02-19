"""Checkpoint save/load helpers for the autonomy controller."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

from src.framework.contracts import Checkpoint, RunConfig
from src.framework.runtime.execution_context import ExecutionContext


def _resolve(value: Any) -> Any:
    """Resolve awaitables from synchronous contexts."""
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


class CheckpointLoadResult(BaseModel):
    """Result from loading a checkpoint file."""

    checkpoint_path: str
    checkpoint: Checkpoint
    context: ExecutionContext

    model_config = {"arbitrary_types_allowed": True}


class CheckpointManager:
    """Persist/restore execution context and optional store checkpoints."""

    def __init__(
        self,
        checkpoint_dir: str = "data/memory/checkpoints",
        store: Any = None,
        event_emitter: Any = None,
    ) -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._store = store
        self._event_emitter = event_emitter

    def save(
        self,
        *,
        context: ExecutionContext,
        pending_tasks: Optional[list[str]] = None,
        completed_tasks: Optional[list[str]] = None,
    ) -> str:
        """Save execution context checkpoint and optional store snapshot."""
        checkpoint = context.to_checkpoint()
        checkpoint.pending_tasks = list(pending_tasks or [])
        checkpoint.completed_tasks = list(completed_tasks or [])

        stem = (
            f"{checkpoint.run_id}_cycle_{checkpoint.cycle_id}_step_{checkpoint.step_count}"
        )
        checkpoint_path = self._dir / f"{stem}.json"

        working_memory_path = self._dir / f"{stem}.wm.json"
        if self._store is not None and hasattr(self._store, "save_checkpoint"):
            _resolve(self._store.save_checkpoint(checkpoint.run_id, str(working_memory_path)))
            checkpoint.working_memory_path = str(working_memory_path)

        checkpoint_data = checkpoint.model_dump(mode="json")
        checkpoint_path.write_text(
            json.dumps(checkpoint_data, indent=2),
            encoding="utf-8",
        )
        self._emit(
            "checkpoint_saved",
            {
                "run_id": checkpoint.run_id,
                "cycle_id": checkpoint.cycle_id,
                "checkpoint_path": str(checkpoint_path),
            },
        )
        return str(checkpoint_path)

    def load(
        self,
        *,
        checkpoint_path: str,
        run_config: RunConfig,
    ) -> CheckpointLoadResult:
        """Load checkpoint file and restore execution context."""
        raw = Path(checkpoint_path).read_text(encoding="utf-8")
        checkpoint = Checkpoint.model_validate(json.loads(raw))

        if (
            self._store is not None
            and checkpoint.working_memory_path
            and hasattr(self._store, "load_checkpoint")
        ):
            _resolve(self._store.load_checkpoint(checkpoint.run_id, checkpoint.working_memory_path))

        context = ExecutionContext.from_checkpoint(
            checkpoint=checkpoint,
            run_config=run_config,
            store=self._store,
        )

        self._emit(
            "checkpoint_restored",
            {
                "run_id": checkpoint.run_id,
                "cycle_id": checkpoint.cycle_id,
                "checkpoint_path": checkpoint_path,
            },
        )

        return CheckpointLoadResult(
            checkpoint_path=checkpoint_path,
            checkpoint=checkpoint,
            context=context,
        )

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit(event_type, payload)
            except Exception:
                pass

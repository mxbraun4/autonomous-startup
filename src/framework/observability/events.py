"""Event models for observability and replay."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_serializer


EVENT_TYPES_REQUIRED = {
    "run_start",
    "run_end",
    "cycle_start",
    "cycle_end",
    "task_scheduled",
    "task_started",
    "task_completed",
    "task_failed",
    "tool_called",
    "tool_result",
    "gate_decision",
    "policy_violation",
    "checkpoint_saved",
    "checkpoint_restored",
    "policy_patch_applied",
    "procedure_updated",
    "agent_reasoning",
    "llm_call",
    "agent_exchange",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class ObservabilityEvent(BaseModel):
    """Canonical event record for logging, timeline, and replay."""

    event_id: str = Field(default_factory=_new_id)
    sequence: int = 0
    event_type: str
    run_id: Optional[str] = None
    cycle_id: Optional[int] = None
    timestamp_utc: datetime = Field(default_factory=_utc_now)
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_serializer("timestamp_utc")
    @classmethod
    def _serialize_dt(cls, value: datetime) -> str:
        return value.isoformat()


def create_event(
    *,
    sequence: int,
    event_type: str,
    run_id: Optional[str],
    cycle_id: Optional[int],
    payload: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> ObservabilityEvent:
    """Build a canonical observability event."""
    return ObservabilityEvent(
        sequence=sequence,
        event_type=event_type,
        run_id=run_id,
        cycle_id=cycle_id,
        payload=payload,
        metadata=metadata or {},
    )


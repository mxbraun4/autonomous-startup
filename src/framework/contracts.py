"""Pydantic V2 data models for all five memory types."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer

from src.framework.types import (
    ConsensusStatus,
    EntryType,
    EpisodeType,
    ErrorCategory,
    TaskStatus,
    ToolCallStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class BaseMemoryEntity(BaseModel):
    """Base for all memory entities (Layer A fields)."""

    entity_id: str = Field(default_factory=_new_id)
    run_id: Optional[str] = None
    cycle_id: Optional[int] = None
    timestamp_utc: datetime = Field(default_factory=_utc_now)
    version: int = 1
    status: str = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_serializer("timestamp_utc")
    @classmethod
    def _serialize_dt(cls, v: datetime) -> str:
        return v.isoformat()


# ---------------------------------------------------------------------------
# Episodic Memory
# ---------------------------------------------------------------------------


class Episode(BaseMemoryEntity):
    """Record of an agent action and its outcome."""

    agent_id: str
    episode_type: EpisodeType = EpisodeType.GENERAL
    context: Dict[str, Any] = Field(default_factory=dict)
    action: str = ""
    outcome: Dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    summary_text: str = ""
    tags: List[str] = Field(default_factory=list)
    iteration: int = 0


# ---------------------------------------------------------------------------
# Procedural Memory
# ---------------------------------------------------------------------------


class ProcedureVersion(BaseModel):
    """A single version snapshot of a procedure."""

    version: int
    workflow: Dict[str, Any]
    score: float = 0.0
    created_by: str = ""
    provenance: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)

    @field_serializer("created_at")
    @classmethod
    def _serialize_dt(cls, v: datetime) -> str:
        return v.isoformat()


class Procedure(BaseMemoryEntity):
    """A versioned procedure/workflow for a task type."""

    task_type: str
    current_version: int = 1
    versions: List[ProcedureVersion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Consensus Memory
# ---------------------------------------------------------------------------


class ConsensusEntry(BaseMemoryEntity):
    """A shared-knowledge entry agreed upon by agents."""

    key: str  # namespaced, e.g. "strategy.target_sector"
    value: Any = None
    entry_type: EntryType = EntryType.FACT
    confidence: float = 1.0
    source_agent_id: str = ""
    source_evidence: List[str] = Field(default_factory=list)
    supersedes: Optional[str] = None  # entity_id of the entry this replaces
    consensus_status: ConsensusStatus = ConsensusStatus.APPROVED


# ---------------------------------------------------------------------------
# Runtime / Orchestration Contracts (Layer A completion)
# ---------------------------------------------------------------------------


class RunConfig(BaseMemoryEntity):
    """Immutable configuration for a single autonomous run."""

    seed: int = 42
    max_cycles: int = 10
    max_steps_per_cycle: int = 100
    budget_seconds: Optional[float] = None
    budget_tokens: Optional[int] = None
    domain_adapter: str = "default"
    autonomy_level: int = 0
    policies: Dict[str, Any] = Field(default_factory=dict)
    schedules: List[Dict[str, Any]] = Field(default_factory=list)
    max_delegation_depth: int = 3


class TaskSpec(BaseMemoryEntity):
    """Typed description of work to be done by an agent."""

    task_id: str = Field(default_factory=_new_id)
    objective: str = ""
    agent_role: str = ""
    required_capabilities: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    expected_output_schema: Optional[Dict[str, Any]] = None
    delegated_by: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    priority: int = 0


class TaskResult(BaseMemoryEntity):
    """Typed output produced after a task completes or fails."""

    task_id: str = ""
    agent_id: str = ""
    task_status: TaskStatus = TaskStatus.COMPLETED
    output: Dict[str, Any] = Field(default_factory=dict)
    output_text: str = ""
    error: Optional[str] = None
    error_category: Optional[ErrorCategory] = None
    tool_calls: List[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    tokens_used: int = 0
    retries: int = 0


class ToolCall(BaseMemoryEntity):
    """Record of a single tool invocation."""

    tool_name: str = ""
    capability: str = ""
    caller_agent_id: str = ""
    caller_task_id: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_status: ToolCallStatus = ToolCallStatus.SUCCESS
    result: Any = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    policy_check_passed: bool = True
    denied_reason: Optional[str] = None


class AgentDecision(BaseMemoryEntity):
    """Structured record of an agent's reasoning and choices."""

    agent_id: str = ""
    task_id: str = ""
    decision_type: str = ""
    reasoning: str = ""
    chosen_action: str = ""
    alternatives_considered: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class CycleMetrics(BaseMemoryEntity):
    """Domain-agnostic aggregated metrics for one complete BML cycle."""

    cycle_id: int = 0
    task_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    tokens_used: int = 0
    duration_seconds: float = 0.0
    domain_metrics: Dict[str, Any] = Field(default_factory=dict)


class GateDecision(BaseMemoryEntity):
    """Single gate verdict in an evaluation."""

    gate_name: str = ""
    gate_status: str = "pass"  # pass / warn / fail
    evidence: Dict[str, Any] = Field(default_factory=dict)
    recommended_action: str = "continue"


class EvaluationResult(BaseMemoryEntity):
    """Scorecard output with gate decisions."""

    gates: List[GateDecision] = Field(default_factory=list)
    overall_status: str = "pass"
    summary: str = ""
    recommended_action: str = "continue"



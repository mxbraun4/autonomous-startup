"""Framework - Storage, evaluation, learning, and observability."""

from src.framework.types import (
    ConsensusStatus,
    EntryType,
    EpisodeType,
    ErrorCategory,
    ItemType,
    MemoryType,
    TaskStatus,
    ToolCallStatus,
)
from src.framework.contracts import (
    AgentDecision,
    BaseMemoryEntity,
    ConsensusEntry,
    CycleMetrics,
    Episode,
    EvaluationResult,
    GateDecision,
    Procedure,
    ProcedureVersion,
    RunConfig,
    SemanticDocument,
    TaskResult,
    TaskSpec,
    ToolCall,
    WorkingMemoryItem,
)
from src.framework.eval import Evaluator, GateThresholds, Scorecard, build_scorecard
from src.framework.learning import (
    PolicyPatch,
    PolicyUpdater,
    ProcedureUpdateProposal,
    ProcedureUpdater,
)
from src.framework.observability import (
    EVENT_TYPES_REQUIRED,
    EventLogger,
    ObservabilityEvent,
    create_event,
)

__all__ = [
    # Types / Enums
    "ConsensusStatus",
    "EntryType",
    "EpisodeType",
    "ErrorCategory",
    "ItemType",
    "MemoryType",
    "TaskStatus",
    "ToolCallStatus",
    # Contracts
    "AgentDecision",
    "BaseMemoryEntity",
    "ConsensusEntry",
    "CycleMetrics",
    "Episode",
    "EvaluationResult",
    "GateDecision",
    "Procedure",
    "ProcedureVersion",
    "RunConfig",
    "SemanticDocument",
    "TaskResult",
    "TaskSpec",
    "ToolCall",
    "WorkingMemoryItem",
    # Eval
    "Evaluator",
    "GateThresholds",
    "Scorecard",
    "build_scorecard",
    # Learning
    "PolicyPatch",
    "PolicyUpdater",
    "ProcedureUpdateProposal",
    "ProcedureUpdater",
    # Observability
    "EVENT_TYPES_REQUIRED",
    "EventLogger",
    "ObservabilityEvent",
    "create_event",
]

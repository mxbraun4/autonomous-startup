"""Enums and type definitions for the memory system."""

from enum import Enum


class MemoryType(str, Enum):
    """Five-tier memory types."""

    WORKING = "working"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    CONSENSUS = "consensus"


class EntryType(str, Enum):
    """Consensus entry types."""

    FACT = "fact"
    DECISION = "decision"
    STRATEGY = "strategy"
    PARAMETER = "parameter"


class ItemType(str, Enum):
    """Working memory item types."""

    TASK_STATE = "task_state"
    RETRIEVED_FACT = "retrieved_fact"
    REASONING_STEP = "reasoning_step"
    INTERMEDIATE_RESULT = "intermediate_result"


class EpisodeType(str, Enum):
    """Episode types for episodic memory."""

    DATA_COLLECTION = "data_collection"
    OUTREACH = "outreach"
    VC_MATCHING = "vc_matching"
    TOOL_BUILDING = "tool_building"
    ANALYSIS = "analysis"
    LEARNING = "learning"
    GENERAL = "general"


class ConsensusStatus(str, Enum):
    """Status of a consensus entry."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolCallStatus(str, Enum):
    """Outcome of a tool invocation."""

    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


class ErrorCategory(str, Enum):
    """Classification of task/runtime errors."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    BUDGET_EXCEEDED = "budget_exceeded"
    POLICY_VIOLATION = "policy_violation"
    UNRESOLVABLE_CAPABILITY = "unresolvable_capability"

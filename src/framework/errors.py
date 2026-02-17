"""Error types for the memory system."""


class MemoryStoreError(Exception):
    """Base exception for memory store operations."""

    def __init__(self, message: str, store_type: str = "unknown"):
        self.store_type = store_type
        super().__init__(f"[{store_type}] {message}")


class EntityNotFoundError(MemoryStoreError):
    """Raised when an entity is not found in the store."""

    def __init__(self, entity_id: str, store_type: str = "unknown"):
        self.entity_id = entity_id
        super().__init__(f"Entity not found: {entity_id}", store_type)


class StoreConnectionError(MemoryStoreError):
    """Raised when a store connection fails."""

    def __init__(self, message: str, store_type: str = "unknown"):
        super().__init__(f"Connection error: {message}", store_type)


class ValidationError(MemoryStoreError):
    """Raised when data validation fails."""

    def __init__(self, message: str, store_type: str = "unknown"):
        super().__init__(f"Validation error: {message}", store_type)


# ---------------------------------------------------------------------------
# Agent Runtime Errors (separate hierarchy from MemoryStoreError)
# ---------------------------------------------------------------------------


class AgentRuntimeError(Exception):
    """Base exception for agent runtime operations."""

    def __init__(self, message: str, run_id: str = ""):
        self.run_id = run_id
        super().__init__(message)


class BudgetExhaustedError(AgentRuntimeError):
    """Raised when a budget (time, tokens, steps) is exhausted."""

    def __init__(self, message: str = "Budget exhausted", run_id: str = ""):
        super().__init__(message, run_id)


class PolicyViolationError(AgentRuntimeError):
    """Raised when an action violates a policy."""

    def __init__(self, message: str = "Policy violation", run_id: str = ""):
        super().__init__(message, run_id)


class CapabilityNotFoundError(AgentRuntimeError):
    """Raised when a required capability cannot be resolved."""

    def __init__(self, capability: str, run_id: str = ""):
        self.capability = capability
        super().__init__(f"Capability not found: {capability}", run_id)


class TaskRoutingError(AgentRuntimeError):
    """Raised when a task cannot be routed to any agent."""

    def __init__(self, message: str = "No agent found for task", run_id: str = ""):
        super().__init__(message, run_id)


# ---------------------------------------------------------------------------
# Orchestration Errors (Layer D)
# ---------------------------------------------------------------------------


class OrchestrationError(AgentRuntimeError):
    """Base exception for orchestration operations."""

    def __init__(self, message: str = "Orchestration error", run_id: str = ""):
        super().__init__(message, run_id)


class CycleDetectedError(OrchestrationError):
    """Raised when the task DAG contains a cycle."""

    def __init__(self, cycle_path: list[str], run_id: str = ""):
        self.cycle_path = cycle_path
        super().__init__(
            f"Cycle detected in task graph: {' -> '.join(cycle_path)}",
            run_id,
        )


class DeadlockError(OrchestrationError):
    """Raised when no tasks are ready but the graph is not complete."""

    def __init__(self, blocked_tasks: list[str], run_id: str = ""):
        self.blocked_tasks = blocked_tasks
        super().__init__(
            f"Deadlock: no ready tasks, blocked tasks: {blocked_tasks}",
            run_id,
        )

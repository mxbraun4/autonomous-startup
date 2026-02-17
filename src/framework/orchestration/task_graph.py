"""Task DAG with node state machine and dependency tracking.

TaskNode wraps a TaskSpec with mutable execution state. TaskGraph holds the
full DAG, validates it (cycle + dangling-dep detection), and provides
ready-task iteration and dependent-skipping.

State machine::

    PENDING -> READY         (get_ready_tasks)
    READY   -> RUNNING       (mark_running)
    RUNNING -> COMPLETED     (mark_completed)
    RUNNING -> FAILED        (mark_failed)
    RUNNING -> PENDING       (reset_to_pending — retry)
    PENDING -> SKIPPED       (skip_dependents)
    READY   -> SKIPPED       (skip_dependents)
"""

from collections import deque
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.contracts import TaskResult, TaskSpec
from src.framework.errors import CycleDetectedError
from src.framework.types import TaskStatus


class TaskNode(BaseModel):
    """Wraps a :class:`TaskSpec` with mutable execution state."""

    model_config = {"arbitrary_types_allowed": True}

    task_spec: TaskSpec
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[TaskResult] = None
    retry_count: int = 0

    @property
    def task_id(self) -> str:
        return self.task_spec.task_id


class TaskGraph:
    """Directed acyclic graph of tasks with dependency edges.

    Nodes are :class:`TaskNode` instances keyed by task_id.
    Edges encode ``depends_on`` relationships: if task B depends on task A,
    there is an edge A -> B (A must complete before B becomes ready).
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, TaskNode] = {}
        # forward edges: task_id -> list of task_ids that depend on it
        self._dependents: Dict[str, List[str]] = {}
        # reverse edges: task_id -> list of task_ids it depends on
        self._dependencies: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_tasks(self, task_specs: List[TaskSpec]) -> None:
        """Build nodes and edges from a list of TaskSpecs, then validate."""
        for spec in task_specs:
            node = TaskNode(task_spec=spec)
            self._nodes[spec.task_id] = node
            self._dependents.setdefault(spec.task_id, [])
            self._dependencies[spec.task_id] = list(spec.depends_on)

        # Build forward edges
        for spec in task_specs:
            for dep_id in spec.depends_on:
                self._dependents.setdefault(dep_id, [])
                self._dependents[dep_id].append(spec.task_id)

        self.validate()

    def validate(self) -> None:
        """Check for cycles and dangling dependencies.

        Raises
        ------
        CycleDetectedError
            If the dependency graph contains a cycle.
        ValueError
            If a task depends on a non-existent task.
        """
        # Dangling dependency check
        for task_id, deps in self._dependencies.items():
            for dep_id in deps:
                if dep_id not in self._nodes:
                    raise ValueError(
                        f"Task '{task_id}' depends on unknown task '{dep_id}'"
                    )

        # Cycle detection via Kahn's algorithm
        in_degree: Dict[str, int] = {tid: 0 for tid in self._nodes}
        for tid, deps in self._dependencies.items():
            in_degree[tid] = len(deps)

        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited_count = 0

        while queue:
            tid = queue.popleft()
            visited_count += 1
            for dependent in self._dependents.get(tid, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if visited_count != len(self._nodes):
            # Find nodes in the cycle for the error message
            cycle_nodes = [tid for tid, deg in in_degree.items() if deg > 0]
            raise CycleDetectedError(cycle_path=cycle_nodes)

    # ------------------------------------------------------------------
    # Node access
    # ------------------------------------------------------------------

    def get_node(self, task_id: str) -> TaskNode:
        """Return the node for the given task_id."""
        return self._nodes[task_id]

    @property
    def nodes(self) -> Dict[str, TaskNode]:
        return self._nodes

    # ------------------------------------------------------------------
    # Ready-task iteration
    # ------------------------------------------------------------------

    def get_ready_tasks(self) -> List[TaskNode]:
        """Return nodes that are ready to execute.

        Transitions PENDING nodes with all deps COMPLETED to READY, and
        also returns nodes already in READY state (from a previous call
        that were not yet picked up by the scheduler).
        """
        ready: List[TaskNode] = []
        for tid, node in self._nodes.items():
            if node.status == TaskStatus.READY:
                ready.append(node)
            elif node.status == TaskStatus.PENDING:
                deps = self._dependencies.get(tid, [])
                if all(self._nodes[d].status == TaskStatus.COMPLETED for d in deps):
                    node.status = TaskStatus.READY
                    ready.append(node)
        return ready

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def mark_running(self, task_id: str) -> None:
        node = self._nodes[task_id]
        assert node.status == TaskStatus.READY, (
            f"Cannot mark {task_id} RUNNING from {node.status}"
        )
        node.status = TaskStatus.RUNNING

    def mark_completed(self, task_id: str, result: TaskResult) -> None:
        node = self._nodes[task_id]
        assert node.status == TaskStatus.RUNNING, (
            f"Cannot mark {task_id} COMPLETED from {node.status}"
        )
        node.status = TaskStatus.COMPLETED
        node.result = result

    def mark_failed(self, task_id: str, result: TaskResult) -> None:
        node = self._nodes[task_id]
        assert node.status == TaskStatus.RUNNING, (
            f"Cannot mark {task_id} FAILED from {node.status}"
        )
        node.status = TaskStatus.FAILED
        node.result = result

    def mark_skipped(self, task_id: str) -> None:
        node = self._nodes[task_id]
        assert node.status in (TaskStatus.PENDING, TaskStatus.READY), (
            f"Cannot mark {task_id} SKIPPED from {node.status}"
        )
        node.status = TaskStatus.SKIPPED

    def reset_to_pending(self, task_id: str) -> None:
        """Reset a RUNNING node back to PENDING for retry."""
        node = self._nodes[task_id]
        assert node.status == TaskStatus.RUNNING, (
            f"Cannot reset {task_id} to PENDING from {node.status}"
        )
        node.status = TaskStatus.PENDING
        node.retry_count += 1

    # ------------------------------------------------------------------
    # Dependent skipping
    # ------------------------------------------------------------------

    def skip_dependents(self, task_id: str) -> List[str]:
        """Recursively skip all transitive dependents of a failed task.

        Returns the list of task_ids that were skipped.
        """
        skipped: List[str] = []
        queue = deque(self._dependents.get(task_id, []))
        visited: set[str] = set()

        while queue:
            tid = queue.popleft()
            if tid in visited:
                continue
            visited.add(tid)
            node = self._nodes[tid]
            if node.status in (TaskStatus.PENDING, TaskStatus.READY):
                node.status = TaskStatus.SKIPPED
                skipped.append(tid)
                # Continue to dependents of skipped nodes
                queue.extend(self._dependents.get(tid, []))

        return skipped

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_complete(self) -> bool:
        """Return True if all nodes are in a terminal state."""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}
        return all(n.status in terminal for n in self._nodes.values())

    def topological_order(self) -> List[str]:
        """Return task_ids in a valid topological order."""
        in_degree: Dict[str, int] = {
            tid: len(self._dependencies.get(tid, []))
            for tid in self._nodes
        }
        queue = deque(
            sorted(tid for tid, deg in in_degree.items() if deg == 0)
        )
        order: List[str] = []
        while queue:
            tid = queue.popleft()
            order.append(tid)
            for dependent in sorted(self._dependents.get(tid, [])):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        return order

    def pending_task_ids(self) -> List[str]:
        return [tid for tid, n in self._nodes.items() if n.status == TaskStatus.PENDING]

    def completed_task_ids(self) -> List[str]:
        return [tid for tid, n in self._nodes.items() if n.status == TaskStatus.COMPLETED]

    def failed_task_ids(self) -> List[str]:
        return [tid for tid, n in self._nodes.items() if n.status == TaskStatus.FAILED]

    def skipped_task_ids(self) -> List[str]:
        return [tid for tid, n in self._nodes.items() if n.status == TaskStatus.SKIPPED]

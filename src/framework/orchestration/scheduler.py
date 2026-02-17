"""Priority-based deterministic task scheduler.

Picks the next ready task from a TaskGraph, sorting by priority (ascending =
highest priority) with deterministic tie-breaking via a seeded RNG or
alphabetical task_id fallback.
"""

import random
from typing import List, Optional

from src.framework.orchestration.task_graph import TaskGraph, TaskNode


class Scheduler:
    """Select the next task to execute from a TaskGraph.

    Parameters
    ----------
    rng : random.Random, optional
        A seeded RNG for deterministic tie-breaking among tasks of equal
        priority. When ``None``, ties are broken alphabetically by task_id.
    """

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng

    def next_task(self, graph: TaskGraph) -> Optional[TaskNode]:
        """Pick the single highest-priority ready task and mark it RUNNING.

        Returns ``None`` when no tasks are ready.
        """
        ready = graph.get_ready_tasks()
        if not ready:
            return None

        chosen = self._pick(ready)
        graph.mark_running(chosen.task_id)
        return chosen

    def schedule_all(self, graph: TaskGraph) -> List[TaskNode]:
        """Return all ready tasks in priority order. Does NOT mark RUNNING."""
        ready = graph.get_ready_tasks()
        if not ready:
            return []
        return self._sort(ready)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _pick(self, ready: List[TaskNode]) -> TaskNode:
        """Return the highest-priority node with deterministic tie-breaking."""
        sorted_nodes = self._sort(ready)
        # Find all nodes with the best (lowest value) priority
        best_priority = sorted_nodes[0].task_spec.priority
        tied = [n for n in sorted_nodes if n.task_spec.priority == best_priority]

        if len(tied) == 1 or self._rng is None:
            return tied[0]

        return self._rng.choice(tied)

    def _sort(self, nodes: List[TaskNode]) -> List[TaskNode]:
        """Sort by priority (ascending), then by task_id alphabetically."""
        return sorted(nodes, key=lambda n: (n.task_spec.priority, n.task_id))

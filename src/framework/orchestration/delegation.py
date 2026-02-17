"""Delegation depth tracking and output schema validation.

Agents signal delegation by including ``"delegated_tasks": [...]`` in their
:class:`TaskResult.output` dict. The DelegationHandler injects those sub-tasks
into the running TaskGraph and validates delegate outputs against optional
JSON schemas.
"""

import logging
from typing import Dict, List, Optional

from src.framework.contracts import TaskResult, TaskSpec
from src.framework.orchestration.task_graph import TaskGraph

logger = logging.getLogger(__name__)


class DelegationHandler:
    """Manages task delegation depth and output validation.

    Parameters
    ----------
    max_delegation_depth : int
        Maximum allowed nesting depth of delegated tasks.
    max_children_per_parent : int
        Maximum number of child tasks a single parent task may spawn.
    max_total_delegated_tasks : int | None
        Optional global cap on delegated tasks in a graph.
    dedupe_within_parent : bool
        If True, suppress duplicate delegated objectives under one parent.
    """

    def __init__(
        self,
        max_delegation_depth: int = 3,
        max_children_per_parent: int = 10,
        max_total_delegated_tasks: Optional[int] = None,
        dedupe_within_parent: bool = True,
    ) -> None:
        self.max_delegation_depth = max_delegation_depth
        self.max_children_per_parent = max_children_per_parent
        self.max_total_delegated_tasks = max_total_delegated_tasks
        self.dedupe_within_parent = dedupe_within_parent

    def delegation_depth(self, graph: TaskGraph, task_id: str) -> int:
        """Walk the ``delegated_by`` chain and return the depth.

        A root task (no ``delegated_by``) has depth 0.
        """
        depth = 0
        current_id = task_id
        while True:
            node = graph.get_node(current_id)
            parent_id = node.task_spec.delegated_by
            if parent_id is None or parent_id not in graph.nodes:
                return depth
            depth += 1
            current_id = parent_id

    def inject_delegated_tasks(
        self,
        graph: TaskGraph,
        parent_task_id: str,
        sub_task_dicts: List[Dict],
    ) -> List[str]:
        """Create TaskSpecs from delegation output and add them to the graph.

        Each sub-task dict is expected to have at least ``task_id`` and
        ``objective`` keys. The ``delegated_by`` field is set automatically,
        and each sub-task implicitly depends on the parent being completed.

        Returns the list of newly added task_ids.

        Raises
        ------
        ValueError
            If the delegation depth would exceed ``max_delegation_depth``.
        """
        current_depth = self.delegation_depth(graph, parent_task_id)
        if current_depth + 1 > self.max_delegation_depth:
            raise ValueError(
                f"Delegation depth {current_depth + 1} exceeds max "
                f"{self.max_delegation_depth} for parent task '{parent_task_id}'"
            )

        existing_children = [
            n.task_spec
            for n in graph.nodes.values()
            if n.task_spec.delegated_by == parent_task_id
        ]
        if len(existing_children) + len(sub_task_dicts) > self.max_children_per_parent:
            raise ValueError(
                f"Delegation child limit exceeded for '{parent_task_id}': "
                f"{len(existing_children) + len(sub_task_dicts)} > {self.max_children_per_parent}"
            )

        if self.max_total_delegated_tasks is not None:
            existing_total_delegated = sum(
                1 for n in graph.nodes.values() if n.task_spec.delegated_by is not None
            )
            if existing_total_delegated + len(sub_task_dicts) > self.max_total_delegated_tasks:
                raise ValueError(
                    "Total delegated-task limit exceeded: "
                    f"{existing_total_delegated + len(sub_task_dicts)} > "
                    f"{self.max_total_delegated_tasks}"
                )

        new_specs: List[TaskSpec] = []
        new_ids: List[str] = []
        pending_ids: set[str] = set()
        existing_objectives = {
            (spec.objective or "").strip().lower()
            for spec in existing_children
            if (spec.objective or "").strip()
        }

        for idx, sub in enumerate(sub_task_dicts, start=1):
            objective = (sub.get("objective", "") or "").strip()
            objective_key = objective.lower()
            if (
                self.dedupe_within_parent
                and objective_key
                and objective_key in existing_objectives
            ):
                continue
            if objective_key:
                existing_objectives.add(objective_key)

            task_id = sub.get("task_id", "")
            if not task_id:
                task_id = f"{parent_task_id}_delegated_{idx}"
            if task_id in graph.nodes or task_id in pending_ids:
                raise ValueError(f"Delegated task id already exists: '{task_id}'")
            pending_ids.add(task_id)

            depends_on = list(sub.get("depends_on", []))
            if parent_task_id not in depends_on:
                depends_on.append(parent_task_id)

            spec = TaskSpec(
                task_id=task_id,
                objective=objective,
                agent_role=sub.get("agent_role", ""),
                required_capabilities=sub.get("required_capabilities", []),
                constraints=sub.get("constraints", {}),
                input_data=sub.get("input_data", {}),
                expected_output_schema=sub.get("expected_output_schema"),
                delegated_by=parent_task_id,
                depends_on=depends_on,
                priority=sub.get("priority", 0),
            )
            new_specs.append(spec)
            new_ids.append(spec.task_id)

        if new_specs:
            graph.add_tasks(new_specs)

        return new_ids

    # ------------------------------------------------------------------
    # Output validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_output(task_result: TaskResult, expected_schema: Optional[Dict]) -> bool:
        """Validate task output against a JSON schema.

        Returns ``True`` if valid, if no schema is provided, or if
        ``jsonschema`` is not installed (with a warning).
        """
        if expected_schema is None:
            return True

        try:
            import jsonschema  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "jsonschema is not installed; skipping output validation "
                "for task %s",
                task_result.task_id,
            )
            return True

        try:
            jsonschema.validate(instance=task_result.output, schema=expected_schema)
            return True
        except jsonschema.ValidationError:
            return False

    @staticmethod
    def validate_output_with_error(
        task_result: TaskResult,
        expected_schema: Optional[Dict],
    ) -> Optional[str]:
        """Validate and return an error message, or ``None`` if valid."""
        if expected_schema is None:
            return None

        try:
            import jsonschema  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "jsonschema is not installed; skipping output validation "
                "for task %s",
                task_result.task_id,
            )
            return None

        try:
            jsonschema.validate(instance=task_result.output, schema=expected_schema)
            return None
        except jsonschema.ValidationError as exc:
            return str(exc.message)

"""Procedural memory - JSON-based storage for workflows and procedures."""
import json
from typing import Dict, Any, Optional
from pathlib import Path
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ProceduralMemory:
    """JSON-based procedural memory for storing successful workflows."""

    def __init__(self, file_path: str = "data/memory/workflows.json"):
        """Initialize procedural memory.

        Args:
            file_path: Path to JSON file
        """
        self.file_path = file_path

        # Ensure directory exists
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)

        self.workflows = self._load()
        logger.info(f"Initialized procedural memory at {file_path}")

    def _load(self) -> Dict[str, Any]:
        """Load workflows from file.

        Returns:
            Workflows dict
        """
        if not Path(self.file_path).exists():
            return {}

        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load workflows from {self.file_path}: {e}")
            return {}

    def _save(self) -> None:
        """Save workflows to file."""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.workflows, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save workflows to {self.file_path}: {e}")

    def get_workflow(self, task_type: str) -> Optional[Dict[str, Any]]:
        """Get workflow for a task type.

        Args:
            task_type: Type of task

        Returns:
            Workflow dict or None if not found
        """
        workflow = self.workflows.get(task_type)
        if workflow:
            logger.debug(f"Retrieved workflow for {task_type}")
        return workflow

    def save_workflow(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        performance_score: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Save or update workflow.

        Updates workflow only if performance score is better than existing.

        Args:
            task_type: Type of task
            workflow: Workflow definition dict
            performance_score: Performance score (higher is better)
            metadata: Optional metadata
        """
        current = self.workflows.get(task_type)

        # Update if this is better or if no existing workflow
        if not current or performance_score > current.get('score', 0):
            self.workflows[task_type] = {
                'workflow': workflow,
                'score': performance_score,
                'metadata': metadata or {}
            }
            self._save()

            logger.info(
                f"Saved workflow for {task_type} "
                f"(score: {performance_score:.3f})"
            )
        else:
            logger.debug(
                f"Skipped saving workflow for {task_type} "
                f"(current score {current['score']:.3f} >= new score {performance_score:.3f})"
            )

    def get_all_workflows(self) -> Dict[str, Any]:
        """Get all workflows.

        Returns:
            Dict of all workflows
        """
        return self.workflows.copy()

    def delete_workflow(self, task_type: str) -> bool:
        """Delete a workflow.

        Args:
            task_type: Type of task

        Returns:
            True if deleted, False if not found
        """
        if task_type in self.workflows:
            del self.workflows[task_type]
            self._save()
            logger.info(f"Deleted workflow for {task_type}")
            return True

        return False

    def clear(self) -> None:
        """Clear all workflows."""
        self.workflows = {}
        self._save()
        logger.info("Cleared procedural memory")

    def get_best_practices(self, task_type: str) -> Dict[str, Any]:
        """Get best practices for a task type based on workflow performance.

        Args:
            task_type: Type of task

        Returns:
            Best practices dict
        """
        workflow = self.get_workflow(task_type)

        if not workflow:
            return {
                'task_type': task_type,
                'available': False,
                'message': 'No workflow found for this task type'
            }

        return {
            'task_type': task_type,
            'available': True,
            'score': workflow['score'],
            'workflow': workflow['workflow'],
            'metadata': workflow.get('metadata', {})
        }

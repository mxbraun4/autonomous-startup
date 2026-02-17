"""Configurable retry policy with exponential backoff.

Only retries TRANSIENT errors. Provides delay computation and a blocking
``wait()`` method for immediate-retry loops inside the Executor.
"""

import time
from typing import Optional

from src.framework.contracts import TaskResult
from src.framework.types import ErrorCategory


class RetryPolicy:
    """Decides whether to retry a failed task and how long to wait.

    Parameters
    ----------
    max_retries : int
        Default maximum retry count per task.
    base_delay_seconds : float
        Delay before the first retry. Subsequent delays double.
    max_delay_seconds : float
        Cap on the computed delay.
    """

    def __init__(
        self,
        max_retries: int = 2,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def should_retry(
        self,
        task_result: TaskResult,
        current_retry_count: int,
        max_retries_override: Optional[int] = None,
    ) -> bool:
        """Return ``True`` if the task should be retried.

        Only TRANSIENT errors are retried. Budget, policy, and capability
        errors are considered permanent.
        """
        if task_result.error_category != ErrorCategory.TRANSIENT:
            return False
        limit = max_retries_override if max_retries_override is not None else self.max_retries
        return current_retry_count < limit

    def compute_delay(self, current_retry_count: int) -> float:
        """Compute the backoff delay for the given retry attempt (0-indexed)."""
        delay = self.base_delay_seconds * (2 ** current_retry_count)
        return min(delay, self.max_delay_seconds)

    def wait(self, current_retry_count: int) -> None:
        """Block for the computed backoff duration."""
        time.sleep(self.compute_delay(current_retry_count))

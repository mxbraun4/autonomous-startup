"""Read-only budget query layer on top of ExecutionContext.

BudgetManager adds wall-clock tracking and utilization queries but does
NOT duplicate budget mutation — that stays in ExecutionContext.
"""

import time
from typing import Any, Callable, Dict, Optional

from src.framework.safety.limits import BudgetLimits


class BudgetManager:
    """Query interface for budget utilization and wall-clock tracking.

    Parameters
    ----------
    execution_context
        The :class:`ExecutionContext` that owns budget state.
    limits
        Optional :class:`BudgetLimits` overriding RunConfig defaults.
    _clock
        Injectable monotonic clock for deterministic testing.
    """

    def __init__(
        self,
        execution_context: Any,
        limits: Optional[BudgetLimits] = None,
        _clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ctx = execution_context
        self._limits = limits or BudgetLimits()
        self._clock = _clock
        self._start_wall: float = self._clock()

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check_budget(self) -> bool:
        """Return ``True`` if all budgets still have remaining capacity.

        Delegates token/second checks to ExecutionContext, then adds
        wall-clock enforcement.
        """
        if not self._ctx.check_budget():
            return False

        # Wall-clock limit
        if self._limits.max_wall_seconds is not None:
            if self.elapsed_wall_seconds() >= self._limits.max_wall_seconds:
                return False

        # Step limit (from BudgetLimits, distinct from per-cycle step limit)
        if self._limits.max_steps is not None:
            ctx = self._ctx.run_context
            if ctx.step_count >= self._limits.max_steps:
                return False

        return True

    # ------------------------------------------------------------------
    # Remaining-capacity queries
    # ------------------------------------------------------------------

    def remaining_tokens(self) -> Optional[int]:
        """Return remaining token budget, or ``None`` if unlimited."""
        return self._ctx.run_context.budget_remaining_tokens

    def remaining_seconds(self) -> Optional[float]:
        """Return remaining execution-time budget, or ``None`` if unlimited."""
        return self._ctx.run_context.budget_remaining_seconds

    def remaining_steps(self) -> Optional[int]:
        """Return remaining steps, or ``None`` if unlimited."""
        if self._limits.max_steps is None:
            return None
        return max(0, self._limits.max_steps - self._ctx.run_context.step_count)

    # ------------------------------------------------------------------
    # Wall-clock queries
    # ------------------------------------------------------------------

    def elapsed_wall_seconds(self) -> float:
        """Seconds elapsed since BudgetManager was created."""
        return self._clock() - self._start_wall

    def remaining_wall_seconds(self) -> Optional[float]:
        """Remaining wall-clock seconds, or ``None`` if unlimited."""
        if self._limits.max_wall_seconds is None:
            return None
        return max(0.0, self._limits.max_wall_seconds - self.elapsed_wall_seconds())

    # ------------------------------------------------------------------
    # Utilization
    # ------------------------------------------------------------------

    def utilization_pct(self) -> Dict[str, Optional[float]]:
        """Return utilization percentage for each budget dimension.

        A value of ``None`` means the dimension is unlimited.
        """
        result: Dict[str, Optional[float]] = {}

        # Tokens
        if self._limits.max_tokens is not None and self._limits.max_tokens > 0:
            remaining = self.remaining_tokens()
            used = self._limits.max_tokens - (remaining if remaining is not None else self._limits.max_tokens)
            result["tokens"] = (used / self._limits.max_tokens) * 100.0
        else:
            result["tokens"] = None

        # Seconds
        if self._limits.max_seconds is not None and self._limits.max_seconds > 0:
            remaining = self.remaining_seconds()
            used = self._limits.max_seconds - (remaining if remaining is not None else self._limits.max_seconds)
            result["seconds"] = (used / self._limits.max_seconds) * 100.0
        else:
            result["seconds"] = None

        # Steps
        if self._limits.max_steps is not None and self._limits.max_steps > 0:
            result["steps"] = (self._ctx.run_context.step_count / self._limits.max_steps) * 100.0
        else:
            result["steps"] = None

        # Wall clock
        if self._limits.max_wall_seconds is not None and self._limits.max_wall_seconds > 0:
            result["wall_seconds"] = (self.elapsed_wall_seconds() / self._limits.max_wall_seconds) * 100.0
        else:
            result["wall_seconds"] = None

        return result

    def is_critical(self) -> bool:
        """Return ``True`` if any budget dimension is below the critical threshold.

        A dimension is critical when its *remaining* percentage is at or below
        ``critical_threshold_pct``.  Unlimited dimensions are never critical.
        """
        threshold = self._limits.critical_threshold_pct
        util = self.utilization_pct()

        for _dim, pct in util.items():
            if pct is not None and pct >= (100.0 - threshold):
                return True

        return False

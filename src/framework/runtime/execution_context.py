"""ExecutionContext: budget tracking, RNG, step counting, checkpointing.

Note on thread safety: This class is NOT thread-safe. If Layer D introduces
concurrent agent execution, callers must serialize access to begin_step /
end_step or introduce a lock.
"""

import random
from typing import Any, Optional

from src.framework.contracts import Checkpoint, RunConfig, RunContext
from src.framework.errors import BudgetExhaustedError


class ExecutionContext:
    """Wraps a :class:`RunContext` with lifecycle helpers.

    Constructed from a :class:`RunConfig` and a store reference. Provides
    step counting, budget deduction, deterministic RNG, and checkpoint
    serialisation.
    """

    def __init__(self, run_config: RunConfig, store: Any = None) -> None:
        self._run_config = run_config
        rng = random.Random(run_config.seed)

        self._ctx = RunContext(
            run_id=run_config.run_id or run_config.entity_id,
            cycle_id=0,
            step_count=0,
            budget_remaining_seconds=run_config.budget_seconds,
            budget_remaining_tokens=run_config.budget_tokens,
            rng=rng,
            store=store,
        )

    @property
    def run_context(self) -> RunContext:
        return self._ctx

    @property
    def run_config(self) -> RunConfig:
        return self._run_config

    def begin_cycle(self, cycle_id: int) -> None:
        """Set the current cycle counter."""
        self._ctx.cycle_id = cycle_id

    def begin_step(self, agent_id: str) -> None:
        """Increment the step counter and check budgets.

        Raises :class:`BudgetExhaustedError` if any budget is exhausted
        or the per-cycle step limit is exceeded.
        """
        if not self.check_budget():
            raise BudgetExhaustedError(
                "Budget exhausted before step could begin",
                run_id=self._ctx.run_id,
            )

        # Check per-cycle step limit
        if self._ctx.step_count >= self._run_config.max_steps_per_cycle:
            raise BudgetExhaustedError(
                f"Step limit exceeded: {self._ctx.step_count} >= {self._run_config.max_steps_per_cycle}",
                run_id=self._ctx.run_id,
            )

        self._ctx.step_count += 1
        self._ctx.active_agent_id = agent_id

    def end_step(self, tokens_used: int = 0, duration_seconds: float = 0.0) -> None:
        """Deduct consumed resources from remaining budgets."""
        if self._ctx.budget_remaining_tokens is not None:
            self._ctx.budget_remaining_tokens = max(
                0, self._ctx.budget_remaining_tokens - tokens_used
            )
        if self._ctx.budget_remaining_seconds is not None:
            self._ctx.budget_remaining_seconds = max(
                0.0, self._ctx.budget_remaining_seconds - duration_seconds
            )

    def check_budget(self) -> bool:
        """Return ``True`` if all budgets still have remaining capacity."""
        if (
            self._ctx.budget_remaining_tokens is not None
            and self._ctx.budget_remaining_tokens <= 0
        ):
            return False
        if (
            self._ctx.budget_remaining_seconds is not None
            and self._ctx.budget_remaining_seconds <= 0.0
        ):
            return False
        return True

    def get_rng(self) -> random.Random:
        """Return the seeded RNG instance."""
        return self._ctx.rng

    def to_checkpoint(self) -> Checkpoint:
        """Serialise current state into a :class:`Checkpoint`."""
        return Checkpoint(
            run_id=self._ctx.run_id,
            cycle_id=self._ctx.cycle_id,
            step_count=self._ctx.step_count,
            seed=self._run_config.seed,
            rng_state=self._ctx.rng.getstate(),
            budget_remaining_seconds=self._ctx.budget_remaining_seconds,
            budget_remaining_tokens=self._ctx.budget_remaining_tokens,
        )

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: Checkpoint,
        run_config: RunConfig,
        store: Any = None,
    ) -> "ExecutionContext":
        """Restore an :class:`ExecutionContext` from a checkpoint.

        The RNG state is restored exactly, so subsequent random draws
        will be identical to the original execution.
        """
        ctx = cls(run_config, store)
        ctx._ctx.run_id = checkpoint.run_id
        ctx._ctx.cycle_id = checkpoint.cycle_id
        ctx._ctx.step_count = checkpoint.step_count
        ctx._ctx.budget_remaining_seconds = checkpoint.budget_remaining_seconds
        ctx._ctx.budget_remaining_tokens = checkpoint.budget_remaining_tokens

        # Restore RNG state
        rng_state = checkpoint.rng_state
        if rng_state is not None:
            # JSON round-trip turns tuples into lists; setstate needs tuples
            if isinstance(rng_state, list):
                rng_state[1] = tuple(rng_state[1])
                rng_state = tuple(rng_state)
            ctx._ctx.rng.setstate(rng_state)

        return ctx

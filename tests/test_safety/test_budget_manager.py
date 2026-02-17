"""Tests for BudgetManager."""

from src.framework.contracts import RunConfig
from src.framework.runtime.execution_context import ExecutionContext
from src.framework.safety.budget_manager import BudgetManager
from src.framework.safety.limits import BudgetLimits


def _make_ctx(tokens=None, seconds=None):
    """Create an ExecutionContext with the given budget."""
    rc = RunConfig(budget_tokens=tokens, budget_seconds=seconds)
    return ExecutionContext(rc)


class TestCheckBudget:
    def test_delegates_to_context(self):
        ctx = _make_ctx(tokens=100)
        bm = BudgetManager(ctx)
        assert bm.check_budget() is True

    def test_false_on_token_exhaustion(self):
        ctx = _make_ctx(tokens=10)
        ctx.begin_step("a")
        ctx.end_step(tokens_used=10)
        assert ctx.check_budget() is False
        bm = BudgetManager(ctx)
        assert bm.check_budget() is False

    def test_false_on_seconds_exhaustion(self):
        ctx = _make_ctx(seconds=1.0)
        ctx.begin_step("a")
        ctx.end_step(duration_seconds=1.0)
        bm = BudgetManager(ctx)
        assert bm.check_budget() is False


class TestRemainingQueries:
    def test_remaining_tokens(self):
        ctx = _make_ctx(tokens=500)
        ctx.begin_step("a")
        ctx.end_step(tokens_used=100)
        bm = BudgetManager(ctx)
        assert bm.remaining_tokens() == 400

    def test_remaining_seconds(self):
        ctx = _make_ctx(seconds=60.0)
        ctx.begin_step("a")
        ctx.end_step(duration_seconds=10.0)
        bm = BudgetManager(ctx)
        assert bm.remaining_seconds() == 50.0

    def test_remaining_steps(self):
        ctx = _make_ctx()
        limits = BudgetLimits(max_steps=10)
        ctx.begin_step("a")
        ctx.end_step()
        bm = BudgetManager(ctx, limits=limits)
        assert bm.remaining_steps() == 9


class TestWallClock:
    def test_wall_clock_via_injectable_clock(self):
        t = [0.0]

        def clock():
            return t[0]

        ctx = _make_ctx()
        bm = BudgetManager(ctx, _clock=clock)
        assert bm.elapsed_wall_seconds() == 0.0
        t[0] = 5.0
        assert bm.elapsed_wall_seconds() == 5.0

    def test_wall_clock_limit_exceeded(self):
        t = [0.0]

        def clock():
            return t[0]

        ctx = _make_ctx()
        limits = BudgetLimits(max_wall_seconds=10.0)
        bm = BudgetManager(ctx, limits=limits, _clock=clock)
        assert bm.check_budget() is True
        t[0] = 10.0
        assert bm.check_budget() is False
        assert bm.remaining_wall_seconds() == 0.0


class TestUtilization:
    def test_utilization_pct_computation(self):
        ctx = _make_ctx(tokens=1000)
        ctx.begin_step("a")
        ctx.end_step(tokens_used=250)
        limits = BudgetLimits(max_tokens=1000, max_steps=10)
        bm = BudgetManager(ctx, limits=limits)
        util = bm.utilization_pct()
        assert util["tokens"] == 25.0
        assert util["steps"] == 10.0  # 1 step out of 10
        assert util["seconds"] is None  # unlimited
        assert util["wall_seconds"] is None  # unlimited

    def test_is_critical_below_threshold(self):
        ctx = _make_ctx(tokens=100)
        ctx.begin_step("a")
        ctx.end_step(tokens_used=95)
        limits = BudgetLimits(max_tokens=100, critical_threshold_pct=10.0)
        bm = BudgetManager(ctx, limits=limits)
        assert bm.is_critical() is True

    def test_unlimited_never_critical(self):
        ctx = _make_ctx()
        bm = BudgetManager(ctx)
        assert bm.is_critical() is False

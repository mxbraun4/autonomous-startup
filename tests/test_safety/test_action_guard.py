"""Tests for ActionGuard and create_action_guard factory."""

from src.framework.contracts import RunConfig
from src.framework.runtime.execution_context import ExecutionContext
from src.framework.safety.action_guard import ActionGuard, create_action_guard
from src.framework.safety.budget_manager import BudgetManager
from src.framework.safety.limits import BudgetLimits, ToolClassification
from src.framework.safety.policy_engine import PolicyEngine


def _guard(
    denylist=None,
    allowlist=None,
    autonomy_level=2,
    budget_manager=None,
    max_consecutive_denials=5,
):
    pe = PolicyEngine(
        denylist=set(denylist) if denylist else None,
        allowlist=set(allowlist) if allowlist else None,
        autonomy_level=autonomy_level,
    )
    return ActionGuard(
        policy_engine=pe,
        budget_manager=budget_manager,
        max_consecutive_denials=max_consecutive_denials,
    )


class TestHappyPath:
    def test_delegates_to_policy_engine(self):
        g = _guard()
        assert g.check("tool", "cap", {}) is True

    def test_policy_denial_propagated(self):
        g = _guard(denylist=["bad"])
        assert g.check("bad", "cap", {}) is False


class TestKillSwitch:
    def test_kill_denies_everything(self):
        g = _guard()
        g.kill("test reason")
        assert g.check("any_tool", "cap", {}) is False

    def test_kill_reason_recorded(self):
        g = _guard()
        g.kill("some reason")
        assert g.is_killed is True
        assert g.kill_reason == "some reason"


class TestAutoKill:
    def test_auto_kill_after_n_consecutive_denials(self):
        g = _guard(denylist=["tool"], max_consecutive_denials=3)
        for _ in range(3):
            g.check("tool", "cap", {})
        assert g.is_killed is True
        assert "3 consecutive" in g.kill_reason

    def test_consecutive_denials_reset_on_success(self):
        g = _guard(denylist=["bad"], max_consecutive_denials=3)
        # Two denials
        g.check("bad", "cap", {})
        g.check("bad", "cap", {})
        # One success resets the counter
        g.check("good", "cap", {})
        # Two more denials (should not trigger auto-kill yet)
        g.check("bad", "cap", {})
        g.check("bad", "cap", {})
        assert g.is_killed is False


class TestDenialLog:
    def test_denial_log_records_all_denials(self):
        g = _guard(denylist=["x"])
        g.check("x", "cap", {})
        g.check("x", "cap", {})
        assert len(g.denial_log) == 2
        assert g.denial_log[0].tool_name == "x"
        assert g.denial_log[0].rule_name == "denylist"


class TestBudget:
    def test_budget_exhaustion_denies(self):
        ctx = ExecutionContext(RunConfig(budget_tokens=10))
        ctx.begin_step("a")
        ctx.end_step(tokens_used=10)
        bm = BudgetManager(ctx)
        g = _guard(budget_manager=bm)
        assert g.check("tool", "cap", {}) is False
        result = g.check_detailed("tool", "cap", {})
        assert result.rule_name == "budget"


class TestPolicyOnlyMode:
    def test_guard_without_budget_manager(self):
        g = _guard()
        assert g.check("tool", "cap", {}) is True


class TestFactory:
    def test_create_action_guard_from_runconfig(self):
        rc = RunConfig(
            budget_tokens=1000,
            autonomy_level=1,
            policies={
                "denylist": ["dangerous_tool"],
                "max_consecutive_denials": 3,
            },
        )
        ctx = ExecutionContext(rc)
        guard = create_action_guard(rc, ctx)
        # Allowed tool passes
        assert guard.check("safe_tool", "cap", {}) is True
        # Denylisted tool blocked
        assert guard.check("dangerous_tool", "cap", {}) is False

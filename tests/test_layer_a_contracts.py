"""Tests for Layer A completion: new enums, errors, and runtime contracts."""

import json
import random

from src.framework.types import (
    ConsensusStatus,
    ErrorCategory,
    TaskStatus,
    ToolCallStatus,
)
from src.framework.errors import (
    AgentRuntimeError,
    BudgetExhaustedError,
    CapabilityNotFoundError,
    MemoryStoreError,
    PolicyViolationError,
    TaskRoutingError,
)
from src.framework.contracts import (
    AgentDecision,
    BaseMemoryEntity,
    Checkpoint,
    CycleMetrics,
    EvaluationResult,
    GateDecision,
    RunConfig,
    RunContext,
    TaskResult,
    TaskSpec,
    ToolCall,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.READY == "ready"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.BLOCKED == "blocked"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.SKIPPED == "skipped"

    def test_cardinality(self):
        assert len(TaskStatus) == 7


class TestToolCallStatus:
    def test_values(self):
        assert ToolCallStatus.SUCCESS == "success"
        assert ToolCallStatus.ERROR == "error"
        assert ToolCallStatus.DENIED == "denied"
        assert ToolCallStatus.TIMEOUT == "timeout"
        assert ToolCallStatus.BUDGET_EXCEEDED == "budget_exceeded"

    def test_cardinality(self):
        assert len(ToolCallStatus) == 5


class TestErrorCategory:
    def test_values(self):
        assert ErrorCategory.TRANSIENT == "transient"
        assert ErrorCategory.PERMANENT == "permanent"
        assert ErrorCategory.BUDGET_EXCEEDED == "budget_exceeded"
        assert ErrorCategory.POLICY_VIOLATION == "policy_violation"
        assert ErrorCategory.UNRESOLVABLE_CAPABILITY == "unresolvable_capability"

    def test_cardinality(self):
        assert len(ErrorCategory) == 5


# ---------------------------------------------------------------------------
# Error hierarchy tests
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_agent_runtime_error_is_not_memory_store_error(self):
        assert not issubclass(AgentRuntimeError, MemoryStoreError)

    def test_agent_runtime_error_is_exception(self):
        assert issubclass(AgentRuntimeError, Exception)

    def test_budget_exhausted_inherits_agent_runtime_error(self):
        assert issubclass(BudgetExhaustedError, AgentRuntimeError)

    def test_policy_violation_inherits_agent_runtime_error(self):
        assert issubclass(PolicyViolationError, AgentRuntimeError)

    def test_capability_not_found_inherits_agent_runtime_error(self):
        assert issubclass(CapabilityNotFoundError, AgentRuntimeError)

    def test_task_routing_inherits_agent_runtime_error(self):
        assert issubclass(TaskRoutingError, AgentRuntimeError)

    def test_agent_runtime_error_carries_run_id(self):
        err = AgentRuntimeError("boom", run_id="r42")
        assert err.run_id == "r42"
        assert "boom" in str(err)

    def test_capability_not_found_carries_capability(self):
        err = CapabilityNotFoundError("web_search", run_id="r1")
        assert err.capability == "web_search"
        assert "web_search" in str(err)
        assert err.run_id == "r1"

    def test_budget_exhausted_defaults(self):
        err = BudgetExhaustedError()
        assert err.run_id == ""
        assert "Budget exhausted" in str(err)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestRunConfig:
    def test_defaults(self):
        rc = RunConfig()
        assert rc.seed == 42
        assert rc.max_cycles == 10
        assert rc.max_steps_per_cycle == 100
        assert rc.budget_seconds is None
        assert rc.budget_tokens is None
        assert rc.domain_adapter == "default"
        assert rc.autonomy_level == 0
        assert rc.policies == {}
        assert rc.max_delegation_depth == 3

    def test_inherits_base_memory_entity(self):
        rc = RunConfig()
        assert isinstance(rc, BaseMemoryEntity)
        assert len(rc.entity_id) == 16

    def test_json_round_trip(self):
        rc = RunConfig(
            run_id="run1",
            seed=123,
            max_cycles=5,
            budget_seconds=60.0,
            budget_tokens=10000,
            domain_adapter="startup_vc",
            autonomy_level=2,
            policies={"allow": ["web_search"]},
            max_delegation_depth=5,
        )
        data = json.loads(rc.model_dump_json())
        restored = RunConfig.model_validate(data)
        assert restored.seed == 123
        assert restored.max_cycles == 5
        assert restored.budget_seconds == 60.0
        assert restored.budget_tokens == 10000
        assert restored.domain_adapter == "startup_vc"
        assert restored.autonomy_level == 2
        assert restored.policies == {"allow": ["web_search"]}
        assert restored.max_delegation_depth == 5
        assert restored.run_id == "run1"


class TestRunContext:
    def test_is_not_base_memory_entity(self):
        ctx = RunContext(run_id="r1")
        assert not isinstance(ctx, BaseMemoryEntity)

    def test_mutable_fields(self):
        ctx = RunContext(run_id="r1", cycle_id=0, step_count=0)
        ctx.step_count = 5
        ctx.cycle_id = 2
        ctx.active_agent_id = "agent_1"
        assert ctx.step_count == 5
        assert ctx.cycle_id == 2
        assert ctx.active_agent_id == "agent_1"

    def test_arbitrary_types(self):
        rng = random.Random(42)
        ctx = RunContext(run_id="r1", rng=rng)
        assert ctx.rng is rng

    def test_store_reference(self):
        sentinel = object()
        ctx = RunContext(run_id="r1", store=sentinel)
        assert ctx.store is sentinel


class TestTaskSpec:
    def test_defaults(self):
        ts = TaskSpec()
        assert len(ts.task_id) == 16
        assert ts.objective == ""
        assert ts.required_capabilities == []
        assert ts.depends_on == []
        assert ts.priority == 0
        assert ts.delegated_by is None

    def test_json_round_trip(self):
        ts = TaskSpec(
            task_id="t1",
            objective="Research startups",
            agent_role="Data Strategy Expert",
            required_capabilities=["web_search", "database_write"],
            constraints={"max_retries": 2},
            input_data={"query": "fintech"},
            expected_output_schema={"type": "object"},
            delegated_by="t0",
            depends_on=["t_prev"],
            priority=1,
        )
        data = json.loads(ts.model_dump_json())
        restored = TaskSpec.model_validate(data)
        assert restored.task_id == "t1"
        assert restored.objective == "Research startups"
        assert restored.required_capabilities == ["web_search", "database_write"]
        assert restored.delegated_by == "t0"
        assert restored.depends_on == ["t_prev"]

    def test_inherits_base_memory_entity(self):
        ts = TaskSpec()
        assert isinstance(ts, BaseMemoryEntity)


class TestTaskResult:
    def test_defaults(self):
        tr = TaskResult()
        assert tr.task_status == TaskStatus.COMPLETED
        assert tr.error is None
        assert tr.error_category is None
        assert tr.tool_calls == []
        assert tr.retries == 0

    def test_json_round_trip(self):
        tr = TaskResult(
            task_id="t1",
            agent_id="a1",
            task_status=TaskStatus.FAILED,
            output={"partial": True},
            output_text="Failed midway",
            error="timeout",
            error_category=ErrorCategory.TRANSIENT,
            tool_calls=["tc1", "tc2"],
            duration_seconds=1.5,
            tokens_used=500,
            retries=2,
        )
        data = json.loads(tr.model_dump_json())
        restored = TaskResult.model_validate(data)
        assert restored.task_status == TaskStatus.FAILED
        assert restored.error_category == ErrorCategory.TRANSIENT
        assert restored.retries == 2
        assert restored.tool_calls == ["tc1", "tc2"]


class TestToolCall:
    def test_json_round_trip(self):
        tc = ToolCall(
            tool_name="web_search_startups",
            capability="web_search",
            caller_agent_id="a1",
            caller_task_id="t1",
            arguments={"query": "fintech"},
            call_status=ToolCallStatus.SUCCESS,
            result={"urls": ["http://example.com"]},
            duration_ms=120.5,
            policy_check_passed=True,
        )
        data = json.loads(tc.model_dump_json())
        restored = ToolCall.model_validate(data)
        assert restored.tool_name == "web_search_startups"
        assert restored.call_status == ToolCallStatus.SUCCESS
        assert restored.policy_check_passed is True

    def test_denied_tool_call(self):
        tc = ToolCall(
            tool_name="dangerous_tool",
            capability="admin",
            call_status=ToolCallStatus.DENIED,
            policy_check_passed=False,
            denied_reason="Not in allowlist",
        )
        assert tc.policy_check_passed is False
        assert tc.denied_reason == "Not in allowlist"

    def test_inherits_base_memory_entity(self):
        tc = ToolCall()
        assert isinstance(tc, BaseMemoryEntity)


class TestAgentDecision:
    def test_defaults_and_round_trip(self):
        ad = AgentDecision(
            agent_id="a1",
            task_id="t1",
            decision_type="tool_selection",
            reasoning="Tool X is best because ...",
            chosen_action="use_tool_x",
            alternatives_considered=["tool_y", "tool_z"],
            confidence=0.85,
        )
        data = json.loads(ad.model_dump_json())
        restored = AgentDecision.model_validate(data)
        assert restored.confidence == 0.85
        assert restored.alternatives_considered == ["tool_y", "tool_z"]


class TestCycleMetrics:
    def test_domain_agnostic(self):
        """CycleMetrics should have no hardcoded domain-specific fields."""
        cm = CycleMetrics(
            cycle_id=1,
            task_count=10,
            success_count=8,
            failure_count=2,
            tokens_used=5000,
            duration_seconds=30.0,
            domain_metrics={"response_rate": 0.4, "meeting_rate": 0.1},
        )
        assert cm.task_count == 10
        assert cm.domain_metrics["response_rate"] == 0.4
        # Verify no startup-specific fields exist
        assert not hasattr(cm, "response_rate")
        assert not hasattr(cm, "meeting_rate")
        assert not hasattr(cm, "outreach_sent_count")

    def test_json_round_trip(self):
        cm = CycleMetrics(
            cycle_id=3,
            task_count=5,
            success_count=5,
            domain_metrics={"custom_key": 42},
        )
        data = json.loads(cm.model_dump_json())
        restored = CycleMetrics.model_validate(data)
        assert restored.domain_metrics["custom_key"] == 42


class TestEvaluationResultAndGateDecision:
    def test_gate_decision(self):
        gd = GateDecision(
            gate_name="reliability",
            gate_status="fail",
            evidence={"success_rate": 0.2},
            recommended_action="stop",
        )
        assert gd.gate_status == "fail"
        assert gd.recommended_action == "stop"

    def test_evaluation_with_gates(self):
        g1 = GateDecision(gate_name="reliability", gate_status="pass")
        g2 = GateDecision(gate_name="safety", gate_status="warn", recommended_action="pause")
        er = EvaluationResult(
            gates=[g1, g2],
            overall_status="warn",
            summary="Safety gate warned",
            recommended_action="pause",
        )
        assert len(er.gates) == 2
        assert er.overall_status == "warn"

    def test_json_round_trip(self):
        g1 = GateDecision(gate_name="efficiency", gate_status="pass")
        er = EvaluationResult(
            gates=[g1],
            overall_status="pass",
            summary="All clear",
        )
        data = json.loads(er.model_dump_json())
        restored = EvaluationResult.model_validate(data)
        assert len(restored.gates) == 1
        assert restored.gates[0].gate_name == "efficiency"


class TestCheckpoint:
    def test_round_trip_with_rng_state(self):
        rng = random.Random(99)
        rng.random()  # advance state
        state = rng.getstate()

        cp = Checkpoint(
            run_id="run42",
            cycle_id=3,
            step_count=15,
            seed=99,
            rng_state=state,
            working_memory_path="/tmp/wm.json",
            store_data_dir="/tmp/store",
            pending_tasks=["t1", "t2"],
            completed_tasks=["t0"],
            budget_remaining_seconds=30.0,
            budget_remaining_tokens=5000,
        )
        data = json.loads(cp.model_dump_json())
        restored = Checkpoint.model_validate(data)
        assert restored.run_id == "run42"
        assert restored.cycle_id == 3
        assert restored.step_count == 15
        assert restored.seed == 99
        assert restored.pending_tasks == ["t1", "t2"]
        assert restored.completed_tasks == ["t0"]
        assert restored.budget_remaining_seconds == 30.0
        assert restored.budget_remaining_tokens == 5000

        # Restore RNG from state and verify determinism
        rng2 = random.Random()
        # rng_state round-trips as list but setstate needs tuple
        rng_state = restored.rng_state
        if isinstance(rng_state, list):
            rng_state[1] = tuple(rng_state[1])
            rng_state = tuple(rng_state)
        rng2.setstate(rng_state)
        assert rng.random() == rng2.random()

    def test_inherits_base_memory_entity(self):
        cp = Checkpoint()
        assert isinstance(cp, BaseMemoryEntity)

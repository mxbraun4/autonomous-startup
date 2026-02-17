"""Tests for ExecutionContext: budget, steps, RNG, checkpointing."""

import json

import pytest

from src.framework.contracts import Checkpoint, RunConfig
from src.framework.errors import BudgetExhaustedError
from src.framework.runtime.execution_context import ExecutionContext


class TestExecutionContextInitialState:
    def test_initial_state(self):
        rc = RunConfig(run_id="r1", seed=42, budget_seconds=60.0, budget_tokens=10000)
        ctx = ExecutionContext(rc)
        assert ctx.run_context.run_id == "r1"
        assert ctx.run_context.cycle_id == 0
        assert ctx.run_context.step_count == 0
        assert ctx.run_context.budget_remaining_seconds == 60.0
        assert ctx.run_context.budget_remaining_tokens == 10000

    def test_unlimited_budget(self):
        rc = RunConfig(run_id="r2", seed=1)
        ctx = ExecutionContext(rc)
        assert ctx.run_context.budget_remaining_seconds is None
        assert ctx.run_context.budget_remaining_tokens is None
        assert ctx.check_budget() is True

    def test_run_id_falls_back_to_entity_id(self):
        rc = RunConfig(seed=1)
        ctx = ExecutionContext(rc)
        assert ctx.run_context.run_id == rc.entity_id


class TestStepCounting:
    def test_step_increments(self):
        rc = RunConfig(run_id="r1", seed=1, max_steps_per_cycle=10)
        ctx = ExecutionContext(rc)
        ctx.begin_step("agent_1")
        assert ctx.run_context.step_count == 1
        assert ctx.run_context.active_agent_id == "agent_1"
        ctx.begin_step("agent_2")
        assert ctx.run_context.step_count == 2
        assert ctx.run_context.active_agent_id == "agent_2"

    def test_step_limit_exceeded(self):
        rc = RunConfig(run_id="r1", seed=1, max_steps_per_cycle=2)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.begin_step("a1")
        with pytest.raises(BudgetExhaustedError, match="Step limit exceeded"):
            ctx.begin_step("a1")


class TestBudgetDeduction:
    def test_token_deduction(self):
        rc = RunConfig(run_id="r1", seed=1, budget_tokens=1000, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.end_step(tokens_used=300)
        assert ctx.run_context.budget_remaining_tokens == 700

    def test_time_deduction(self):
        rc = RunConfig(run_id="r1", seed=1, budget_seconds=10.0, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.end_step(duration_seconds=3.5)
        assert ctx.run_context.budget_remaining_seconds == 6.5

    def test_budget_exhaustion_raises_on_next_step(self):
        rc = RunConfig(run_id="r1", seed=1, budget_tokens=100, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.end_step(tokens_used=100)
        assert ctx.run_context.budget_remaining_tokens == 0
        with pytest.raises(BudgetExhaustedError):
            ctx.begin_step("a1")

    def test_time_budget_exhaustion(self):
        rc = RunConfig(run_id="r1", seed=1, budget_seconds=1.0, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.end_step(duration_seconds=1.0)
        with pytest.raises(BudgetExhaustedError):
            ctx.begin_step("a1")

    def test_budget_does_not_go_negative(self):
        rc = RunConfig(run_id="r1", seed=1, budget_tokens=50, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.end_step(tokens_used=100)  # overshoot
        assert ctx.run_context.budget_remaining_tokens == 0

    def test_unlimited_budget_never_exhausts(self):
        rc = RunConfig(run_id="r1", seed=1, max_steps_per_cycle=1000)
        ctx = ExecutionContext(rc)
        for i in range(100):
            ctx.begin_step("a1")
            ctx.end_step(tokens_used=999, duration_seconds=999.0)
        assert ctx.check_budget() is True


class TestDeterministicRNG:
    def test_same_seed_same_sequence(self):
        rc1 = RunConfig(seed=42)
        rc2 = RunConfig(seed=42)
        ctx1 = ExecutionContext(rc1)
        ctx2 = ExecutionContext(rc2)
        seq1 = [ctx1.get_rng().random() for _ in range(10)]
        seq2 = [ctx2.get_rng().random() for _ in range(10)]
        assert seq1 == seq2

    def test_different_seed_different_sequence(self):
        ctx1 = ExecutionContext(RunConfig(seed=1))
        ctx2 = ExecutionContext(RunConfig(seed=2))
        assert ctx1.get_rng().random() != ctx2.get_rng().random()


class TestCheckpointRoundTrip:
    def test_checkpoint_preserves_state(self):
        rc = RunConfig(run_id="r1", seed=99, budget_tokens=5000, budget_seconds=30.0, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_cycle(2)
        ctx.begin_step("a1")
        ctx.end_step(tokens_used=100, duration_seconds=1.0)
        ctx.begin_step("a1")
        ctx.end_step(tokens_used=200, duration_seconds=2.0)

        # Advance RNG state a bit before checkpointing
        ctx.get_rng().random()

        cp = ctx.to_checkpoint()
        assert cp.run_id == "r1"
        assert cp.cycle_id == 2
        assert cp.step_count == 2
        assert cp.budget_remaining_tokens == 4700
        assert cp.budget_remaining_seconds == 27.0

        # Restore from checkpoint
        ctx2 = ExecutionContext.from_checkpoint(cp, rc)
        assert ctx2.run_context.run_id == "r1"
        assert ctx2.run_context.cycle_id == 2
        assert ctx2.run_context.step_count == 2
        assert ctx2.run_context.budget_remaining_tokens == 4700
        assert ctx2.run_context.budget_remaining_seconds == 27.0

        # Both RNGs should produce the same sequence from the checkpoint state
        assert ctx.get_rng().random() == ctx2.get_rng().random()
        assert ctx.get_rng().random() == ctx2.get_rng().random()

    def test_checkpoint_json_round_trip(self):
        rc = RunConfig(run_id="r1", seed=42, budget_tokens=1000, max_steps_per_cycle=100)
        ctx = ExecutionContext(rc)
        ctx.begin_step("a1")
        ctx.get_rng().random()

        cp = ctx.to_checkpoint()
        data = json.loads(cp.model_dump_json())
        cp_restored = Checkpoint.model_validate(data)

        ctx2 = ExecutionContext.from_checkpoint(cp_restored, rc)
        # After JSON round-trip, RNG should still produce deterministic output
        assert ctx.get_rng().random() == ctx2.get_rng().random()


class TestBeginCycle:
    def test_begin_cycle(self):
        rc = RunConfig(run_id="r1", seed=1)
        ctx = ExecutionContext(rc)
        ctx.begin_cycle(5)
        assert ctx.run_context.cycle_id == 5

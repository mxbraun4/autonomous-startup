"""Tests for Layer E autonomy controller components."""

from pathlib import Path

from src.framework.autonomy import (
    CheckpointManager,
    RunController,
    TerminationPolicy,
)
from src.framework.autonomy.termination import TerminationState, evaluate_termination
from src.framework.contracts import (
    CycleMetrics,
    EvaluationResult,
    GateDecision,
    RunConfig,
    TaskResult,
    TaskSpec,
)
from src.framework.observability import EventLogger
from src.framework.types import TaskStatus


class _FakeCycleExecutionResult:
    def __init__(
        self,
        *,
        total_tasks: int,
        completed_count: int,
        failed_count: int = 0,
        skipped_count: int = 0,
    ) -> None:
        self.total_tasks = total_tasks
        self.completed_count = completed_count
        self.failed_count = failed_count
        self.skipped_count = skipped_count
        self.task_results = {
            "task_1": TaskResult(task_id="task_1", task_status=TaskStatus.COMPLETED),
        }


class _FakeExecutor:
    def __init__(self, cycle_results):
        self._results = list(cycle_results)
        self.calls = 0

    def execute(self, task_specs):
        self.calls += 1
        if self._results:
            return self._results.pop(0)
        return _FakeCycleExecutionResult(total_tasks=len(task_specs), completed_count=len(task_specs))


class _FakeStore:
    def __init__(self):
        self.started = []
        self.ended = []
        self.saved = []
        self.loaded = []

    def start_run(self, run_id, metadata=None):
        self.started.append((run_id, metadata))

    def end_run(self, run_id):
        self.ended.append(run_id)

    def save_checkpoint(self, run_id, path):
        self.saved.append((run_id, path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("{}", encoding="utf-8")

    def load_checkpoint(self, run_id, path):
        self.loaded.append((run_id, path))


def _build_tasks(run_context):
    return [
        TaskSpec(
            task_id=f"task_{run_context.cycle_id}",
            objective="do work",
            agent_role="worker",
        )
    ]


def _always_pass_eval(current_metrics, previous_metrics=None):
    return EvaluationResult(
        run_id=current_metrics.run_id,
        cycle_id=current_metrics.cycle_id,
        gates=[GateDecision(gate_name="reliability", gate_status="pass", recommended_action="continue")],
        overall_status="pass",
        recommended_action="continue",
        summary="ok",
    )


def _gate_pause_eval(current_metrics, previous_metrics=None):
    return EvaluationResult(
        run_id=current_metrics.run_id,
        cycle_id=current_metrics.cycle_id,
        gates=[GateDecision(gate_name="reliability", gate_status="warn", recommended_action="pause")],
        overall_status="warn",
        recommended_action="pause",
        summary="pause",
    )


def _measure_fn(*, cycle_id, execution_result, run_id, duration_seconds):
    return CycleMetrics(
        run_id=run_id,
        cycle_id=cycle_id,
        task_count=execution_result.total_tasks,
        success_count=execution_result.completed_count,
        failure_count=execution_result.failed_count,
        duration_seconds=duration_seconds,
        tokens_used=0,
        domain_metrics={},
    )


class _EvaluatorAdapter:
    def __init__(self, fn):
        self._fn = fn

    def evaluate(self, current_metrics, previous_metrics=None):
        return self._fn(current_metrics, previous_metrics)


def test_termination_policy_stops_on_budget_exhaustion():
    policy = TerminationPolicy(max_cycles=3, critical_failure_threshold=2)
    state = TerminationState()
    decision = evaluate_termination(
        cycle_id=1,
        policy=policy,
        state=state,
        budget_ok=False,
        evaluation_result=None,
    )
    assert decision.action == "stop"
    assert decision.reason == "budget_exhausted"


def test_checkpoint_manager_roundtrip(tmp_path):
    store = _FakeStore()
    manager = CheckpointManager(checkpoint_dir=str(tmp_path), store=store)

    run_config = RunConfig(run_id="run_cp", seed=42, max_cycles=2)
    from src.framework.runtime.execution_context import ExecutionContext
    context = ExecutionContext(run_config, store=store)
    context.begin_cycle(2)
    context.begin_step("agent_1")
    context.end_step(tokens_used=5, duration_seconds=1.0)

    checkpoint_path = manager.save(
        context=context,
        pending_tasks=["p1"],
        completed_tasks=["c1"],
    )
    assert Path(checkpoint_path).exists()
    assert len(store.saved) == 1

    loaded = manager.load(
        checkpoint_path=checkpoint_path,
        run_config=run_config,
    )
    assert loaded.checkpoint.cycle_id == 2
    assert loaded.context.run_context.step_count == 1
    assert len(store.loaded) == 1


def test_run_controller_runs_until_max_cycles(tmp_path):
    run_config = RunConfig(run_id="run_max", seed=1, max_cycles=2)
    executor = _FakeExecutor(
        [
            _FakeCycleExecutionResult(total_tasks=1, completed_count=1),
            _FakeCycleExecutionResult(total_tasks=1, completed_count=1),
        ]
    )
    store = _FakeStore()

    controller = RunController(
        run_config=run_config,
        executor=executor,
        task_builder=_build_tasks,
        store=store,
        evaluator=_EvaluatorAdapter(_always_pass_eval),
        measure_fn=_measure_fn,
        checkpoint_dir=str(tmp_path),
    )
    result = controller.run()

    assert result.run_id == "run_max"
    assert result.cycles_completed == 2
    assert result.final_status == "completed"
    assert result.final_reason == "max_cycles_reached"
    assert executor.calls == 2
    assert len(store.started) == 1
    assert len(store.ended) == 1
    assert result.last_checkpoint_path is not None


def test_run_controller_pauses_on_gate_pause(tmp_path):
    run_config = RunConfig(run_id="run_pause", seed=1, max_cycles=5)
    executor = _FakeExecutor([_FakeCycleExecutionResult(total_tasks=1, completed_count=1)])

    controller = RunController(
        run_config=run_config,
        executor=executor,
        task_builder=_build_tasks,
        evaluator=_EvaluatorAdapter(_gate_pause_eval),
        measure_fn=_measure_fn,
        checkpoint_dir=str(tmp_path),
    )
    result = controller.run()

    assert result.cycles_completed == 1
    assert result.final_action == "pause"
    assert result.final_status == "paused"
    assert result.final_reason == "gate_pause"


def test_run_controller_resume_from_checkpoint(tmp_path):
    run_config = RunConfig(run_id="run_resume", seed=1, max_cycles=2)
    executor = _FakeExecutor(
        [
            _FakeCycleExecutionResult(total_tasks=1, completed_count=1),
            _FakeCycleExecutionResult(total_tasks=1, completed_count=1),
        ]
    )
    store = _FakeStore()
    controller = RunController(
        run_config=run_config,
        executor=executor,
        task_builder=_build_tasks,
        store=store,
        evaluator=_EvaluatorAdapter(_always_pass_eval),
        measure_fn=_measure_fn,
        checkpoint_dir=str(tmp_path),
    )

    first = controller.run()
    assert first.cycles_completed == 2
    checkpoint_path = first.last_checkpoint_path
    assert checkpoint_path is not None

    # Resume on a fresh controller instance from same checkpoint.
    executor2 = _FakeExecutor([_FakeCycleExecutionResult(total_tasks=1, completed_count=1)])
    controller2 = RunController(
        run_config=run_config,
        executor=executor2,
        task_builder=_build_tasks,
        store=store,
        evaluator=_EvaluatorAdapter(_always_pass_eval),
        measure_fn=_measure_fn,
        checkpoint_dir=str(tmp_path),
    )
    resumed = controller2.resume(checkpoint_path)

    # Checkpoint was from cycle 2 and max_cycles=2, so no additional cycles should run.
    assert resumed.cycles_completed == 0
    assert resumed.final_status == "completed"
    assert resumed.final_reason == "max_cycles_reached"


def test_run_controller_emits_run_cycle_and_checkpoint_events(tmp_path):
    run_config = RunConfig(run_id="run_events", seed=1, max_cycles=1)
    executor = _FakeExecutor([_FakeCycleExecutionResult(total_tasks=1, completed_count=1)])
    event_logger = EventLogger()

    controller = RunController(
        run_config=run_config,
        executor=executor,
        task_builder=_build_tasks,
        evaluator=_EvaluatorAdapter(_always_pass_eval),
        measure_fn=_measure_fn,
        checkpoint_dir=str(tmp_path),
        event_emitter=event_logger,
    )
    result = controller.run()
    assert result.final_status == "completed"

    event_types = {
        event.event_type for event in event_logger.get_events(run_id="run_events")
    }
    assert "run_start" in event_types
    assert "cycle_start" in event_types
    assert "cycle_end" in event_types
    assert "checkpoint_saved" in event_types
    assert "run_end" in event_types

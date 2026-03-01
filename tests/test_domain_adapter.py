"""Tests for Layer I domain adapters."""

from types import SimpleNamespace

from src.framework.adapters import StartupVCAdapter
from src.framework.autonomy.run_controller import RunController
from src.framework.contracts import EvaluationResult, GateDecision, RunConfig


class _FakeExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, task_specs):
        self.calls += 1
        return SimpleNamespace(
            total_tasks=len(task_specs),
            completed_count=len(task_specs),
            failed_count=0,
            skipped_count=0,
            task_results={t.task_id: {"ok": True} for t in task_specs},
        )


class _EvaluatorAdapter:
    def evaluate(self, current_metrics, previous_metrics=None):
        del previous_metrics
        return EvaluationResult(
            run_id=current_metrics.run_id,
            cycle_id=current_metrics.cycle_id,
            gates=[GateDecision(gate_name="reliability", gate_status="pass")],
            overall_status="pass",
            recommended_action="continue",
            summary="ok",
        )


def test_startup_vc_adapter_builds_cycle_tasks():
    adapter = StartupVCAdapter(max_targets_per_cycle=4)
    run_context = SimpleNamespace(run_id="run_a", cycle_id=2)
    tasks = adapter.build_cycle_tasks(run_context)

    assert len(tasks) == 1
    assert all(task.run_id == "run_a" for task in tasks)
    assert all(task.cycle_id == 2 for task in tasks)
    assert tasks[0].constraints["max_targets"] == 4


def test_startup_vc_adapter_simulation_and_metrics():
    adapter = StartupVCAdapter()
    run_context = SimpleNamespace(run_id="run_x", cycle_id=1)
    cycle_outputs = SimpleNamespace(
        total_tasks=3,
        completed_count=2,
        failed_count=1,
        skipped_count=0,
    )
    simulation = adapter.simulate_environment(cycle_outputs, run_context)
    metrics = adapter.compute_domain_metrics(simulation)

    assert simulation["success_rate"] > 0.0
    assert 0.0 <= metrics["response_rate"] <= 1.0
    assert 0.0 <= metrics["meeting_rate"] <= metrics["response_rate"]
    assert "procedure_score" in metrics


def test_startup_vc_adapter_wires_customer_environment(monkeypatch):
    captured = {"build_called": False, "run_called": False}

    def fake_build_input(**kwargs):
        captured["build_called"] = True
        captured["build_kwargs"] = dict(kwargs)
        return {"run_context": {"iteration": kwargs["iteration"]}}

    def fake_run_customer_environment(environment_input):
        captured["run_called"] = True
        captured["environment_input"] = dict(environment_input)
        return {
            "metrics": {
                "founder_interested_rate": 0.60,
                "vc_interested_rate": 0.40,
                "mutual_interest_rate": 0.50,
                "meeting_conversion_rate": 0.50,
                "average_match_relevance": 0.70,
                "explanation_coverage": 0.80,
                "personalization_quality_score": 0.90,
            },
            "events": [{"event_id": "evt_1"}],
            "diagnostics": {"input_validation_errors": []},
        }

    monkeypatch.setattr(
        "src.framework.adapters.startup_vc.build_customer_environment_input",
        fake_build_input,
    )
    monkeypatch.setattr(
        "src.framework.adapters.startup_vc.run_customer_environment",
        fake_run_customer_environment,
    )

    adapter = StartupVCAdapter(use_customer_simulation=True)
    run_context = SimpleNamespace(run_id="run_c", cycle_id=3)
    cycle_outputs = SimpleNamespace(
        total_tasks=3,
        completed_count=2,
        failed_count=1,
        skipped_count=0,
    )
    simulation = adapter.simulate_environment(cycle_outputs, run_context)

    assert captured["build_called"] is True
    assert captured["run_called"] is True
    assert simulation["measurement_source"] == "customer_simulation"
    assert simulation["response_rate"] == 0.5
    assert simulation["meeting_rate"] == 0.25
    assert simulation["match_quality_score"] == 0.7
    assert simulation["explanation_coverage"] == 0.8
    assert simulation["outreach_personalization_score"] == 0.9
    assert simulation["customer_diagnostics"]["events_count"] == 1
    assert simulation["customer_metrics"]["mutual_interest_rate"] == 0.5


def test_startup_vc_adapter_fallbacks_when_customer_environment_fails(monkeypatch):
    def fake_run_customer_environment(_environment_input):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.framework.adapters.startup_vc.run_customer_environment",
        fake_run_customer_environment,
    )

    adapter = StartupVCAdapter(use_customer_simulation=True)
    run_context = SimpleNamespace(run_id="run_c", cycle_id=1)
    cycle_outputs = SimpleNamespace(
        total_tasks=3,
        completed_count=2,
        failed_count=1,
        skipped_count=0,
    )
    simulation = adapter.simulate_environment(cycle_outputs, run_context)

    assert simulation["measurement_source"] == "customer_simulation_fallback_formula"
    assert "customer_simulation_error" in simulation
    assert 0.0 <= simulation["response_rate"] <= 1.0


def test_run_controller_uses_domain_adapter_when_task_builder_absent(tmp_path):
    run_config = RunConfig(
        run_id="run_adapter",
        seed=1,
        max_cycles=1,
        policies={"max_children_per_parent": 9},
    )
    adapter = StartupVCAdapter()
    executor = _FakeExecutor()
    controller = RunController(
        run_config=run_config,
        executor=executor,
        domain_adapter=adapter,
        evaluator=_EvaluatorAdapter(),
        checkpoint_dir=str(tmp_path),
    )
    result = controller.run()

    assert result.cycles_completed == 1
    assert result.final_status == "completed"
    assert executor.calls == 1
    # Explicit run config policy overrides adapter default.
    assert run_config.policies["max_children_per_parent"] == 9
    # Adapter defaults still merged in.
    assert "loop_window_size" in run_config.policies


"""Tests for the web-product domain adapter."""

from __future__ import annotations

from types import SimpleNamespace

from src.framework.adapters import WebProductAdapter
from src.framework.contracts import EvaluationResult, GateDecision, TaskResult
from src.framework.types import TaskStatus


def test_web_product_adapter_builds_cycle_tasks():
    adapter = WebProductAdapter(
        target_url="http://127.0.0.1:3000",
        workspace_root=".",
        test_command="pytest -q",
        restart_command='python -c "print(\'restart\')"',
        max_edits_per_cycle=3,
        default_edit_instruction={
            "path": "README.md",
            "search": "foo",
            "replace": "bar",
            "dry_run": True,
        },
    )

    tasks = adapter.build_cycle_tasks(SimpleNamespace(run_id="run_web", cycle_id=2))
    assert len(tasks) == 3
    assert tasks[0].agent_role == "web_explorer"
    assert tasks[1].agent_role == "web_improver"
    assert tasks[2].agent_role == "web_validator"
    assert tasks[0].required_capabilities == ["browser_navigate"]
    assert tasks[1].required_capabilities == ["code_edit"]
    assert tasks[2].required_capabilities == ["run_tests", "restart_service"]
    assert tasks[0].input_data["url"] == "http://127.0.0.1:3000"

    policies = adapter.get_domain_policies()
    assert policies["allowed_edit_path_patterns"] == ["README.md"]
    assert policies["allowed_edit_search_patterns"] == ["^foo$"]


def test_web_product_adapter_metrics_include_layer_g_signals():
    adapter = WebProductAdapter(
        target_url="http://localhost:3000",
        workspace_root=".",
    )
    cycle_outputs = SimpleNamespace(
        total_tasks=3,
        completed_count=3,
        failed_count=0,
        skipped_count=0,
        task_results={
            "web_explore_cycle_1": TaskResult(
                task_id="web_explore_cycle_1",
                task_status=TaskStatus.COMPLETED,
                output={},
            ),
            "web_improve_cycle_1": TaskResult(
                task_id="web_improve_cycle_1",
                task_status=TaskStatus.COMPLETED,
                output={"edits_applied": 1},
            ),
            "web_validate_cycle_1": TaskResult(
                task_id="web_validate_cycle_1",
                task_status=TaskStatus.COMPLETED,
                output={"tests_passed": True, "restart_status": "success"},
            ),
        },
    )
    run_ctx = SimpleNamespace(run_id="run_web", cycle_id=1)

    simulation = adapter.simulate_environment(cycle_outputs, run_ctx)
    metrics = adapter.compute_domain_metrics(simulation)

    assert metrics["tests_passed"] is True
    assert metrics["restart_success"] is True
    assert metrics["edits_applied"] == 1
    assert "procedure_score" in metrics
    assert "policy_violations" in metrics
    assert "unhandled_exceptions" in metrics
    assert "determinism_variance" in metrics


def test_web_product_adapter_procedures_and_policies():
    adapter = WebProductAdapter(
        target_url="http://localhost:3000",
        workspace_root=".",
        max_edits_per_cycle=2,
    )
    evaluation = EvaluationResult(
        run_id="run_1",
        cycle_id=1,
        gates=[GateDecision(gate_name="reliability", gate_status="pass")],
        overall_status="pass",
        recommended_action="continue",
        summary="ok",
    )
    proposals = adapter.suggest_procedure_updates(evaluation)
    policies = adapter.get_domain_policies()

    assert len(proposals) == 1
    assert proposals[0].task_type == "web_validation"
    assert "allowlist" in policies
    assert policies["max_edits_per_cycle"] == 2
    assert "code_edit" in policies["allowlist"]

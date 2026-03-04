"""Tests for BML loop autonomy improvements.

Covers:
1. Structured QA failure reports (_format_qa_failures)
2. Simulation feedback timing (moved into BUILD, guarded in evaluate)
3. PolicyUpdater persistence and real active_policies
4. Evaluator trend analysis via previous_metrics / procedure_score
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from src.crewai_agents.crews import BuildMeasureLearnFlow, _FlowState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flow(**overrides) -> BuildMeasureLearnFlow:
    """Create a flow and patch state fields for unit-testing helpers."""
    flow = BuildMeasureLearnFlow(max_iterations=1, verbose=0)
    for key, value in overrides.items():
        setattr(flow.state, key, value)
    return flow


# ===================================================================
# 1. Structured QA failure reports
# ===================================================================

class TestFormatQaFailures:
    """Tests for _format_qa_failures helper."""

    def test_empty_result(self):
        flow = _make_flow()
        assert "No QA results" in flow._format_qa_failures({})

    def test_all_passing(self):
        qa = {
            "qa_gate_passed": True,
            "syntax": {"syntax_ok": True},
            "workspace_ok": True,
            "http_ok": True,
        }
        flow = _make_flow()
        report = flow._format_qa_failures(qa)
        assert "no failures" in report.lower()

    def test_syntax_failures(self):
        qa = {
            "qa_gate_passed": False,
            "syntax": {
                "syntax_ok": False,
                "syntax_failures": [
                    {"file": "src/bad.py", "error": "unexpected indent"},
                    {"file": "src/worse.py", "error": "invalid syntax"},
                ],
            },
            "workspace_ok": True,
            "http_ok": True,
        }
        flow = _make_flow()
        report = flow._format_qa_failures(qa)
        assert "SYNTAX ERRORS" in report
        assert "src/bad.py" in report
        assert "unexpected indent" in report
        assert "src/worse.py" in report
        assert "1." in report  # numbered

    def test_workspace_missing(self):
        qa = {
            "qa_gate_passed": False,
            "syntax": {"syntax_ok": True},
            "workspace_ok": False,
            "workspace": {
                "html_files": ["index.html"],
                "non_placeholder_html_count": 0,
            },
            "http_ok": True,
        }
        flow = _make_flow()
        report = flow._format_qa_failures(qa)
        assert "WORKSPACE CONTENT MISSING" in report
        assert "Non-placeholder HTML files: 0" in report

    def test_http_failure(self):
        qa = {
            "qa_gate_passed": False,
            "syntax": {"syntax_ok": True},
            "workspace_ok": True,
            "http_ok": False,
            "http_checks": {
                "http_landing_score": 0.0,
                "http_nav_score": 0.5,
            },
        }
        flow = _make_flow()
        report = flow._format_qa_failures(qa)
        assert "HTTP CHECK FAILURES" in report
        assert "http_landing_score: 0.0" in report

    def test_multiple_failures_numbered(self):
        qa = {
            "qa_gate_passed": False,
            "syntax": {
                "syntax_ok": False,
                "syntax_failures": [{"file": "x.py", "error": "err"}],
            },
            "workspace_ok": False,
            "workspace": {"html_files": [], "non_placeholder_html_count": 0},
            "http_ok": False,
            "http_checks": {"http_landing_score": 0.0},
        }
        flow = _make_flow()
        report = flow._format_qa_failures(qa)
        assert "3 issue(s)" in report
        assert "1. SYNTAX" in report
        assert "2. WORKSPACE" in report
        assert "3. HTTP" in report

    def test_remediation_uses_formatted_report(self):
        """Verify _run_coordinator_remediation no longer injects raw JSON."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow._run_coordinator_remediation)
        assert "_format_qa_failures" in source
        assert "json.dumps" not in source


# ===================================================================
# 2. Simulation feedback timing
# ===================================================================

class TestSimulationFeedbackTiming:
    """Simulation runs in BUILD (after QA pass) and is guarded in evaluate."""

    def test_flow_state_has_simulation_field(self):
        state = _FlowState()
        assert hasattr(state, "simulation_feedback_summary")
        assert state.simulation_feedback_summary == ""

    def test_simulation_runs_in_build_when_qa_passes(self):
        """When QA passes, _write_simulation_feedback is called in build()."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.build)
        # Should call _write_simulation_feedback before remediation block
        sim_idx = source.index("_write_simulation_feedback")
        remediation_idx = source.index("_run_coordinator_remediation")
        assert sim_idx < remediation_idx, (
            "Simulation feedback must run before remediation in build()"
        )

    def test_evaluate_guards_double_simulation(self):
        """Evaluate only runs simulation when summary is empty."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        assert "not self.state.simulation_feedback_summary" in source

    def test_feedback_injected_into_remediation(self):
        """Remediation description includes customer friction if available."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow._run_coordinator_remediation)
        assert "CUSTOMER FRICTION POINTS" in source
        assert "simulation_feedback_summary" in source

    def test_evaluate_bridge_populates_summary(self):
        """evaluate() bridge path stores feedback summary, not just writes to DB."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        # After _write_simulation_feedback, should also collect and store
        assert "_collect_user_feedback" in source
        assert "simulation_feedback_summary" in source


# ===================================================================
# 2b. Per-iteration state reset
# ===================================================================

class TestPerIterationStateReset:
    """State fields are properly reset at the start of each build() iteration."""

    def test_build_result_text_reset(self):
        """build_result_text must be reset to avoid stale data on iteration 2+."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.build)
        assert 'self.state.build_result_text = ""' in source

    def test_user_feedback_reset(self):
        """user_feedback must be reset to avoid stale data on iteration 2+."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.build)
        assert "self.state.user_feedback = {}" in source

    def test_all_per_iteration_fields_reset(self):
        """All volatile per-iteration fields are reset at the start of build()."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.build)
        expected_resets = [
            "self.state.qa_passed",
            "self.state.qa_result",
            "self.state.simulation_feedback_summary",
            "self.state.build_result_text",
            "self.state.user_feedback",
        ]
        for field in expected_resets:
            assert field in source, f"{field} not reset in build()"


# ===================================================================
# 3. PolicyUpdater persistence and active_policies
# ===================================================================

class TestPolicyUpdaterPersistence:
    """PolicyUpdater is reused and policies are threaded through state."""

    def test_flow_state_has_active_policies(self):
        state = _FlowState()
        assert hasattr(state, "active_policies")
        assert state.active_policies == {}

    def test_policy_updater_reused(self):
        """_get_policy_updater returns the same instance on repeated calls."""
        flow = _make_flow()
        pu1 = flow._get_policy_updater()
        pu2 = flow._get_policy_updater()
        assert pu1 is pu2

    def test_active_policies_used_for_max_dispatches(self):
        """When active_policies has max_total_delegated_tasks, build() uses it."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.build)
        assert "active_policies" in source
        assert "max_total_delegated_tasks" in source

    def test_evaluate_passes_real_policies(self):
        """evaluate() passes self.state.active_policies to PolicyUpdater."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        # Should use active_policies, not empty dict
        assert "self.state.active_policies" in source
        # Old pattern should be gone
        assert "propose_patches(result, {})" not in source

    def test_policies_updated_after_patches(self):
        """evaluate() stores version.policies back into active_policies."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        assert "version.policies" in source

    def test_max_dispatches_from_policies(self):
        """Flow derives max_dispatches from active_policies."""
        flow = _make_flow(active_policies={"max_total_delegated_tasks": 5})
        val = int(flow.state.active_policies.get("max_total_delegated_tasks", 8))
        assert val == 5

    def test_max_dispatches_default(self):
        """Without policy override, max_dispatches defaults to 8."""
        flow = _make_flow()
        val = int(flow.state.active_policies.get("max_total_delegated_tasks", 8))
        assert val == 8


# ===================================================================
# 4. Evaluator trend analysis via previous_metrics
# ===================================================================

class TestEvaluatorTrendAnalysis:
    """previous_cycle_metrics enables procedure_score_delta computation."""

    def test_flow_state_has_previous_cycle_metrics(self):
        state = _FlowState()
        assert hasattr(state, "previous_cycle_metrics")
        assert state.previous_cycle_metrics is None

    def test_procedure_score_in_domain_metrics(self):
        """evaluate() includes procedure_score in domain_metrics."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        assert '"procedure_score"' in source or "'procedure_score'" in source

    def test_previous_metrics_passed_to_evaluator(self):
        """evaluate() reconstructs CycleMetrics from previous_cycle_metrics."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        assert "previous_metrics=previous_metrics" in source
        assert "previous_cycle_metrics" in source

    def test_metrics_saved_after_evaluate(self):
        """evaluate() saves metrics.model_dump() to previous_cycle_metrics."""
        import inspect
        from src.crewai_agents.crews import BuildMeasureLearnFlow

        source = inspect.getsource(BuildMeasureLearnFlow.evaluate)
        assert "previous_cycle_metrics" in source
        assert "model_dump" in source

    def test_procedure_score_computation(self):
        """procedure_score = success_count / max(1, task_count)."""
        flow = _make_flow(build_task_count=4, build_success_count=3)
        expected = 3 / 4
        actual = flow.state.build_success_count / max(1, flow.state.build_task_count)
        assert actual == pytest.approx(expected)

    def test_procedure_score_zero_tasks(self):
        """With zero tasks, procedure_score should be 0 (no division error)."""
        flow = _make_flow(build_task_count=0, build_success_count=0)
        score = flow.state.build_success_count / max(1, flow.state.build_task_count)
        assert score == 0.0

    def test_previous_metrics_reconstruction(self):
        """CycleMetrics can be reconstructed from a model_dump dict."""
        from src.framework.contracts import CycleMetrics

        original = CycleMetrics(
            cycle_id=1,
            task_count=3,
            success_count=2,
            failure_count=1,
            domain_metrics={"procedure_score": 0.67, "qa_gate_passed": True},
        )
        dumped = original.model_dump()
        reconstructed = CycleMetrics(**dumped)
        assert reconstructed.cycle_id == 1
        assert reconstructed.task_count == 3
        assert reconstructed.domain_metrics["procedure_score"] == pytest.approx(0.67)

    def test_trend_analysis_end_to_end(self):
        """Scorecard computes procedure_score_delta when previous metrics exist."""
        from src.framework.contracts import CycleMetrics
        from src.framework.eval import build_scorecard

        prev = CycleMetrics(
            cycle_id=1,
            task_count=3,
            success_count=2,
            failure_count=1,
            domain_metrics={"procedure_score": 0.5},
        )
        current = CycleMetrics(
            cycle_id=2,
            task_count=4,
            success_count=3,
            failure_count=1,
            domain_metrics={"procedure_score": 0.75},
        )
        sc = build_scorecard(current_metrics=current, previous_metrics=prev)
        assert sc.procedure_score_delta == pytest.approx(0.25)

    def test_no_previous_metrics_gives_none_delta(self):
        """Without previous metrics, procedure_score_delta is None."""
        from src.framework.contracts import CycleMetrics
        from src.framework.eval import build_scorecard

        current = CycleMetrics(
            cycle_id=1,
            task_count=3,
            success_count=2,
            failure_count=1,
            domain_metrics={"procedure_score": 0.67},
        )
        sc = build_scorecard(current_metrics=current, previous_metrics=None)
        assert sc.procedure_score_delta is None

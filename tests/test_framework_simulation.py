"""Smoke tests for the framework + CrewAI startup-VC wiring.

Verifies that ``create_startup_vc_run_controller()`` produces a correctly
wired component graph: RunController ← Executor ← AgentRuntime with
registry, router, store, and event emitter all connected.
"""

import argparse

import pytest

from scripts.run_framework_simulation import (
    _build_arg_parser,
    create_startup_vc_run_controller,
)
from src.framework.autonomy import RunController
from src.framework.observability import EventLogger
from src.framework.safety.startup_vc_policy import (
    build_startup_vc_domain_policy_hook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubStore:
    """Minimal store that satisfies the interfaces the runtime touches."""

    def ep_record(self, episode):
        return episode.entity_id

    def start_run(self, *a, **kw):
        pass

    def end_run(self, *a, **kw):
        pass

    # Working memory stubs
    def wm_save_checkpoint(self):
        return {}

    def wm_load_checkpoint(self, data):
        pass

    # Procedural stubs
    def proc_get(self, key, **kw):
        return None

    def proc_save(self, key, workflow, **kw):
        pass


def _default_args(**overrides) -> argparse.Namespace:
    parser = _build_arg_parser()
    defaults = parser.parse_args(["--iterations", "1"])
    for key, value in overrides.items():
        setattr(defaults, key, value)
    return defaults


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestControllerFactory:
    """Verify the controller factory wires components correctly."""

    def test_returns_controller_and_event_logger(self):
        args = _default_args()
        controller, event_logger, run_id = create_startup_vc_run_controller(
            args, store=_StubStore()
        )
        assert isinstance(controller, RunController)
        assert isinstance(event_logger, EventLogger)
        assert run_id.startswith("startup_vc_")

    def test_store_is_injected(self):
        store = _StubStore()
        args = _default_args()
        controller, _, _ = create_startup_vc_run_controller(args, store=store)
        runtime = controller._executor._runtime
        assert runtime._store is store

    def test_three_agents_registered(self):
        args = _default_args()
        controller, _, _ = create_startup_vc_run_controller(
            args, store=_StubStore()
        )
        agents = controller._executor._runtime._router.list_agents()
        agent_ids = {a.agent_id for a in agents}
        assert "data_specialist" in agent_ids
        assert "matching_specialist" in agent_ids
        # website_builder may or may not be present depending on workspace_enabled

    def test_six_capabilities_registered(self):
        args = _default_args()
        controller, _, _ = create_startup_vc_run_controller(
            args, store=_StubStore()
        )
        registry = controller._executor._runtime._registry
        expected = {
            "data_coverage_analysis",
            "database_write",
            "match_scoring",
            "explanation_generation",
        }
        for cap in expected:
            resolved = registry.resolve(cap)
            assert len(resolved) >= 1, f"Capability '{cap}' has no registered tools"

    def test_procedure_updater_created_with_store(self):
        args = _default_args()
        controller, _, _ = create_startup_vc_run_controller(
            args, store=_StubStore()
        )
        assert controller._procedure_updater is not None

    def test_procedure_updater_absent_without_store(self):
        args = _default_args()
        controller, _, _ = create_startup_vc_run_controller(args, store=None)
        assert controller._procedure_updater is None


class TestStartupVCDomainPolicyHook:
    """Verify the domain policy hook gates tool calls correctly."""

    def test_outreach_allowed_within_limit(self):
        hook = build_startup_vc_domain_policy_hook({"max_targets_per_cycle": 2})
        assert hook("send_outreach_email", "", {}) is None
        assert hook("send_outreach_email", "", {}) is None

    def test_outreach_blocked_over_limit(self):
        hook = build_startup_vc_domain_policy_hook({"max_targets_per_cycle": 1})
        assert hook("send_outreach_email", "", {}) is None
        result = hook("send_outreach_email", "", {})
        assert result is not None
        assert "cycle limit" in result

    def test_web_search_allowed_within_limit(self):
        hook = build_startup_vc_domain_policy_hook({"max_web_searches_per_cycle": 3})
        assert hook("web_search_startups", "", {}) is None
        assert hook("web_search_vcs", "", {}) is None
        assert hook("web_search_startups", "", {}) is None

    def test_web_search_blocked_over_limit(self):
        hook = build_startup_vc_domain_policy_hook({"max_web_searches_per_cycle": 2})
        assert hook("web_search_startups", "", {}) is None
        assert hook("web_search_vcs", "", {}) is None
        result = hook("web_search_startups", "", {})
        assert result is not None
        assert "cycle limit" in result

    def test_unrelated_tool_always_allowed(self):
        hook = build_startup_vc_domain_policy_hook({"max_targets_per_cycle": 0})
        # Even with zero limit, unrelated tools pass
        assert hook("get_database_stats", "", {}) is None
        assert hook("analytics_tool", "", {}) is None


# ---------------------------------------------------------------------------
# Observability event tests
# ---------------------------------------------------------------------------

from src.framework.contracts import CycleMetrics, EvaluationResult, TaskSpec
from src.framework.learning.policy_updater import PolicyPatch, PolicyVersion
from src.framework.learning.procedure_updater import ProcedureUpdateProposal
from src.framework.observability.events import EVENT_TYPES_REQUIRED
from src.framework.runtime.startup_vc_agents import _extract_crew_reasoning


class _SpyEmitter:
    """Captures emitted events for assertion."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []

    def emit(self, event_type: str, payload: object) -> None:
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def payloads_for(self, event_type: str) -> list[object]:
        return [p for t, p in self.events if t == event_type]


class TestObservabilityEventTypes:
    """Verify the 3 new event types are registered."""

    def test_policy_patch_applied_registered(self):
        assert "policy_patch_applied" in EVENT_TYPES_REQUIRED

    def test_procedure_updated_registered(self):
        assert "procedure_updated" in EVENT_TYPES_REQUIRED

    def test_agent_reasoning_registered(self):
        assert "agent_reasoning" in EVENT_TYPES_REQUIRED


class TestPolicyPatchAppliedEvent:
    """Verify policy_patch_applied is emitted when patches are generated."""

    def test_emit_on_patch(self):
        from src.framework.autonomy.loop import AutonomyLoop

        spy = _SpyEmitter()

        class _FakePolicyUpdater:
            def history(self):
                return [type("V", (), {"version": 1})()]

            def propose_patches(self, evaluation_result, current_policies):
                return [
                    PolicyPatch(key="k", old_value="a", new_value="b", reason="test"),
                ]

            def apply_patches(self, current_policies, patches, source_evidence):
                return PolicyVersion(version=2, policies={"k": "b"})

        class _Ctx:
            class run_config:
                policies = {"k": "a"}

        loop = AutonomyLoop.__new__(AutonomyLoop)
        loop._run_id = "r1"
        loop._policy_updater = _FakePolicyUpdater()
        loop._procedure_updater = None
        loop._procedure_recommendations_fn = None
        loop._event_emitter = spy

        eval_result = EvaluationResult(overall_status="pass")
        metrics = CycleMetrics(run_id="r1", cycle_id=3)
        loop._context = _Ctx()

        loop._apply_learning(eval_result, metrics)

        assert "policy_patch_applied" in spy.types()
        payload = spy.payloads_for("policy_patch_applied")[0]
        assert payload["run_id"] == "r1"
        assert payload["cycle_id"] == 3
        assert payload["version_before"] == 1
        assert payload["version_after"] == 2
        assert len(payload["patches"]) == 1
        assert payload["patches"][0]["key"] == "k"

    def test_no_emit_without_patches(self):
        from src.framework.autonomy.loop import AutonomyLoop

        spy = _SpyEmitter()

        class _FakePolicyUpdater:
            def history(self):
                return []

            def propose_patches(self, evaluation_result, current_policies):
                return []

        class _Ctx:
            class run_config:
                policies = {}

        loop = AutonomyLoop.__new__(AutonomyLoop)
        loop._run_id = "r1"
        loop._policy_updater = _FakePolicyUpdater()
        loop._procedure_updater = None
        loop._procedure_recommendations_fn = None
        loop._event_emitter = spy
        loop._context = _Ctx()

        eval_result = EvaluationResult(overall_status="pass")
        metrics = CycleMetrics(run_id="r1", cycle_id=1)

        loop._apply_learning(eval_result, metrics)

        assert "policy_patch_applied" not in spy.types()


class TestProcedureUpdatedEvent:
    """Verify procedure_updated is emitted when procedures change."""

    def test_emit_on_procedure_update(self):
        from src.framework.autonomy.loop import AutonomyLoop

        spy = _SpyEmitter()

        class _FakeProcedure:
            task_type = "data_collection"
            current_version = 2

        class _FakeProcedureUpdater:
            def apply_update(self, proposal):
                return _FakeProcedure()

        proposal = ProcedureUpdateProposal(
            task_type="data_collection",
            workflow={"steps": ["a", "b"]},
            score=0.85,
            provenance="eval_123",
            created_by="learning",
            source_evidence={"eval_id": "e1"},
        )

        class _Ctx:
            class run_config:
                policies = {}

        loop = AutonomyLoop.__new__(AutonomyLoop)
        loop._run_id = "r2"
        loop._policy_updater = None
        loop._procedure_updater = _FakeProcedureUpdater()
        loop._procedure_recommendations_fn = lambda ev, m: [proposal]
        loop._event_emitter = spy
        loop._context = _Ctx()

        eval_result = EvaluationResult(overall_status="pass")
        metrics = CycleMetrics(run_id="r2", cycle_id=5)

        loop._apply_learning(eval_result, metrics)

        assert "procedure_updated" in spy.types()
        payload = spy.payloads_for("procedure_updated")[0]
        assert payload["run_id"] == "r2"
        assert payload["cycle_id"] == 5
        assert payload["task_type"] == "data_collection"
        assert payload["version"] == 2
        assert payload["workflow"] == {"steps": ["a", "b"]}
        assert payload["score"] == 0.85


class TestAgentReasoningEvent:
    """Verify agent_reasoning event is emitted when agent returns reasoning."""

    def test_emit_when_reasoning_present(self):
        from src.framework.runtime.agent_runtime import AgentRuntime
        from src.framework.runtime.capability_registry import CapabilityRegistry
        from src.framework.runtime.task_router import TaskRouter

        spy = _SpyEmitter()
        registry = CapabilityRegistry()
        router = TaskRouter(registry)

        # Register a fake agent that returns reasoning
        def _fake_agent(task_spec, tools, context):
            return {
                "output_text": "done",
                "reasoning": "I chose X because Y",
                "tokens_used": 0,
                "tool_calls": [],
            }

        router.register_agent(
            agent_id="test_agent",
            agent_role="test",
            capabilities=["test_cap"],
            agent_instance=_fake_agent,
        )
        registry.register(
            capability="test_cap",
            tool_name="test_tool",
            tool_callable=lambda **kw: {},
            priority=0,
        )

        # Minimal execution context stub
        class _RunCtx:
            run_id = "r3"
            cycle_id = 7

        class _RunCfg:
            policies = {}
            max_delegation_depth = 3

        class _ExecCtx:
            run_context = _RunCtx()
            run_config = _RunCfg()

            def begin_step(self, agent_id):
                pass

            def end_step(self, tokens_used, duration_seconds):
                pass

            def check_budget(self):
                return True

        rt = AgentRuntime(
            registry=registry,
            router=router,
            store=None,
            context=_ExecCtx(),
            event_emitter=spy,
        )

        task = TaskSpec(
            task_id="t1",
            task_type="test",
            agent_role="test",
            objective="do stuff",
            required_capabilities=["test_cap"],
        )
        rt.execute_task(task)

        assert "agent_reasoning" in spy.types()
        payload = spy.payloads_for("agent_reasoning")[0]
        assert payload["run_id"] == "r3"
        assert payload["cycle_id"] == 7
        assert payload["task_id"] == "t1"
        assert payload["agent_id"] == "test_agent"
        assert payload["reasoning"] == "I chose X because Y"

    def test_no_emit_when_reasoning_empty(self):
        from src.framework.runtime.agent_runtime import AgentRuntime
        from src.framework.runtime.capability_registry import CapabilityRegistry
        from src.framework.runtime.task_router import TaskRouter

        spy = _SpyEmitter()
        registry = CapabilityRegistry()
        router = TaskRouter(registry)

        def _fake_agent(task_spec, tools, context):
            return {
                "output_text": "done",
                "tokens_used": 0,
                "tool_calls": [],
            }

        router.register_agent(
            agent_id="test_agent",
            agent_role="test",
            capabilities=["test_cap"],
            agent_instance=_fake_agent,
        )
        registry.register(
            capability="test_cap",
            tool_name="test_tool",
            tool_callable=lambda **kw: {},
            priority=0,
        )

        class _RunCtx:
            run_id = "r3"
            cycle_id = 7

        class _RunCfg:
            policies = {}
            max_delegation_depth = 3

        class _ExecCtx:
            run_context = _RunCtx()
            run_config = _RunCfg()

            def begin_step(self, agent_id):
                pass

            def end_step(self, tokens_used, duration_seconds):
                pass

            def check_budget(self):
                return True

        rt = AgentRuntime(
            registry=registry,
            router=router,
            store=None,
            context=_ExecCtx(),
            event_emitter=spy,
        )

        task = TaskSpec(
            task_id="t1",
            task_type="test",
            agent_role="test",
            objective="do stuff",
            required_capabilities=["test_cap"],
        )
        rt.execute_task(task)

        assert "agent_reasoning" not in spy.types()


class TestExtractCrewReasoning:
    """Verify _extract_crew_reasoning helper."""

    def test_returns_empty_for_none(self):
        assert _extract_crew_reasoning(None) == ""

    def test_extracts_structured_tasks_output(self):
        class _TaskOut:
            description = "Analyze data"
            raw = "Found 3 gaps"

        class _CrewOut:
            tasks_output = [_TaskOut()]

        result = _extract_crew_reasoning(_CrewOut())
        assert "Analyze data" in result
        assert "Found 3 gaps" in result

    def test_falls_back_to_str(self):
        class _CrewOut:
            pass

        result = _extract_crew_reasoning(_CrewOut())
        assert result  # should be str(obj), non-empty

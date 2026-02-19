"""Runtime agents and wiring helpers for web-product autonomy."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from src.framework.runtime.capability_registry import CapabilityRegistry
from src.framework.runtime.task_router import TaskRouter
from src.framework.types import ToolCallStatus
from src.framework.web_constants import (
    CAP_BROWSER_NAVIGATE,
    CAP_CODE_EDIT,
    CAP_RESTART_SERVICE,
    CAP_RUN_TESTS,
    ROLE_WEB_EXPLORER,
    ROLE_WEB_IMPROVER,
    ROLE_WEB_VALIDATOR,
)


def _tool_error_message(tool_call: Any) -> str:
    status = getattr(tool_call.call_status, "value", str(tool_call.call_status))
    if getattr(tool_call, "denied_reason", None):
        return f"{status}: {tool_call.denied_reason}"
    if getattr(tool_call, "error_message", None):
        return f"{status}: {tool_call.error_message}"
    return status


def _require_tool_success(
    *,
    runtime: Any,
    capability: str,
    arguments: Dict[str, Any],
    agent_id: str,
    task_id: str,
) -> Any:
    tool_call = runtime.execute_tool_call(
        tool_name=capability,
        capability=capability,
        arguments=arguments,
        agent_id=agent_id,
        task_id=task_id,
    )
    if tool_call.call_status != ToolCallStatus.SUCCESS:
        raise RuntimeError(
            f"{capability} failed for task {task_id}: {_tool_error_message(tool_call)}"
        )
    return tool_call


def make_web_explorer_agent(
    runtime: Any,
    *,
    default_url: str,
) -> Callable[..., Dict[str, Any]]:
    """Agent callable that explores a localhost web endpoint."""

    def agent(task_spec, tools, context) -> Dict[str, Any]:
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        cycle_id = getattr(task_spec, "cycle_id", None)
        url = str(input_data.get("url") or default_url)
        selector = input_data.get("selector")
        wait_ms = int(input_data.get("wait_ms", 0))

        call = _require_tool_success(
            runtime=runtime,
            capability=CAP_BROWSER_NAVIGATE,
            arguments={
                "url": url,
                "selector": selector,
                "wait_ms": wait_ms,
                "cycle_id": cycle_id,
            },
            agent_id=ROLE_WEB_EXPLORER,
            task_id=task_spec.task_id,
        )

        return {
            "output_text": f"Explored web product at {url}",
            "navigation": call.result,
            "tool_calls": [call.entity_id],
            "tokens_used": 0,
        }

    return agent


def make_web_improver_agent(runtime: Any) -> Callable[..., Dict[str, Any]]:
    """Agent callable that applies bounded local code edits."""

    def agent(task_spec, tools, context) -> Dict[str, Any]:
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        cycle_id = getattr(task_spec, "cycle_id", None)

        path = input_data.get("path")
        if not path:
            return {
                "output_text": "No edit instruction provided for this cycle",
                "edits_applied": 0,
                "tokens_used": 0,
                "tool_calls": [],
            }

        search = str(input_data.get("search", ""))
        replace = str(input_data.get("replace", ""))
        dry_run = bool(input_data.get("dry_run", False))
        max_replacements = int(input_data.get("max_replacements", 1))
        create_if_missing = bool(input_data.get("create_if_missing", False))

        call = _require_tool_success(
            runtime=runtime,
            capability=CAP_CODE_EDIT,
            arguments={
                "path": str(path),
                "search": search,
                "replace": replace,
                "max_replacements": max_replacements,
                "create_if_missing": create_if_missing,
                "dry_run": dry_run,
                "cycle_id": cycle_id,
            },
            agent_id=ROLE_WEB_IMPROVER,
            task_id=task_spec.task_id,
        )
        result = call.result if isinstance(call.result, dict) else {}
        changed = result.get("status") == "success"

        return {
            "output_text": f"Code edit completed for {path}",
            "edit_result": result,
            "edits_applied": 1 if changed and not dry_run else 0,
            "tool_calls": [call.entity_id],
            "tokens_used": 0,
        }

    return agent


def make_web_validator_agent(runtime: Any) -> Callable[..., Dict[str, Any]]:
    """Agent callable that runs tests and optionally restarts services."""

    def agent(task_spec, tools, context) -> Dict[str, Any]:
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        cycle_id = getattr(task_spec, "cycle_id", None)

        test_command = input_data.get("test_command")
        test_timeout = int(input_data.get("test_timeout_seconds", 120))

        test_call = _require_tool_success(
            runtime=runtime,
            capability=CAP_RUN_TESTS,
            arguments={
                "command": test_command,
                "timeout_seconds": test_timeout,
                "cycle_id": cycle_id,
            },
            agent_id=ROLE_WEB_VALIDATOR,
            task_id=task_spec.task_id,
        )
        test_result = test_call.result if isinstance(test_call.result, dict) else {}
        if test_result.get("tests_passed") is not True:
            raise RuntimeError(
                f"Validation failed: tests did not pass ({test_result.get('status')})"
            )

        tool_calls: List[str] = [test_call.entity_id]
        restart_status = "skipped"

        if bool(input_data.get("restart", True)):
            restart_call = _require_tool_success(
                runtime=runtime,
                capability=CAP_RESTART_SERVICE,
                arguments={
                    "command": input_data.get("restart_command"),
                    "timeout_seconds": int(input_data.get("restart_timeout_seconds", 60)),
                    "cycle_id": cycle_id,
                },
                agent_id=ROLE_WEB_VALIDATOR,
                task_id=task_spec.task_id,
            )
            restart_result = (
                restart_call.result if isinstance(restart_call.result, dict) else {}
            )
            restart_status = str(restart_result.get("status", "unknown"))
            tool_calls.append(restart_call.entity_id)

        return {
            "output_text": "Validation completed successfully",
            "tests_passed": True,
            "restart_status": restart_status,
            "tool_calls": tool_calls,
            "tokens_used": 0,
        }

    return agent


def register_web_capabilities(
    registry: CapabilityRegistry,
    toolset: Any,
) -> None:
    """Register localhost tooling capabilities in a registry."""

    registry.register(
        capability=CAP_BROWSER_NAVIGATE,
        tool_name=CAP_BROWSER_NAVIGATE,
        tool_callable=toolset.browser_navigate,
        priority=0,
    )
    registry.register(
        capability=CAP_CODE_EDIT,
        tool_name=CAP_CODE_EDIT,
        tool_callable=toolset.code_edit,
        priority=0,
    )
    registry.register(
        capability=CAP_RUN_TESTS,
        tool_name=CAP_RUN_TESTS,
        tool_callable=toolset.run_tests,
        priority=0,
    )
    registry.register(
        capability=CAP_RESTART_SERVICE,
        tool_name=CAP_RESTART_SERVICE,
        tool_callable=toolset.restart_service,
        priority=0,
    )


def register_web_agents(
    router: TaskRouter,
    runtime: Any,
    *,
    default_url: str,
) -> None:
    """Register runtime agents for web exploration, editing, and validation."""

    router.register_agent(
        agent_id=ROLE_WEB_EXPLORER,
        agent_role=ROLE_WEB_EXPLORER,
        capabilities=[CAP_BROWSER_NAVIGATE],
        agent_instance=make_web_explorer_agent(runtime, default_url=default_url),
    )
    router.register_agent(
        agent_id=ROLE_WEB_IMPROVER,
        agent_role=ROLE_WEB_IMPROVER,
        capabilities=[CAP_CODE_EDIT],
        agent_instance=make_web_improver_agent(runtime),
    )
    router.register_agent(
        agent_id=ROLE_WEB_VALIDATOR,
        agent_role=ROLE_WEB_VALIDATOR,
        capabilities=[CAP_RUN_TESTS, CAP_RESTART_SERVICE],
        agent_instance=make_web_validator_agent(runtime),
    )

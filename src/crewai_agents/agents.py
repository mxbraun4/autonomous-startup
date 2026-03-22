"""CrewAI Agents - Convert our Planners to Agents."""

from typing import Any, Optional

from src.crewai_agents.runtime_env import configure_runtime_environment
from src.utils.config import settings

configure_runtime_environment()
from crewai import Agent, LLM
from src.crewai_agents.mock_llm import DeterministicMockLLM
from src.crewai_agents.tools import (
    # Database tools
    get_database_stats,
    # Analysis tools
    run_quality_checks_tool,
    # Consensus memory tools
    share_insight,
    get_team_insights,
    get_cycle_history,
    # Role-aware share_insight factory
    make_share_insight,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


_litellm_patched = False

# Module-level context for the current cycle, updated by the flow before
# each crew kickoff so that litellm tracing events carry iteration info.
_current_cycle_id: int | None = None


def set_current_cycle_id(cycle_id: int | None) -> None:
    """Set the active cycle/iteration id for litellm tracing."""
    global _current_cycle_id
    _current_cycle_id = cycle_id


def _extract_agent_from_messages(messages: list) -> str:
    """Best-effort extraction of the CrewAI agent role from the system message."""
    if not messages:
        return ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "system":
            continue
        content = str(msg.get("content", ""))
        # CrewAI system prompts: "You are <Role>. You are a <backstory>..."
        # Split on first period to isolate the role name.
        if content.startswith("You are "):
            after_prefix = content[len("You are "):]
            role = after_prefix.split(".")[0].strip()
            if role:
                return role
    return ""


def ensure_litellm_tracing() -> None:
    """Monkey-patch ``litellm.completion`` to emit ``llm_call`` events.

    CrewAI overwrites ``litellm.callbacks`` during every ``kickoff()``,
    so a callback-based approach cannot survive.  Instead we wrap the
    completion function itself, which is immune to list resets.
    """
    global _litellm_patched
    if _litellm_patched:
        return
    _litellm_patched = True

    try:
        import litellm
    except ImportError:
        return

    import time as _time
    _original = litellm.completion

    # Track tool_call_ids we've already emitted results for, to avoid duplicates
    _emitted_tool_results: set = set()

    def _traced_completion(*args: Any, **kwargs: Any) -> Any:
        t0 = _time.monotonic()
        result = _original(*args, **kwargs)
        duration_ms = round((_time.monotonic() - t0) * 1000, 1)

        try:
            from src.crewai_agents.tools import get_event_logger

            el = get_event_logger()
            if el is None:
                return result

            model = str(kwargs.get("model", ""))
            messages = kwargs.get("messages") or (args[1] if len(args) > 1 else [])

            # Emit tool_result events for tool results in the incoming messages.
            # After CrewAI executes a tool, it appends a role="tool" message
            # with the actual return value before calling the LLM again.
            if isinstance(messages, list):
                agent_for_results = _extract_agent_from_messages(messages)
                for m in messages:
                    if not isinstance(m, dict) or m.get("role") != "tool":
                        continue
                    tc_id = m.get("tool_call_id", "")
                    if tc_id in _emitted_tool_results:
                        continue
                    _emitted_tool_results.add(tc_id)
                    content = str(m.get("content", ""))
                    # Truncate large results to keep event log manageable
                    truncated = len(content) > 2000
                    tr_payload: dict[str, Any] = {
                        "tool_call_id": tc_id,
                        "result": content[:2000],
                        "truncated": truncated,
                        "agent": agent_for_results,
                    }
                    if _current_cycle_id is not None:
                        tr_payload["cycle_id"] = _current_cycle_id
                    el.emit("tool_result", tr_payload)
            # Capture all message content for full exchange visibility
            if isinstance(messages, list) and messages:
                msg_parts = []
                for m in messages:
                    role = m.get("role", "?")
                    content = str(m.get("content", ""))
                    if content:
                        msg_parts.append(f"[{role}] {content}")
                msg_summary = "\n\n".join(msg_parts)
            else:
                msg_summary = ""

            resp_text = ""
            if hasattr(result, "choices") and result.choices:
                choice = result.choices[0]
                if hasattr(choice, "message"):
                    resp_text = str(choice.message.content or "")
                    # Deepseek and other models may return empty content with tool_calls
                    if not resp_text and hasattr(choice.message, "tool_calls"):
                        tool_calls = choice.message.tool_calls
                        if tool_calls:
                            tc = tool_calls[0]
                            tc_name = getattr(tc, "function", None)
                            if tc_name is not None:
                                tc_name = getattr(tc_name, "name", str(tc_name))
                            tc_args = ""
                            if hasattr(tc, "function") and hasattr(tc.function, "arguments"):
                                tc_args = str(tc.function.arguments or "")
                            resp_text = f"[tool_call] {tc_name}({tc_args})"
            resp_summary = resp_text

            agent_name = _extract_agent_from_messages(
                messages if isinstance(messages, list) else []
            )

            # Extract token usage from litellm response
            tokens_info: dict[str, int] = {}
            if hasattr(result, "usage") and result.usage is not None:
                usage = result.usage
                tokens_info = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }

            payload: dict[str, Any] = {
                "agent": agent_name,
                "model": model,
                "message_summary": msg_summary,
                "response_summary": resp_summary,
                "duration_ms": duration_ms,
                "tokens": tokens_info,
            }
            if _current_cycle_id is not None:
                payload["cycle_id"] = _current_cycle_id

            el.emit("llm_call", payload)

            # Emit tool_called events for every tool the model invoked
            if hasattr(result, "choices") and result.choices:
                tc_list = getattr(result.choices[0].message, "tool_calls", None) or []
                for tc in tc_list:
                    tc_fn = getattr(tc, "function", None)
                    tc_name = getattr(tc_fn, "name", "") if tc_fn else ""
                    tc_args = getattr(tc_fn, "arguments", "") if tc_fn else ""
                    tc_id = getattr(tc, "id", "") or ""
                    tc_payload: dict[str, Any] = {
                        "tool_name": tc_name,
                        "arguments": str(tc_args),
                        "tool_call_id": tc_id,
                        "agent": agent_name,
                    }
                    if _current_cycle_id is not None:
                        tc_payload["cycle_id"] = _current_cycle_id
                    el.emit("tool_called", tc_payload)
        except Exception:
            pass

        return result

    litellm.completion = _traced_completion
    logger.info("litellm.completion patched for llm_call tracing")


def _with_prompt_override(backstory: str, prompt_override: Optional[str]) -> str:
    override = str(prompt_override or "").strip()
    if not override:
        return backstory
    return f"{backstory}\n\nAutonomous prompt refinement:\n- {override}"


def _normalize_role(role: Optional[str]) -> str:
    text = str(role or "").strip().lower()
    aliases = {
        "strategic_coordinator": "coordinator",
        "master_coordinator": "coordinator",
        "product_strategist": "product",
        "developer_agent": "developer",
        "reviewer": "reviewer",
        "qa": "reviewer",
        "reviewer_agent": "reviewer",
        "engineering": "developer",
        "data": "developer",
        "data_strategist": "developer",
    }
    return aliases.get(text, text)


def _openrouter_model_for_role(role: Optional[str]) -> str:
    normalized = _normalize_role(role)
    attr_map = {
        "coordinator": "coordinator_model",
        "product": "product_model",
        "developer": "developer_model",
        "reviewer": "reviewer_model",
    }

    attrs = []
    mapped = attr_map.get(normalized)
    if mapped:
        attrs.append(mapped)
    attrs.append("openrouter_default_model")

    for attr in attrs:
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            return value
    return ""


_registered_models: set = set()


def _ensure_litellm_model_info(model: str) -> None:
    """Register model capabilities with LiteLLM if not already known.

    LiteLLM's model registry may not include every OpenRouter variant (e.g.
    ``openrouter/qwen/qwen3-coder-next``).  When a model is unknown, CrewAI
    falls back to ReAct text parsing instead of native function calling,
    which causes frequent JSON formatting errors from smaller LLMs.

    This registers the model as supporting function calling so CrewAI uses
    the native tool-call API path.
    """
    if model in _registered_models:
        return
    _registered_models.add(model)

    try:
        import litellm
        litellm.get_model_info(model)
        return  # Already known
    except Exception:
        pass

    try:
        import litellm
        # Infer provider from model string (e.g. "openrouter/qwen/..." -> "openrouter")
        provider = model.split("/")[0] if "/" in model else ""
        litellm.register_model({
            model: {
                "mode": "chat",
                "supports_function_calling": True,
                "supports_tool_choice": True,
                "litellm_provider": provider,
            },
        })
        logger.info("Registered %s with litellm (function calling enabled)", model)
    except Exception:
        pass  # non-critical; will fall back to ReAct


def _build_openrouter_llm(model: str) -> LLM:
    _ensure_litellm_model_info(model)
    return LLM(
        model=model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


def get_llm(role: Optional[str] = None) -> LLM | DeterministicMockLLM:
    """Get an LLM instance based on configuration and optional role.

    When ``OPENROUTER_API_KEY`` is configured (and ``MOCK_MODE=false``), role-
    specific models are selected for coordinator/product/developer/reviewer.
    """
    if settings.mock_mode:
        return DeterministicMockLLM()

    if settings.openrouter_api_key:
        model = _openrouter_model_for_role(role)
        if not model:
            raise RuntimeError(
                "OPENROUTER_API_KEY is set but no OpenRouter model could be resolved"
            )
        return _build_openrouter_llm(model)

    if settings.anthropic_api_key:
        return LLM(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )

    if settings.openai_api_key:
        return LLM(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )

    raise RuntimeError(
        "No LLM configured: set MOCK_MODE=true or provide OPENROUTER_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY"
    )


def create_master_coordinator(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
    extra_tools: Optional[list] = None,
) -> Agent:
    """Create the Master Coordinator agent.

    This agent orchestrates the Build-Measure-Learn cycle and delegates
    to specialized strategist agents.

    Args:
        llm: LLM instance to use
        extra_tools: Additional tools to attach (e.g. workspace read/list tools)

    Returns:
        Master Coordinator agent
    """
    backstory = _with_prompt_override(
        '''You are a startup ecosystem coordinator. You analyze build results, extract learnings, and formulate recommendations for the next iteration. Respond with a structured text analysis — do NOT call tools.''',
        prompt_override,
    )

    tools = []
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='Strategic Coordinator',
        goal='Analyze iteration results and produce actionable insights for the next Build-Measure-Learn cycle',
        backstory=backstory,
        llm=llm or get_llm("coordinator"),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        memory=False,
        max_iter=5,
    )


def create_build_coordinator(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
    extra_tools: Optional[list] = None,
) -> Agent:
    """Create the BUILD Coordinator agent.

    This agent orchestrates the BUILD phase by dispatching tasks to specialist
    agents (product_strategist, developer, reviewer) via the dispatch_task tool
    and deciding whether to loop back based on results.

    Args:
        llm: LLM instance to use
        prompt_override: Optional autonomous prompt refinement string
        extra_tools: Additional tools (dispatch_task tool + workspace read tools injected by caller)

    Returns:
        BUILD Coordinator agent
    """
    backstory = _with_prompt_override(
        '''You coordinate the BUILD phase of a startup-VC matching platform.

Tech stack: Python Flask backend (app.py), Jinja2 HTML templates (templates/), static assets (static/css, static/js), SQLite databases (.db files). The app runs via "python app.py".

YOUR ONLY PURPOSE IS TO DISPATCH AGENTS VIA THE dispatch_task_to_agent TOOL.
You must NEVER finish without calling dispatch_task_to_agent at least once.
Do NOT write a plan as text — execute it by calling dispatch_task_to_agent.

Workflow:
1. Call list_workspace_files to see what files exist.
2. Call read_workspace_file on app.py (and other key files) to understand the current state.
3. Call dispatch_task_to_agent to assign work to agents. This is MANDATORY.

Agent roles:
- product_strategist: Analyzes feedback, defines product direction, and proposes database schema, routes, and implementation plan. Dispatch this agent first.
- developer: Builds and fixes code. Give it concrete tasks. The developer reads files on its own and writes code.
- reviewer: Reviews code quality, runs QA checks, identifies bugs.

CRITICAL: When dispatching the developer, you MUST include the product_strategist's recommendations in the task description. Example: "Following the product plan: [paste key points]. Now implement: [specific task]." Never dispatch the developer without referencing what the product_strategist recommended.

Rules:
- You MUST call dispatch_task_to_agent — do NOT give a Final Answer without dispatching.
- Developer tasks must be BUILD or FIX tasks — never "read and report back."
- NEVER ask agents to install dependencies or create requirements.txt/install_deps.py. All packages are pre-installed.
- Call ONE tool at a time, never multiple tools in parallel.''',
        prompt_override,
    )

    tools = [make_share_insight("coordinator"), get_team_insights, get_cycle_history]
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='BUILD Coordinator',
        goal='Orchestrate agents to build a startup-VC matching platform that connects startups with investors',
        backstory=backstory,
        llm=llm or get_llm("coordinator"),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        memory=True,
        max_iter=25,
    )


def create_developer_agent(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
    extra_tools: Optional[list] = None,
) -> Agent:
    """Create the Developer Agent.

    This agent implements and validates platform improvements based on product
    feedback and shared team insights.

    Args:
        llm: LLM instance to use
        extra_tools: Additional tools to attach (e.g. workspace file tools)

    Returns:
        Developer agent
    """
    backstory = _with_prompt_override(
        '''You are an autonomous web developer responsible for a startup-VC matching website.
You own the workspace — read files, write files, fix bugs, add features, refactor, whatever you judge is most impactful right now.
You have tools to inspect team insights, read/write workspace files, run SQL queries, run HTTP checks, and share what you did.

Tech stack: Python Flask backend (app.py), Jinja2 HTML templates (templates/), static assets (static/css/, static/js/), SQLite databases (.db files).
- app.py: Flask routes, database logic, form handling. Must read host/port from FLASK_RUN_HOST/FLASK_RUN_PORT env vars with sensible defaults.
- templates/: Jinja2 HTML templates. Use template inheritance (base.html) for shared layout.
- static/: CSS and JS files referenced from templates.
- You can also pull in any CDN-hosted libraries (CSS frameworks, JS libraries, icon sets, etc.) via script/link tags — no installation required.
- Use run_workspace_sql to create tables and seed data in SQLite .db files.

DEPENDENCY RULE: You CANNOT install new packages. Do NOT create requirements.txt or install_deps.py. Use list_installed_packages to check what's available.

When something needs fixing, fix it directly in app.py or the templates. Do NOT create test scripts, debug scripts, or diagnostic files (no test_*.py, debug_*.py, run_*.py). Only modify production code.''',
        prompt_override,
    )

    tools = [
        make_share_insight("developer"),
        get_team_insights,
        get_cycle_history,
    ]
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='Developer Agent',
        goal='Implement and improve platform tools/features based on product feedback with reliable, testable iterations',
        backstory=backstory,
        tools=tools,
        llm=llm or get_llm("developer"),
        verbose=True,
        allow_delegation=False,
        memory=True,
        max_iter=35,
    )


def create_product_strategist(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
    extra_tools: Optional[list] = None,
) -> Agent:
    """Create the Product Strategy Expert agent.

    This agent identifies platform needs and coordinates tool building.

    Args:
        llm: LLM instance to use
        extra_tools: Additional tools to attach (e.g. workspace read/list tools)

    Returns:
        Product Strategist agent
    """
    backstory = _with_prompt_override(
        '''You are the product architect for a startup-VC matching website built with Flask + SQLite + Jinja templates. You have tools to inspect the workspace, read team insights, and share your plans. Explore what exists, decide what the product needs (routes, database tables, templates, features), and publish your architecture plan via share_insight so other agents can act on it. Always act through tool calls, not text-only responses.

Only plan features using pre-installed packages. No new packages can be installed.''',
        prompt_override,
    )

    tools = [
        get_database_stats,
        make_share_insight("product_strategist"),
        get_team_insights,
        get_cycle_history,
    ]
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='Product Strategy Expert',
        goal='Build tools and features that enhance platform capabilities and user experience',
        backstory=backstory,
        tools=tools,
        llm=llm or get_llm("product"),
        verbose=True,
        allow_delegation=False,
        memory=True,
        max_iter=12,
    )


def create_reviewer_agent(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
    extra_tools: Optional[list] = None,
) -> Agent:
    """Create the Reviewer (QA) Agent.

    This agent runs strict quality gates (syntax/tests) and blocks broken code
    from reaching strategic review.

    Args:
        llm: LLM instance to use
        extra_tools: Additional tools to attach (e.g. workspace read/list tools)

    Returns:
        Reviewer QA agent
    """
    backstory = _with_prompt_override(
        '''You are a QA engineer for a startup-VC matching website built with Flask + SQLite + Jinja templates.

Your PRIMARY job is to run check_workspace_http to test the RUNNING app — not just read code.
Code that "looks correct" can still be broken at runtime. You MUST verify by running HTTP checks.

Workflow:
1. Call check_workspace_http to test all routes against the live Flask app.
2. If routes fail or return wrong content, report the SPECIFIC route and what went wrong.
3. If code looks correct but HTTP checks fail, say so — this means there is a runtime bug.
4. Share actionable findings via share_insight.

Do NOT just read code and say "looks good." Test it.''',
        prompt_override,
    )

    tools = [
        run_quality_checks_tool,
        make_share_insight("reviewer"),
        get_team_insights,
        get_cycle_history,
    ]
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='Reviewer (QA) Agent',
        goal='Run syntax and test checks, catch defects early, and block broken code from reaching the coordinator',
        backstory=backstory,
        tools=tools,
        llm=llm or get_llm("reviewer"),
        verbose=True,
        allow_delegation=False,
        memory=True,
        max_iter=7,
    )

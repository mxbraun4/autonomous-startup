"""CrewAI Agents - Convert our Planners to Agents."""

from typing import Any, Optional

from src.crewai_agents.runtime_env import configure_runtime_environment
from src.utils.config import settings

configure_runtime_environment()
from crewai import Agent, LLM
from src.crewai_agents.mock_llm import DeterministicMockLLM
from src.crewai_agents.tools import (
    # Web collection tools
    web_search_startups,
    web_search_vcs,
    fetch_webpage,
    run_data_collection,
    save_startup,
    save_vc,
    # Database tools
    get_startups_tool,
    get_vcs_tool,
    get_database_stats,
    # Analysis tools
    data_validator_tool,
    tool_builder_tool,
    register_dynamic_tool,
    list_dynamic_tools,
    execute_dynamic_tool,
    run_quality_checks_tool,
    # Consensus memory tools
    share_insight,
    get_team_insights,
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
            if isinstance(messages, list) and messages:
                last_msg = str(messages[-1].get("content", ""))
            else:
                last_msg = ""
            msg_summary = last_msg

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
                                tc_args = str(tc.function.arguments or "")[:100]
                            resp_text = f"[tool_call] {tc_name}({tc_args})"
            resp_summary = resp_text

            agent_name = _extract_agent_from_messages(
                messages if isinstance(messages, list) else []
            )

            payload: dict[str, Any] = {
                "agent": agent_name,
                "model": model,
                "message_summary": msg_summary,
                "response_summary": resp_summary,
                "duration_ms": duration_ms,
            }
            if _current_cycle_id is not None:
                payload["cycle_id"] = _current_cycle_id

            el.emit("llm_call", payload)
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


def _build_openrouter_llm(model: str) -> LLM:
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
    workspace_note = ""
    if extra_tools:
        workspace_note = (
            "\n\n        You also have workspace file tools that let you read and list "
            "files in a product workspace directory. Use these to inspect the current "
            "state of the website before deciding what to delegate."
        )
    backstory = _with_prompt_override(
        '''You are an experienced startup ecosystem operator who has built and scaled
        multiple platforms connecting startups with investors. You understand the importance of
        data quality, product innovation, and effective coordination. You coordinate specialized teams
        to execute on strategy, evaluate results, and adapt based on learnings.

        Your approach:
        - Start by analyzing the current state and recent performance
        - Decompose high-level goals into specific objectives for each team
        - Delegate to specialists (data, product, development) while maintaining strategic oversight
        - Synthesize results and extract learnings to improve next iteration
        '''
        + workspace_note,
        prompt_override,
    )

    tools = [make_share_insight("coordinator"), get_team_insights]
    if extra_tools:
        tools.extend(extra_tools)

    return Agent(
        role='Strategic Coordinator',
        goal='Execute Build-Evaluate-Learn cycles to continuously improve the startup-VC matching platform',
        backstory=backstory,
        llm=llm or get_llm("coordinator"),
        tools=tools,
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_data_strategist(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Data Strategy Expert agent.

    This agent identifies data gaps and coordinates data collection efforts.

    Args:
        llm: LLM instance to use

    Returns:
        Data Strategist agent
    """
    backstory = _with_prompt_override(
        '''You are an expert in data quality, coverage analysis, and gap identification.
        You can quickly spot where data is missing or outdated by comparing current coverage
        against VC investment preferences and market trends.

        Your expertise:
        - Identifying data gaps by analyzing VC interests vs. startup coverage
        - Searching the web to find and collect startup and VC data
        - Prioritizing collection efforts based on business impact
        - Ensuring data quality through validation
        - Tracking data freshness and completeness metrics

        You use web search tools to find startups and VCs, save them to the database,
        and validate data quality. Your workflow:
        1. Check database stats to understand current coverage
        2. Search web for startups/VCs in underrepresented sectors
        3. Save found data to database
        4. Validate data quality
        ''',
        prompt_override,
    )

    return Agent(
        role='Data Strategy Expert',
        goal='Maintain comprehensive, high-quality startup and VC data with zero critical gaps',
        backstory=backstory,
        tools=[
            run_data_collection,
            web_search_startups,
            web_search_vcs,
            fetch_webpage,
            save_startup,
            save_vc,
            get_startups_tool,
            get_vcs_tool,
            get_database_stats,
            data_validator_tool,
            make_share_insight("data_strategist"),
            get_team_insights,
        ],
        llm=llm or get_llm("data"),
        verbose=True,
        allow_delegation=True,
        memory=True
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
    workspace_note = ""
    if extra_tools:
        workspace_note = (
            "\n\n        You also have workspace file tools that let you read, write, and "
            "list files in a product workspace directory. Use these to build and "
            "improve HTML/CSS/JS files based on customer feedback and HTTP check results."
        )
    backstory = _with_prompt_override(
        '''You are a web developer building a startup-VC matching website.
        You write HTML, CSS, and JavaScript files in the workspace/ directory using
        the workspace file tools (write_workspace_file, read_workspace_file, list_workspace_files).

        Your approach:
        - Read the product spec from team insights before building
        - Inspect existing workspace files to understand current state
        - Write complete, well-structured HTML pages with proper styling
        - Create real website pages: landing page, founders page, investors page,
          fit-score calculator, about page, and shared navigation/styles
        - Each iteration, produce at least one new or improved HTML/CSS/JS file
        - Replace any placeholder content with real website content

        You collaborate tightly with the Product Strategy Expert. Product specs are
        shared through team insight tools, and you implement them as workspace files.
        Do NOT build internal Python tools — focus on user-facing web pages.
        '''
        + workspace_note,
        prompt_override,
    )

    tools = [
        tool_builder_tool,
        register_dynamic_tool,
        list_dynamic_tools,
        execute_dynamic_tool,
        data_validator_tool,
        get_startups_tool,
        get_vcs_tool,
        make_share_insight("developer"),
        get_team_insights,
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
        memory=True
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
    workspace_note = ""
    if extra_tools:
        workspace_note = (
            "\n\n        You also have workspace file tools that let you read and list "
            "files in a product workspace directory. Use these to inspect the current "
            "site and produce improvement requirements."
        )
    backstory = _with_prompt_override(
        '''You are a product manager building a startup-VC matching website.
        The product vision: a platform where founders find matching investors and VCs
        discover relevant startups, with fit-score calculations and personalized introductions.

        The website is built as HTML/CSS/JS pages in the workspace/ directory.
        Key pages include: landing page (index.html), founders page, investors page,
        fit-score calculator, and about/how-it-works page.

        Your approach:
        - Inspect the current workspace files to understand what exists
        - Identify the highest-priority missing or placeholder page
        - Write a clear, actionable spec for the Developer Agent to implement
        - Focus on user-facing website pages, NOT internal Python tools

        You hand off build specs to the Developer Agent via share_insight.
        '''
        + workspace_note,
        prompt_override,
    )

    tools = [
        tool_builder_tool,
        register_dynamic_tool,
        list_dynamic_tools,
        execute_dynamic_tool,
        make_share_insight("product_strategist"),
        get_team_insights,
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
        memory=True
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
    workspace_note = ""
    if extra_tools:
        workspace_note = (
            "\n\n        You also have workspace file tools that let you read and list "
            "files in a product workspace directory. Use these to inspect website "
            "files and verify correctness, structure, and quality."
        )
    backstory = _with_prompt_override(
        '''You are a strict software QA reviewer. Your responsibility is to catch
        broken code before it reaches the Strategic Coordinator.

        Your approach:
        - Run deterministic quality checks (syntax and tests)
        - Report exact failures and probable root causes
        - Require fixes from the Developer Agent before sign-off
        - Share QA status and blocking defects with the team

        You focus on correctness and release readiness, not feature ideation.
        '''
        + workspace_note,
        prompt_override,
    )

    tools = [
        run_quality_checks_tool,
        make_share_insight("reviewer"),
        get_team_insights,
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
        memory=True
    )


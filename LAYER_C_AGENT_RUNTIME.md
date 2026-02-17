# Layer C: Agent Runtime — Implementation Plan

Last updated: 2026-02-17

## Purpose

Give every agent a **common execution lifecycle** that is independent of domain logic. An agent receives a typed task, resolves what tools it needs, executes under budget and policy constraints, produces a typed result, persists outcomes to memory, and emits structured events. The runtime replaces the current pattern where CrewAI agents, tools, and memory are wired together ad-hoc in `crews.py` and `tools.py`.

## What This Layer Does NOT Do

- It does not schedule or order tasks — that is Layer D (Orchestration Kernel).
- It does not decide when to stop or loop — that is Layer E (Autonomy Controller).
- It does not define policies or budgets — that is Layer F (Safety & Governance).
- It does not evaluate outcomes — that is Layer G (Evaluation & Learning).

The runtime **consumes** policies and budgets from Layer F and **produces** results and events consumed by Layers D, G, and H. It reads and writes through the UnifiedStore (Layer B).

## 2026-02-17 Runtime Upgrades

- Added capability-level failover behavior with tool cooldown support in `capability_registry.py`.
- Added fallback execution chain in `AgentRuntime.execute_tool_call()` with structured attempt traces.
- Added repeated-identical tool-call loop detection in runtime policy flow.
- Added orchestration delegation guardrails: child-task caps, optional global cap, and duplicate-objective suppression.

---

## Prerequisite: Missing Layer A Contracts

Before implementing Layer C, these contracts must be added to `src/framework/contracts.py` and the corresponding enums to `src/framework/types.py`. The runtime cannot function without them.

### New enums needed in `types.py` — IMPLEMENTED

```python
class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class ToolCallStatus(str, Enum):
    """Outcome of a tool invocation."""
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"       # blocked by policy
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"

class ErrorCategory(str, Enum):
    """Classification of task/runtime errors."""
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    BUDGET_EXCEEDED = "budget_exceeded"
    POLICY_VIOLATION = "policy_violation"
    UNRESOLVABLE_CAPABILITY = "unresolvable_capability"
```

### New contracts needed in `contracts.py`

All inherit from `BaseMemoryEntity` so they carry `entity_id`, `run_id`, `cycle_id`, `timestamp_utc`, `version`, `status`, `metadata`.

#### RunConfig — IMPLEMENTED
Configuration for a single autonomous run. Created once, immutable during the run.

```
Fields:
  run_id: str                      # unique identifier for this run
  seed: int                        # RNG seed for determinism
  max_cycles: int                  # hard limit on BML iterations
  max_steps_per_cycle: int         # hard limit on agent steps per cycle
  budget_seconds: Optional[float]  # wall-clock time budget (None = unlimited)
  budget_tokens: Optional[int]     # LLM token budget (None = unlimited)
  domain_adapter: str              # e.g. "startup_vc"
  autonomy_level: int              # 0 = dry-run, 1 = sim-write, 2 = real
  policies: Dict[str, Any]         # tool allowlist/denylist, risk settings
  max_delegation_depth: int = 3    # prevents unbounded agent recursion
```

#### RunContext
Live mutable state threaded through the system during execution. Not persisted directly — reconstructed from checkpoint.

```
Fields:
  run_id: str
  cycle_id: int
  step_count: int                  # incremented each agent action
  budget_remaining_seconds: Optional[float]
  budget_remaining_tokens: Optional[int]
  rng: Any                         # seeded random.Random instance (not serialised)
  active_agent_id: Optional[str]   # which agent is currently executing
  store: Any                       # reference to SyncUnifiedStore (not serialised)
```

#### TaskSpec
Typed description of work to be done by an agent. Created by the orchestrator or by delegation.

```
Fields:
  task_id: str                     # unique task identifier
  objective: str                   # natural language goal
  agent_role: str                  # which agent role should handle this
  required_capabilities: List[str] # capability labels needed (e.g. "web_search", "database_read")
  constraints: Dict[str, Any]      # task-specific limits (max_retries, timeout, etc.)
  input_data: Dict[str, Any]       # structured input from previous task or context
  expected_output_schema: Optional[Dict[str, Any]]  # JSON schema for validation
  delegated_by: Optional[str]      # task_id of the parent task (if delegated)
  depends_on: List[str]            # task_ids that must complete first
  priority: int                    # 0 = highest
```

#### TaskResult — IMPLEMENTED
Typed output produced after a task completes or fails.

```
Fields:
  task_id: str                     # matches the TaskSpec
  agent_id: str                    # which agent executed this
  task_status: TaskStatus          # completed / failed / skipped
  output: Dict[str, Any]           # structured result
  output_text: str                 # natural language summary
  error: Optional[str]             # error message if failed
  error_category: Optional[ErrorCategory]  # typed error classification using ErrorCategory enum
  tool_calls: List[str]            # entity_ids of ToolCall records
  duration_seconds: float          # wall-clock time taken
  tokens_used: int                 # LLM tokens consumed
  retries: int                     # how many retries occurred
```

#### ToolCall
Record of a single tool invocation. Persisted for observability and replay.

```
Fields:
  tool_name: str                   # registered name of the tool
  capability: str                  # capability label (e.g. "database_read")
  caller_agent_id: str             # which agent invoked this
  caller_task_id: str              # which task this belongs to
  arguments: Dict[str, Any]        # arguments passed to the tool
  call_status: ToolCallStatus      # success / error / denied / timeout
  result: Any                      # return value from the tool
  error_message: Optional[str]     # if call_status != success
  duration_ms: float               # how long the call took
  policy_check_passed: bool        # whether the policy engine approved
  denied_reason: Optional[str]     # if policy denied
```

#### AgentDecision
Structured record of an agent's reasoning and delegation choices.

```
Fields:
  agent_id: str
  task_id: str
  decision_type: str               # "tool_selection", "delegation", "strategy_choice"
  reasoning: str                   # natural language reasoning trace
  chosen_action: str               # what was decided
  alternatives_considered: List[str]
  confidence: float                # 0.0 - 1.0
```

#### CycleMetrics — IMPLEMENTED (domain-agnostic)
Aggregated metrics for one complete BML cycle. Produced at end of MEASURE phase. Domain-specific fields are stored in the `domain_metrics` bag, not as top-level fields — this ensures the framework works for any domain adapter.

```
Fields:
  cycle_id: int
  task_count: int                  # total tasks in cycle
  success_count: int               # tasks completed successfully
  failure_count: int               # tasks that failed
  tokens_used: int
  duration_seconds: float
  domain_metrics: Dict[str, Any]   # e.g. {"response_rate": 0.4, "meeting_rate": 0.1}
```

#### Checkpoint
Serialisable snapshot of full run state for pause/resume.

```
Fields:
  run_id: str
  cycle_id: int
  step_count: int
  seed: int
  rng_state: Any                   # result of random.getstate()
  working_memory_path: str         # file path to working memory dump
  pending_tasks: List[str]         # task_ids not yet completed
  completed_tasks: List[str]       # task_ids done
  budget_remaining_seconds: Optional[float]
  budget_remaining_tokens: Optional[int]
  created_at: datetime
```

---

## Files to Create

```
src/framework/runtime/
├── __init__.py
├── agent_runtime.py          # core agent execution lifecycle
├── execution_context.py      # RunContext construction and management
├── capability_registry.py    # tool registration and dispatch
└── task_router.py            # resolve TaskSpec → agent + capabilities
```

---

## File 1: `capability_registry.py`

### Purpose
A registry where tools are registered by **capability label** rather than by name. When an agent needs the `"database_read"` capability, the registry resolves which concrete tool to use, supporting priority ordering and fallbacks.

### Why
Currently, tools are imported directly by name in `agents.py` (`from src.crewai_agents.tools import web_search_startups, ...`) and hardcoded onto each agent. This makes it impossible to swap implementations, add fallbacks, or enforce policies at the tool level.

### Interface

```python
class CapabilityRegistry:
    def register(
        self,
        capability: str,            # e.g. "web_search", "database_read"
        tool_name: str,              # e.g. "Search Web for Startups"
        tool_callable: Callable,     # the actual function or CrewAI Tool
        priority: int = 0,           # lower = preferred
        metadata: Dict[str, Any]     # description, required_args, etc.
    ) -> None

    def resolve(
        self,
        capability: str,
        context: Optional[RunContext] = None  # for policy filtering
    ) -> List[RegisteredTool]
        # Returns tools sorted by priority. Empty list if none registered.

    def resolve_best(
        self,
        capability: str,
        context: Optional[RunContext] = None
    ) -> Optional[RegisteredTool]
        # Returns highest-priority tool, or None.

    def list_capabilities(self) -> List[str]
        # All registered capability labels.

    def list_tools(self, capability: Optional[str] = None) -> List[RegisteredTool]
        # All tools, optionally filtered by capability.
```

### Data model

```python
class RegisteredTool(BaseModel):
    tool_name: str
    capability: str
    priority: int
    tool_callable: Any             # not serialised
    metadata: Dict[str, Any]
```

### Registration plan
All existing tools from `tools.py` get registered under these capabilities:

| Capability          | Tool(s)                                         |
|---------------------|--------------------------------------------------|
| `web_search`        | `web_search_startups`, `web_search_vcs`          |
| `web_fetch`         | `fetch_webpage`                                   |
| `database_write`    | `save_startup`, `save_vc`                         |
| `database_read`     | `get_startups_tool`, `get_vcs_tool`, `get_database_stats` |
| `outreach_send`     | `send_outreach_email`                             |
| `outreach_read`     | `get_outreach_history`, `record_outreach_response`|
| `data_validation`   | `data_validator_tool`                             |
| `content_generation`| `content_generator_tool`                          |
| `tool_specification`| `tool_builder_tool`                               |
| `analytics`         | `analytics_tool`                                  |
| `scraping`          | `scraper_tool`                                    |
| `memory_read`       | (to be added — reads from UnifiedStore)           |
| `memory_write`      | (to be added — writes to UnifiedStore)            |

---

## File 2: `execution_context.py` — IMPLEMENTED

### Purpose
Construct and manage the `RunContext` that gets threaded through agent execution. Provides helpers for budget tracking, step counting, and RNG access.

### Thread-safety note
`ExecutionContext` is NOT thread-safe. If Layer D introduces concurrent agent execution, callers must serialize access to `begin_step` / `end_step` or introduce a lock.

### Interface

```python
class ExecutionContext:
    def __init__(self, run_config: RunConfig, store: SyncUnifiedStore)

    @property
    def run_context(self) -> RunContext

    def begin_cycle(self, cycle_id: int) -> None
        # Reset per-cycle state, increment cycle counter.

    def begin_step(self, agent_id: str) -> None
        # Increment step counter, set active agent, check budget.

    def end_step(self, tokens_used: int = 0, duration_seconds: float = 0) -> None
        # Deduct from budgets.

    def check_budget(self) -> bool
        # Returns False if any budget is exhausted.

    def get_rng(self) -> random.Random
        # Return the seeded RNG instance.

    def to_checkpoint(self) -> Checkpoint
        # Serialise current state.

    @classmethod
    def from_checkpoint(cls, checkpoint: Checkpoint, store: SyncUnifiedStore) -> "ExecutionContext"
        # Restore from checkpoint.
```

### Budget tracking
- `budget_remaining_seconds`: decremented after each step by `duration_seconds`
- `budget_remaining_tokens`: decremented after each step by `tokens_used`
- `step_count`: incremented by `begin_step()`
- If any budget hits zero, `check_budget()` returns `False` and the runtime should stop

---

## File 3: `task_router.py`

### Purpose
Given a `TaskSpec`, determine which agent should execute it and which capabilities are needed. This replaces the hardcoded agent-to-tool mapping in `agents.py`.

### Interface

```python
class TaskRouter:
    def __init__(self, registry: CapabilityRegistry)

    def register_agent(
        self,
        agent_id: str,
        agent_role: str,              # e.g. "Data Strategy Expert"
        capabilities: List[str],      # capability labels this agent can use
        agent_instance: Any           # the CrewAI Agent or custom agent
    ) -> None

    def route(self, task_spec: TaskSpec) -> RoutingDecision
        # Match task_spec.agent_role and task_spec.required_capabilities
        # to a registered agent. Verify all required capabilities are available.

    def list_agents(self) -> List[RegisteredAgent]
```

### Data model

```python
class RegisteredAgent(BaseModel):
    agent_id: str
    agent_role: str
    capabilities: List[str]

class RoutingDecision(BaseModel):
    agent_id: str
    agent_role: str
    resolved_tools: List[RegisteredTool]   # from capability registry
    unresolved_capabilities: List[str]     # capabilities with no tool
    can_execute: bool                      # True only if all required capabilities are resolved
```

### Agent registration plan
Existing agents map to capabilities like this:

| Agent Role                | Capabilities                                                                |
|---------------------------|-----------------------------------------------------------------------------|
| `Strategic Coordinator`   | `memory_read`, `memory_write`, `analytics`                                  |
| `Data Strategy Expert`    | `web_search`, `web_fetch`, `database_read`, `database_write`, `data_validation`, `scraping` |
| `Product Strategy Expert` | `tool_specification`, `memory_read`                                         |
| `Outreach Strategy Expert`| `database_read`, `content_generation`, `outreach_send`, `outreach_read`, `analytics` |

---

## File 4: `agent_runtime.py`

### Purpose
The core execution engine. Takes a `TaskSpec`, runs an agent through its lifecycle, and produces a `TaskResult`. This is the single entry point for all agent work.

### Interface

```python
class AgentRuntime:
    def __init__(
        self,
        registry: CapabilityRegistry,
        router: TaskRouter,
        store: SyncUnifiedStore,
        context: ExecutionContext,
        policy_engine: Optional[Any] = None,  # Layer F, None until built
        event_emitter: Optional[Any] = None,  # Layer H, None until built
    )

    def execute_task(self, task_spec: TaskSpec) -> TaskResult:
        """Run a single task through the full agent lifecycle."""
        # 1. Route task to agent
        # 2. Resolve capabilities to tools
        # 3. Load agent context from working memory
        # 4. Execute agent (CrewAI or custom) with resolved tools
        # 5. Record tool calls
        # 6. Validate output against expected_output_schema (if provided)
        # 7. Persist episode to episodic memory
        # 8. Update working memory with result
        # 9. Emit events
        # 10. Return TaskResult

    def execute_tool_call(
        self,
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
        agent_id: str,
        task_id: str,
    ) -> ToolCall:
        """Execute a single tool call with policy checking and recording."""
        # 1. Check policy (if policy_engine available)
        # 2. Check budget
        # 3. Execute tool
        # 4. Record ToolCall
        # 5. Emit event
        # 6. Return ToolCall record
```

### Execution lifecycle (detailed)

```
execute_task(task_spec) called
│
├─ 1. ROUTE
│   ├─ router.route(task_spec) → RoutingDecision
│   ├─ If can_execute is False → return TaskResult(status=FAILED, error="unresolved capabilities")
│   └─ Get agent instance from routing decision
│
├─ 2. PREPARE CONTEXT
│   ├─ context.begin_step(agent_id)
│   ├─ Load working memory: store.wm_get_context_for_prompt(agent_id)
│   ├─ Load relevant procedure: store.proc_get(task_type) if applicable
│   ├─ Load recent episodes: store.ep_search_structured(agent_id, limit=5)
│   └─ Build augmented prompt with context + procedure + past episodes
│
├─ 3. EXECUTE
│   ├─ Pass task_spec.objective + augmented context to agent
│   ├─ Agent calls tools via execute_tool_call() (policy-checked)
│   ├─ Collect all ToolCall records
│   └─ Receive agent output
│
├─ 4. VALIDATE
│   ├─ If expected_output_schema: validate output against schema
│   └─ If validation fails: mark as FAILED or trigger repair (future)
│
├─ 5. PERSIST
│   ├─ Record Episode to episodic memory (agent_id, action, outcome, success)
│   ├─ Update working memory with result summary
│   ├─ Record AgentDecision (if reasoning trace available)
│   └─ context.end_step(tokens_used, duration)
│
├─ 6. EMIT
│   ├─ Emit task_completed or task_failed event
│   └─ Emit tool_call events for each tool invocation
│
└─ 7. RETURN TaskResult
```

### Integration with CrewAI

The runtime does NOT replace CrewAI — it wraps it. The agent execution step (step 3) calls into CrewAI's `Agent` and `Task` system, but with tools resolved through the capability registry rather than hardcoded. This means:

- `Agent` instances are still created by `create_data_strategist()` etc., but their `tools` list comes from the registry
- `Task` instances are constructed from `TaskSpec` objects
- `Crew.kickoff()` is called for the actual execution
- The runtime captures the result and wraps it in `TaskResult`

Over time, the CrewAI dependency can be reduced or replaced without changing the runtime interface.

---

## Interaction with Other Layers

```
Layer D (Orchestrator)
  │
  │ calls execute_task(task_spec)
  ▼
Layer C (Agent Runtime)
  │
  ├──reads──► Layer B (UnifiedStore)    — working memory, episodes, procedures
  ├──writes─► Layer B (UnifiedStore)    — episodes, working memory, tool calls
  ├──checks─► Layer F (Policy Engine)   — tool allowlist, action guard (optional until built)
  ├──emits──► Layer H (Event Emitter)   — structured events (optional until built)
  └──uses───► Layer A (Contracts)       — TaskSpec, TaskResult, ToolCall, etc.
```

Layer F and H are consumed via optional constructor arguments. Until those layers are built, the runtime operates without policy enforcement and without event emission. This avoids circular dependencies and allows incremental build-out.

---

## Testing Plan

Tests go in `tests/test_runtime/` or `tests/test_agent_runtime.py`.

### Unit tests

1. **CapabilityRegistry**
   - Register a tool, resolve by capability → returns correct tool
   - Register multiple tools with priority → resolve returns sorted order
   - Resolve unknown capability → returns empty list
   - List capabilities → returns all registered labels
   - List tools filtered by capability → correct subset

2. **TaskRouter**
   - Register agent, route matching task → correct agent returned
   - Route task with unresolvable capability → `can_execute=False`
   - Route task with no matching agent_role → error or fallback

3. **ExecutionContext**
   - Create from RunConfig → correct initial state
   - begin_step / end_step → step_count increments, budgets decrement
   - check_budget with exhausted budget → returns False
   - to_checkpoint / from_checkpoint → round-trip preserves state
   - RNG produces deterministic output for same seed

4. **AgentRuntime**
   - execute_task with mock agent → returns TaskResult with correct status
   - execute_task persists Episode to store → episode found in episodic memory
   - execute_task with failing tool → TaskResult has FAILED status and error
   - execute_tool_call records ToolCall → ToolCall persisted
   - execute_task with budget exceeded → returns FAILED with budget_exceeded error

### Integration tests

5. **Full lifecycle**
   - Create registry, register tools, create router, register agents
   - Create runtime with real UnifiedStore (tmp_path)
   - Execute a TaskSpec end-to-end
   - Verify: TaskResult returned, Episode in store, ToolCalls recorded, working memory updated

---

## Build Order Within Layer C

```
Step 1: Add missing contracts to contracts.py and types.py
        (RunConfig, RunContext, TaskSpec, TaskResult, ToolCall, etc.)
        + tests for serialisation

Step 2: capability_registry.py
        + tests for register/resolve/list

Step 3: execution_context.py
        + tests for budget tracking, checkpoint round-trip, deterministic RNG

Step 4: task_router.py
        + tests for agent registration and routing

Step 5: agent_runtime.py
        + unit tests with mock agent
        + integration test with real store

Step 6: Register all existing tools from tools.py into the registry
        (a setup/bootstrap function, called at startup)
```

---

## Open Questions for Founder

These should be decided before or during implementation:

1. **Should agents be able to delegate tasks to other agents through the runtime?**
   **Resolved**: Yes. `delegated_by` field exists on `TaskSpec`, and `max_delegation_depth` on `RunConfig` (default 3) prevents unbounded recursion. `AgentRuntime.execute_task()` checks depth before execution.

2. **How should CrewAI be integrated long-term?**
   Option A: CrewAI remains the agent execution engine, wrapped by the runtime.
   Option B: Replace CrewAI with direct LLM calls managed by the runtime.
   This plan assumes Option A for now. The runtime accepts any callable as an agent instance.

3. **Should tool calls require explicit policy approval from the start, or should that wait for Layer F?**
   **Resolved**: Layer F is optional — the runtime works without it but has a `policy_engine` hook ready. When present, `execute_tool_call()` checks the engine before execution.

---

## Design Corrections Applied (2026-02-16)

1. **ErrorCategory enum** added to `types.py` — enables Layer E to make structured retry/stop decisions without string parsing
2. **CycleMetrics made domain-agnostic** — replaced hardcoded startup-specific fields (response_rate, meeting_rate, etc.) with generic `task_count`/`success_count`/`failure_count` + `domain_metrics: Dict[str, Any]` bag
3. **max_delegation_depth** added to `RunConfig` (default 3) — prevents unbounded agent recursion in autonomous operation
4. **Thread-safety note** added to `ExecutionContext` docstring — flags that Layer D must serialize access if concurrent execution is introduced
5. **EvaluationResult and GateDecision** included in Layer A contracts (not deferred to Layer G) — they are pure data contracts needed across layers

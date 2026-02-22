# Remaining Framework + CrewAI Wiring Gaps

Last updated: 2026-02-22

## Context

The `framework` mode (`scripts/run_framework_simulation.py`) runs end-to-end:
`RunController` -> `AutonomyLoop` -> `Executor` -> `TaskRouter` -> CrewAI agent callables -> `StartupVCAdapter` simulation -> evaluation gates -> checkpoint.

However, several internal connections are incomplete or bypassed. This document lists every gap found in a post-integration code audit, with the concrete fix for each.

---

## Gap Summary

| # | Component | Severity | Issue |
|---|-----------|----------|-------|
| 1 | Store/Memory injection | **Critical** | `store=None` passed to RunController, AgentRuntime, ExecutionContext — disables episodes, procedures, checkpoint snapshots |
| 2 | ProcedureUpdater | **Major** | Cannot instantiate without store; adapter's `suggest_procedure_updates()` proposals never applied |
| 3 | CrewAI tool-call bridging | **Major** | Agents use CrewAI's internal tool system, never call `runtime.execute_tool_call()` — framework cannot observe, gate, or audit individual tool invocations |
| 4 | Duplicate `task_completed` events | **Minor** | Both `AgentRuntime.execute_task()` (agent_runtime.py:173) and `Executor._handle_completed()` (executor.py:198) emit `task_completed` for the same task |
| 5 | No startup-VC domain policy hook | **Minor** | `create_action_guard()` called without `domain_policy_hook`; no domain-specific tool gating |
| 6 | Checkpoint store snapshots | **Minor** | `CheckpointManager.save()` skips `.wm.json` working-memory snapshots when store is None |

Items 1, 2, and 6 are all caused by the same root issue (store not wired). Item 5 only matters after item 3 is fixed.

---

## Fix 1 — Wire the memory store through the runtime stack

**Root cause**: `_init_memory_store()` returns `sync_store`, but `create_startup_vc_run_controller()` ignores the return value and passes `store=None` to every component.

**File**: `scripts/run_framework_simulation.py`

**Changes**:

1. In `main()`, capture the store and pass it to the controller factory:
   ```python
   sync_store = _init_memory_store()
   controller, event_logger, run_id = create_startup_vc_run_controller(args, store=sync_store)
   ```

2. In `create_startup_vc_run_controller()`, accept the store parameter and inject it:
   ```python
   def create_startup_vc_run_controller(
       args: argparse.Namespace,
       store: Any = None,
   ) -> Tuple[RunController, EventLogger, str]:
   ```
   Then replace every `store=None` with `store=store`:
   - `ExecutionContext(run_config=run_config, store=store)`
   - `AgentRuntime(..., store=store, ...)`
   - `RunController(..., store=store, ...)`

**What this fixes**:
- `AgentRuntime._persist_episode()` (agent_runtime.py:453-477) writes agent episodes to episodic memory instead of returning early
- `RunController.__init__()` (run_controller.py:105-110) auto-creates `ProcedureUpdater(store)`
- `CheckpointManager.save()` (checkpointing.py:78-80) writes `.wm.json` working-memory snapshots
- `_apply_learning()` in `loop.py:399-410` calls `adapter.suggest_procedure_updates()` and applies proposals via `ProcedureUpdater`

---

## Fix 2 — Bridge CrewAI tool calls back to `runtime.execute_tool_call()`

**Root cause**: The three agent factories in `startup_vc_agents.py` ignore both the `tools` parameter and the `runtime` reference. They create a standalone CrewAI Crew and call `crew.kickoff()`. The framework never sees which tools were invoked, so:
- Tool-call events (`tool_called`, `tool_denied`, `tool_error`) are never emitted
- Policy engine cannot deny calls mid-agent-execution
- Loop detection (repeated identical calls) is bypassed
- `tool_calls` list is always empty in agent return dict
- Dashboard and diagnostics see no tool-call telemetry

**File**: `src/framework/runtime/startup_vc_agents.py`

**Approach**: Wrap each CrewAI tool so invocations route through `runtime.execute_tool_call()` before reaching the real tool function. This is a shim pattern:

```python
def _wrap_crewai_tool(runtime, tool, agent_id, task_id, collected_ids):
    """Wrap a CrewAI BaseTool so calls route through the framework runtime."""
    original_run = tool._run

    def wrapped_run(*args, **kwargs):
        call = runtime.execute_tool_call(
            tool_name=tool.name,
            capability=tool.name,
            arguments=kwargs,
            agent_id=agent_id,
            task_id=task_id,
        )
        if call.call_status != ToolCallStatus.SUCCESS:
            return f"Tool denied: {getattr(call, 'denied_reason', call.call_status)}"
        collected_ids.append(call.entity_id)
        return original_run(*args, **kwargs)

    tool._run = wrapped_run
    return tool
```

Then in each agent factory, before creating the Crew, wrap the agent's tools and collect call IDs:

```python
call_ids = []
for t in crewai_agent.tools:
    _wrap_crewai_tool(runtime, t, ROLE_DATA_SPECIALIST, task_spec.task_id, call_ids)
# ... crew.kickoff() ...
return {"output_text": output_text, "tool_calls": call_ids, "tokens_used": 0}
```

**Caveats**:
- Couples to CrewAI's `BaseTool._run` internals. If CrewAI changes the interface, this breaks. An alternative is to subclass `BaseTool` with a `FrameworkAwareTool` wrapper.
- Policy denials inside `runtime.execute_tool_call()` return a denied status — the shim must handle this gracefully (return error string to the agent, skip the real tool call).
- If the overhead is unwanted in mock mode, gate it behind a flag.

---

## Fix 3 — Deduplicate `task_completed` events

**Root cause**: `AgentRuntime.execute_task()` emits `task_completed` at agent_runtime.py:173. Then `Executor._handle_completed()` emits `task_completed` again at executor.py:198. Both fire for every successful task.

**File**: `src/framework/runtime/agent_runtime.py`

**Change**: Remove the `self._emit("task_completed", task_result)` call at line 173. The Executor is the authoritative emitter because it also handles delegation and schema validation before marking a task as truly completed. Alternatively, rename the AgentRuntime emission to `agent_task_finished` if downstream consumers need both signals.

**What this fixes**: Event counts in the dashboard and diagnostics match actual completed tasks (currently doubled).

---

## Fix 4 — Add a startup-VC domain policy hook

**Root cause**: `create_action_guard(run_config, context)` is called without `domain_policy_hook`, so no domain-specific tool restrictions apply.

**Files**: New `src/framework/safety/startup_vc_policy.py` + `scripts/run_framework_simulation.py`

**Approach**: Define a `build_startup_vc_domain_policy_hook()` that enforces startup-VC constraints:
- Limit outreach sends per cycle to `max_targets_per_cycle`
- Rate-limit external API calls (web search tools) per cycle

```python
def build_startup_vc_domain_policy_hook(
    policies: Dict[str, Any],
) -> Callable[[str, str, Dict[str, Any]], Optional[str]]:
    max_targets = int(policies.get("max_targets_per_cycle", 5))
    send_count = 0

    def hook(tool_name: str, capability: str, arguments: Dict[str, Any]) -> Optional[str]:
        nonlocal send_count
        if tool_name == "send_outreach_email":
            send_count += 1
            if send_count > max_targets:
                return f"Outreach send limit ({max_targets}) exceeded"
        return None  # allow

    return hook
```

Then wire it in `run_framework_simulation.py`:
```python
domain_policy_hook = build_startup_vc_domain_policy_hook(run_config.policies)
action_guard = create_action_guard(run_config, context, domain_policy_hook=domain_policy_hook)
```

**Priority**: Low. Only useful after Fix 2 is in place, since without tool-call bridging the policy hook is never consulted.

---

## Fix 5 — Print memory store path in output

**Root cause**: After a run, there's no indication where episodic/procedural memory lives for post-run inspection.

**File**: `scripts/run_framework_simulation.py`

**Change**: Print `data_dir` in the summary output:
```python
print(f"Memory store: {selected_dir}")
```

Trivial quality-of-life improvement.

---

## Implementation Order

| Priority | Fix | Impact | Effort |
|----------|-----|--------|--------|
| 1 | Fix 1: Store injection | Unlocks learning, episodes, checkpoint snapshots | Small (3 lines) |
| 2 | Fix 3: Event dedup | Correct event counts in dashboard/diagnostics | Tiny (1 line removal) |
| 3 | Fix 2: Tool-call bridging | Unlocks policy enforcement, full telemetry | Medium (new shim + refactor agents) |
| 4 | Fix 4: Domain policy hook | Domain-specific tool gating | Small (new file + 2 lines wiring) |
| 5 | Fix 5: Store path output | Quality-of-life | Tiny |

Fixes 1 and 3 can be done immediately with no design decisions required. Fix 2 requires choosing between monkey-patching `_run` vs subclassing `BaseTool`.

---

## Verification Checklist

After all fixes:

- [ ] `python scripts/run.py --mode framework --iterations 2` completes and prints non-zero `tool_called` event counts
- [ ] `data/memory/checkpoints_startup/` contains both `.json` and `.wm.json` files
- [ ] Event log has exactly one `task_completed` per task (not two)
- [ ] `python scripts/run.py --mode crewai --iterations 1` still works unchanged
- [ ] `pytest tests/ -v` all pass
- [ ] Episodic memory contains entries after a framework run (query via `sync_store.ep_search()`)
- [ ] Procedure updates applied: `sync_store.proc_get("startup_vc_matching")` returns a versioned procedure after a passing cycle

---

## What Already Works

These components are correctly wired and need no changes:

- **Task routing**: `TaskRouter` matches `agent_role` from `StartupVCAdapter.build_cycle_tasks()` to agents registered by `register_startup_vc_agents()` — confirmed working
- **Domain simulation**: `RunController` calls `adapter.simulate_environment()` and `adapter.compute_domain_metrics()` — confirmed working
- **Termination policy**: Auto-created from `run_config.policies`, evaluation gates trigger correct stop/pause/continue decisions — confirmed working
- **Adaptive policy controller**: Auto-created if `adaptive_policy_enabled` is true (default), adjusts autonomy level based on gate results — confirmed working
- **Diagnostics agent**: Auto-created if `diagnostics_enabled` is true (default) and `event_emitter` is provided — confirmed working
- **Dashboard compatibility**: `--mode dashboard --events-path data/memory/startup_autonomy_events.ndjson` can render events from framework runs

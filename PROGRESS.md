# Framework Progress Tracker

Last updated: 2026-02-17

## Goal

Build a fully autonomous multi-agent system that runs Build-Measure-Learn cycles without human intervention. Agents independently orchestrate, delegate, execute, evaluate, and adapt their strategies across iterations — all within enforced safety bounds. A single command launches multi-cycle runs that can be paused, resumed, replayed, and audited. The framework is domain-agnostic; the startup-VC matching use case is a domain adapter plugged into it.

## Recent Updates (2026-02-17)

- Runtime: added tool failover chains with cooldown-aware capability resolution.
- Runtime/Safety: added repeated-identical tool-call loop detection.
- Orchestration: added bounded delegation controls (per-parent fan-out caps, optional global caps, duplicate-objective suppression).
- Tests: added coverage for failover, loop guards, and delegation bounds.

## Layer Status Overview

| Layer | Name                   | Status          | Files                                      |
|-------|------------------------|-----------------|--------------------------------------------|
| A     | Contracts & Types      | **Done**        | `src/framework/contracts.py`, `types.py`, `errors.py` |
| B     | Unified Storage        | **Done**        | `src/framework/storage/`                   |
| C     | Agent Runtime          | **Done**        | `src/framework/runtime/`                   |
| D     | Orchestration Kernel   | **Done**        | `src/framework/orchestration/`             |
| E     | Autonomy Controller    | Not started     | —                                          |
| F     | Safety & Governance    | **Done**        | `src/framework/safety/`                    |
| G     | Evaluation & Learning  | Not started     | —                                          |
| H     | Observability & Replay | Not started     | —                                          |
| I     | Domain Adapter Interface | Not started   | —                                          |

---

## Layer A: Contracts & Types — Done

### What exists
Memory entity contracts are implemented and tested:
- `BaseMemoryEntity` (common fields: entity_id, run_id, cycle_id, timestamp_utc, version, status, metadata)
- `WorkingMemoryItem`
- `SemanticDocument`
- `Episode`
- `Procedure` / `ProcedureVersion`
- `ConsensusEntry`

Runtime/orchestration contracts (added 2026-02-16):
- `RunConfig` — immutable configuration for a single autonomous run (seed, max_cycles, budgets, policies, max_delegation_depth)
- `RunContext` — live mutable state (NOT a BaseMemoryEntity; uses arbitrary_types_allowed)
- `TaskSpec` — typed task description with objective, constraints, required_capabilities, delegation tracking
- `TaskResult` — typed output with task_status, error_category, tool_calls
- `ToolCall` — record of a tool invocation with policy_check_passed, denied_reason
- `AgentDecision` — structured agent decision with reasoning trace and confidence
- `CycleMetrics` — domain-agnostic metrics (task_count, success_count, domain_metrics bag)
- `EvaluationResult` — scorecard with GateDecision list, overall_status, recommended_action
- `GateDecision` — single gate verdict (pass/warn/fail, evidence, recommended_action)
- `Checkpoint` — serializable snapshot for pause/resume with RNG state

Enums in `types.py`: `MemoryType`, `ItemType`, `EpisodeType`, `EntryType`, `ConsensusStatus`, `TaskStatus`, `ToolCallStatus`, `ErrorCategory`

Error hierarchy in `errors.py`:
- `MemoryStoreError` tree (memory store operations)
- `AgentRuntimeError` tree (separate hierarchy): `BudgetExhaustedError`, `PolicyViolationError`, `CapabilityNotFoundError`, `TaskRoutingError`

**Tests**: `tests/test_contracts.py` (12 tests), `tests/test_layer_a_contracts.py` (38 tests)

---

## Layer B: Unified Storage — Done

### What exists
All five memory tiers are implemented with both new backends and legacy adapters:

**Backends** (`src/framework/storage/backends/`):
- `working_memory.py` — in-memory dict, TTL, relevance scoring, prompt packing, checkpoints
- `semantic_store.py` — ChromaDB with ONNX embeddings, vector search, collection management
- `episodic_store.py` — SQLite + ChromaDB dual-write, structured and semantic search
- `procedural_store.py` — SQLite with auto-versioning, rollback, score tracking
- `consensus_store.py` — SQLite with propose/approve workflow, supersession chains

**Legacy adapters** (`src/framework/storage/adapters/`):
- `legacy_semantic.py`, `legacy_episodic.py`, `legacy_procedural.py`

**Facade and wrapper**:
- `unified_store.py` — async UnifiedStore facade over all tiers
- `sync_wrapper.py` — SyncUnifiedStore for use in synchronous contexts (CrewAI)
- `protocol.py` — Protocol class defining the storage interface

**Tests**: 64 passing across `test_contracts.py`, `test_working_memory.py`, `test_unified_store.py`, `test_memory_integration.py`

**Full suite (Layers A+B+C+F)**: 190 tests passing

### Recent fixes applied (2026-02-15)
- Fixed `sem_get()`/`sem_delete()` to scan all persisted ChromaDB collections, not just the in-memory cache
- Fixed Pydantic V2 deprecation: replaced `json_encoders` with `@field_serializer`
- Fixed CrewAI `memory=True` causing OpenAI auth errors (disabled CrewAI built-in memory; project uses its own UnifiedStore)
- Fixed test_crewai_integration tool invocation (`.run()` instead of direct call)
- Registered `slow` pytest marker, added skip for tests requiring live API key

---

## Layer C: Agent Runtime — Done

### What exists
Files created (2026-02-16):
- `src/framework/runtime/__init__.py` — package exports
- `src/framework/runtime/capability_registry.py` — `CapabilityRegistry`, `RegisteredTool`: register tools by capability label, resolve by priority, list operations
- `src/framework/runtime/execution_context.py` — `ExecutionContext`: wraps RunContext with budget tracking, step counting, deterministic RNG, checkpoint serialisation. Thread-safety note for future Layer D.
- `src/framework/runtime/task_router.py` — `TaskRouter`, `RegisteredAgent`, `RoutingDecision`: route TaskSpec to agent by role match then capability overlap
- `src/framework/runtime/agent_runtime.py` — `AgentRuntime`: core execution engine with execute_task() and execute_tool_call() lifecycle. Handles budget exhaustion, delegation depth, episode persistence, event emission. Optional policy_engine and event_emitter hooks for Layers F and H.

Runtime lifecycle:
1. Route TaskSpec to agent via TaskRouter
2. Check delegation depth against RunConfig.max_delegation_depth
3. Begin step (budget + step limit check)
4. Execute agent callable with resolved tools
5. End step (budget accounting)
6. Persist Episode to episodic memory
7. Emit structured event
8. Return typed TaskResult

**Tests**: `tests/test_capability_registry.py` (11 tests), `tests/test_execution_context.py` (16 tests), `tests/test_task_router.py` (7 tests), `tests/test_agent_runtime.py` (19 tests)

---

## Layer D: Orchestration Kernel — Done

### What exists
Files created (2026-02-17):
- `src/framework/orchestration/__init__.py` — package exports
- `src/framework/orchestration/retry_policy.py` — `RetryPolicy`: configurable retry with exponential backoff, transient-only retry gating
- `src/framework/orchestration/task_graph.py` — `TaskNode`, `TaskGraph`: DAG with dependency edges, cycle detection (Kahn's algorithm), dangling-dep check, state machine (PENDING → READY → RUNNING → COMPLETED/FAILED/SKIPPED), dependent skipping
- `src/framework/orchestration/scheduler.py` — `Scheduler`: priority-based scheduling with deterministic RNG tie-breaking, alphabetical fallback
- `src/framework/orchestration/delegation.py` — `DelegationHandler`: delegation depth tracking, sub-task injection, JSON schema output validation (optional jsonschema dependency)
- `src/framework/orchestration/executor.py` — `Executor`, `CycleExecutionResult`: main execution loop with retry, delegation, schema validation, fail-fast with dependent skipping

Error classes added to `src/framework/errors.py`:
- `OrchestrationError(AgentRuntimeError)` — base for orchestration errors
- `CycleDetectedError(OrchestrationError)` — raised when DAG has a cycle
- `DeadlockError(OrchestrationError)` — raised when no tasks are ready but graph is incomplete

Orchestration lifecycle:
1. Build TaskGraph from TaskSpecs, validate (cycles, dangling deps)
2. Scheduler picks next task by priority with deterministic tie-breaking
3. Execute task via AgentRuntime.execute_task()
4. On transient failure: immediate retry with exponential backoff (max 2 retries)
5. On success: validate output schema, handle delegation (inject sub-tasks)
6. On permanent failure: mark failed, skip all transitive dependents
7. Return CycleExecutionResult with aggregated outcomes

**Tests**: `tests/test_orchestration/test_orchestration.py`

### Dependencies
- Requires Layer A contracts (`TaskSpec`, `TaskResult`)
- Requires Layer C runtime for task execution

---

## Layer E: Autonomy Controller — Not Started

### What needs to be built
Files to create:
- `src/framework/autonomy/run_controller.py`
- `src/framework/autonomy/loop.py`
- `src/framework/autonomy/checkpointing.py`
- `src/framework/autonomy/termination.py`

Purpose: run the system continuously with explicit loop semantics and stop conditions.

Core loop: build cycle tasks → execute → measure → evaluate gates → update procedures → decide continue/pause/stop → checkpoint.

Stop conditions: budget exhausted, max cycles reached, repeated critical failures, policy violation requiring manual review.

### Dependencies
- Requires Layer B storage (checkpointing)
- Requires Layer D orchestration (cycle execution)
- Requires Layer F safety (budget enforcement)
- Requires Layer G evaluation (gate decisions)

---

## Layer F: Safety & Governance — Done

### What exists
Files created (2026-02-16):
- `src/framework/safety/__init__.py` — package exports
- `src/framework/safety/limits.py` — `BudgetLimits`, `ToolClassification`: Pydantic data models for budget caps and per-tool risk metadata (side_effect_level 0/1/2, risk_tags)
- `src/framework/safety/policy_engine.py` — `PolicyEngine`, `PolicyResult`: rule-based tool-call gating with denylist → allowlist → autonomy level → argument validators → domain hook evaluation order. Deny-first precedence; mutable at runtime.
- `src/framework/safety/budget_manager.py` — `BudgetManager`: read-only budget query layer on top of ExecutionContext. Adds wall-clock tracking (injectable clock), utilization percentages, critical-threshold detection. Does NOT duplicate budget mutation.
- `src/framework/safety/action_guard.py` — `ActionGuard`, `create_action_guard`: composite guard that checks kill switch → budget → policy rules. Implements `check(tool_name, capability, arguments) -> bool` matching the AgentRuntime interface. Auto-kills after N consecutive policy denials (default 5). Denial log with timestamps.

Integration: `ActionGuard` is passed as `policy_engine` to `AgentRuntime.__init__()`. No runtime interface changes needed. One-line enhancement in `agent_runtime.py` propagates structured denial reason via `check_detailed` when available.

**Tests**: `tests/test_safety/test_limits.py` (4 tests), `tests/test_safety/test_policy_engine.py` (16 tests), `tests/test_safety/test_budget_manager.py` (10 tests), `tests/test_safety/test_action_guard.py` (10 tests)

### Dependencies
- Requires Layer A contracts (`RunConfig` for budget definitions)

---

## Layer G: Evaluation & Learning — Not Started

### What needs to be built
Files to create:
- `src/framework/eval/evaluator.py`
- `src/framework/eval/scorecard.py`
- `src/framework/eval/gates.py`
- `src/framework/learning/policy_updater.py`
- `src/framework/learning/procedure_updater.py`

Purpose: convert cycle outcomes into strategy updates.

Gate categories: reliability, stability, learning, safety, efficiency.

Gate output: gate_name, status (pass/warn/fail), evidence, recommended_action (continue/pause/stop/rollback).

Learning policy: updates must be versioned, include source evidence, and be reversible.

### Dependencies
- Requires Layer A contracts (`CycleMetrics`, `EvaluationResult`, `GateDecision`)
- Requires Layer B storage (procedural memory for procedure updates)

---

## Layer H: Observability & Replay — Not Started

### What needs to be built
Files to create:
- `src/framework/observability/events.py`
- `src/framework/observability/logger.py`
- `src/framework/observability/replay.py`
- `src/framework/observability/timeline.py`

Required event classes: run start/end, cycle start/end, task scheduled/started/completed/failed, tool called/result, gate decision, policy violation, checkpoint saved/restored.

Replay: given run_id and fixed seed, replay produces same decision trace. Differences surfaced by diff report.

### Dependencies
- Requires Layer A contracts (all event types)
- Requires Layer B storage (event persistence)

---

## Layer I: Domain Adapter Interface — Not Started

### What needs to be built
Files to create:
- `src/framework/adapters/base.py`
- `src/framework/adapters/startup_vc.py`

Adapter contract methods:
- `build_cycle_tasks(run_context)`
- `simulate_environment(cycle_outputs, run_context)`
- `compute_domain_metrics(simulation_outputs)`
- `suggest_procedure_updates(evaluation_result)`
- `get_domain_policies()`

Rule: core layers never import domain-specific modules directly.

### Dependencies
- Requires Layers C, D, G to be functional

---

## Recommended Build Order

The layers have dependencies on each other. The build order that respects those dependencies:

```
1. Layer A (finish contracts)  — no dependencies, everything else needs this
2. Layer F (safety)            — only needs Layer A; Layer C/D/E consume it
3. Layer C (agent runtime)     — needs A
4. Layer D (orchestration)     — needs A, C
5. Layer G (evaluation)        — needs A, B
6. Layer H (observability)     — needs A, B
7. Layer E (autonomy)          — needs B, D, F, G (the integrator)
8. Layer I (domain adapter)    — needs C, D, G
```

---

## Founder Decisions Needed Before Layer E

These decisions should be made before implementing the Autonomy Controller:

- Default autonomy level: dry-run or simulation-write?
- Hard budget limits: time, steps, tokens/cost?
- Which gate failures force auto-stop vs. warn-only?
- Learning update mode: auto-apply or review queue?
- Retention window for run artifacts?

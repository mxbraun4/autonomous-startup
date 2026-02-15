# Framework Progress Tracker

Last updated: 2026-02-15

## Goal

Build a fully autonomous multi-agent system that runs Build-Measure-Learn cycles without human intervention. Agents independently orchestrate, delegate, execute, evaluate, and adapt their strategies across iterations — all within enforced safety bounds. A single command launches multi-cycle runs that can be paused, resumed, replayed, and audited. The framework is domain-agnostic; the startup-VC matching use case is a domain adapter plugged into it.

## Layer Status Overview

| Layer | Name                   | Status          | Files                                      |
|-------|------------------------|-----------------|--------------------------------------------|
| A     | Contracts & Types      | **Partial**     | `src/framework/contracts.py`, `types.py`, `errors.py` |
| B     | Unified Storage        | **Done**        | `src/framework/storage/`                   |
| C     | Agent Runtime          | Not started     | —                                          |
| D     | Orchestration Kernel   | Not started     | —                                          |
| E     | Autonomy Controller    | Not started     | —                                          |
| F     | Safety & Governance    | Not started     | —                                          |
| G     | Evaluation & Learning  | Not started     | —                                          |
| H     | Observability & Replay | Not started     | —                                          |
| I     | Domain Adapter Interface | Not started   | —                                          |

---

## Layer A: Contracts & Types — Partial

### What exists
Memory entity contracts are implemented and tested:
- `BaseMemoryEntity` (common fields: entity_id, run_id, cycle_id, timestamp_utc, version, status, metadata)
- `WorkingMemoryItem`
- `SemanticDocument`
- `Episode`
- `Procedure` / `ProcedureVersion`
- `ConsensusEntry`

Enums in `types.py`: `MemoryType`, `ItemType`, `EpisodeType`, `EntryType`, `ConsensusStatus`

Custom exceptions in `errors.py`.

### What is missing
The plan requires these runtime/orchestration contracts that have not been created:
- `RunConfig` — configuration for a single autonomous run (seed, max_cycles, budgets, policies)
- `RunContext` — live state passed through the system during execution (current run_id, cycle_id, budget remaining, RNG)
- `TaskSpec` — typed task description with objective, constraints, expected_output_schema
- `TaskResult` — typed output of a completed task (status, output, metrics, error)
- `ToolCall` — record of a tool invocation (tool name, args, caller agent)
- `ToolResult` — record of a tool's response (output, duration, success)
- `AgentDecision` — structured agent decision with reasoning trace
- `CycleMetrics` — aggregated metrics for one BML cycle (response_rate, meeting_rate, data_collected, etc.)
- `EvaluationResult` — scorecard output with gate decisions
- `GateDecision` — single gate verdict (pass/warn/fail, evidence, recommended_action)
- `Checkpoint` — serializable snapshot of full run state for pause/resume

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

### Recent fixes applied (2026-02-15)
- Fixed `sem_get()`/`sem_delete()` to scan all persisted ChromaDB collections, not just the in-memory cache
- Fixed Pydantic V2 deprecation: replaced `json_encoders` with `@field_serializer`
- Fixed CrewAI `memory=True` causing OpenAI auth errors (disabled CrewAI built-in memory; project uses its own UnifiedStore)
- Fixed test_crewai_integration tool invocation (`.run()` instead of direct call)
- Registered `slow` pytest marker, added skip for tests requiring live API key

---

## Layer C: Agent Runtime — Not Started

### What needs to be built
Files to create:
- `src/framework/runtime/agent_runtime.py`
- `src/framework/runtime/execution_context.py`
- `src/framework/runtime/capability_registry.py`
- `src/framework/runtime/task_router.py`

Purpose: execute any agent with a common lifecycle, independent of domain.

Runtime lifecycle:
1. Load context from UnifiedStore
2. Resolve task intent and capability requirements
3. Select tools/delegates through capability registry
4. Execute tool calls under policy and budget limits
5. Produce typed `TaskResult` and emit events
6. Persist outcomes and hand off to evaluator

Capability registry:
- Register tools by capability label
- Support multiple tools per capability with priority/fallback
- Emit resolution trace for observability

### Dependencies
- Requires Layer A contracts to be completed first (`TaskSpec`, `TaskResult`, `ToolCall`, `ToolResult`, `RunContext`)

---

## Layer D: Orchestration Kernel — Not Started

### What needs to be built
Files to create:
- `src/framework/orchestration/task_graph.py`
- `src/framework/orchestration/executor.py`
- `src/framework/orchestration/scheduler.py`
- `src/framework/orchestration/delegation.py`
- `src/framework/orchestration/retry_policy.py`

Purpose: reusable execution engine supporting sequential, hierarchical, and event-driven coordination.

Key responsibilities:
- Build DAG from task specs, enforce dependency ordering
- Task state machine: pending → ready → running → completed/failed/skipped
- Retry with configurable backoff (default max 2 retries, transient errors only)
- Delegation: delegator emits `TaskSpec`, delegate result validated against schema
- Deterministic scheduling mode for reproducibility

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

## Layer F: Safety & Governance — Not Started

### What needs to be built
Files to create:
- `src/framework/safety/policy_engine.py`
- `src/framework/safety/budget_manager.py`
- `src/framework/safety/limits.py`
- `src/framework/safety/action_guard.py`

Purpose: keep autonomous behavior bounded and auditable.

Policy engine: tool allowlist/denylist, action validation per environment mode, domain risk policies via adapter hooks.

Budget manager: track wall-clock time, step count, token/cost budget. Expose remaining budget in RunContext.

Control levels: Level 0 (dry run), Level 1 (simulation write-only), Level 2 (bounded real tool calls).

Kill switches: manual, auto on critical policy violation, auto on repeated unrecoverable failures.

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

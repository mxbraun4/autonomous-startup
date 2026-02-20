# Framework Plan: Autonomous Multi-Agent Simulation System (Detailed)

Last updated: 2026-02-20

## 1) Purpose and Framing
This document is the implementation blueprint for building an autonomous multi-agent simulation framework that can run repeatedly with minimal human intervention, while remaining constrained, reproducible, and inspectable.

This is not a game plan and not only a startup-VC product plan. It is a systems plan for:
- orchestration
- memory
- evaluation
- safety
- autonomous operation
- domain plug-in support

Domain examples (like startup/VC matching) are adapters loaded into the framework, not the framework itself.

## 2) Success Definition
The framework is considered successful when all statements below are true.

- A single command can launch multi-cycle autonomous runs.
- Runs can be paused, resumed, replayed, and audited.
- The system enforces strict runtime and action guardrails.
- Results are reproducible for fixed seeds/configuration.
- The system can evaluate itself and adjust procedural strategy.
- Domain-specific logic can be swapped without changing core orchestration code.

## 3) Hard Constraints
These constraints are first-class and must be implemented before broad autonomy.

- Determinism first: fixed-seed behavior by default in simulation mode.
- Bounded autonomy: every loop has max steps, max retries, max cycle count.
- Policy-constrained execution: action/tool allowlist with deny-by-default options.
- No hidden side effects: all run-impacting writes pass through framework storage APIs.
- Structured observability: every major decision emits an event.
- Backward compatibility: existing simulation still runs during migration.

## Active Priorities (2026-02-18)
Near-term execution priorities now that framework layers are implemented:

1. Product-coupled localhost web autonomy:
   - wire `scripts/run.py --mode web` to the real local product URL, tests, and restart command
   - keep edit scopes narrow and policy-bounded
2. Runtime path clarity:
   - keep `scripts/run.py` as the main entrypoint
   - keep `scripts/run_simulation.py` as compatibility path only
3. Controlled real-LLM readiness:
   - run first `MOCK_MODE=false` cycles under strict budgets and policy limits
   - compare traces against mock-mode behavior
4. Customer simulation quality loop:
   - keep `match_score` deterministic and data-derived from founder/VC profiles
   - derive `timing_score` from product-perception/readiness signals (not external input buckets)
   - keep qualitative scoring (`explanation_quality`, `personalization_score`) optional via LLM with deterministic fallback

## 4) Current Repository Baseline
Existing useful assets already in repository.

- Orchestration prototype: `src/crewai_agents/crews.py`
- Agent wiring prototype: `src/crewai_agents/agents.py`
- Tools registry prototype: `src/crewai_agents/tools.py`
- Deterministic mock-mode LLM + local CrewAI runtime path bootstrap: `src/crewai_agents/mock_llm.py`, `src/crewai_agents/runtime_env.py`
- Episodic memory: `src/memory/episodic.py`
- Semantic memory: `src/memory/semantic.py`
- Procedural memory: `src/memory/procedural.py`
- Simulation actors: `src/simulation/startup_agent.py`, `src/simulation/vc_agent.py`
- DB persistence: `src/data/database.py`
- Entrypoints: `scripts/seed_memory.py`, `scripts/run.py` (mode-based), `scripts/run_simulation.py` (compatibility path)
- Entrypoints: `scripts/seed_memory.py`, `scripts/run_simulation.py`, `scripts/run_customer_simulation.py`, `scripts/evaluate_customer_simulation.py`

Main limitation now: measure metrics in `src/crewai_agents/crews.py` include synthetic improvement formulas. This blocks genuine autonomous evaluation.

## 5) Target Architecture (Layered)

## Layer A: Contracts and Types
Goal: eliminate ad hoc payloads and create strongly-typed system boundaries.

Required artifacts:
- `src/framework/contracts.py`
- `src/framework/types.py`
- `src/framework/errors.py`

Mandatory contract objects:
- `RunConfig`
- `RunContext`
- `TaskSpec`
- `TaskResult`
- `ToolCall`
- `ToolResult`
- `AgentDecision`
- `CycleMetrics`
- `EvaluationResult`
- `GateDecision`
- `Checkpoint`

Mandatory fields across all major entities:
- `run_id`
- `cycle_id`
- `entity_id`
- `timestamp_utc`
- `version`
- `status`
- `metadata`

Requirements:
- Every schema must be serializable to JSON.
- Every schema must carry deterministic hashable core fields.
- Every schema must validate on ingress to storage.

## Layer B: Unified Storage
Goal: one facade for all memory and operational state.

Required artifacts:
- `src/framework/storage/unified_store.py`
- `src/framework/storage/episodic_store.py`
- `src/framework/storage/semantic_store.py`
- `src/framework/storage/procedural_store.py`
- `src/framework/storage/state_store.py`
- `src/framework/storage/run_artifacts.py`

Adapter strategy:
- Wrap existing memory modules first.
- Migrate internals later without changing facade API.

UnifiedStore minimum API:
- `start_run(run_config) -> run_id`
- `end_run(run_id, final_status, summary)`
- `save_event(run_id, cycle_id, event)`
- `save_episode(run_id, cycle_id, episode)`
- `query_episodes(filters)`
- `save_semantic(documents)`
- `search_semantic(query, top_k)`
- `save_procedure(key, workflow, score, metadata)`
- `get_procedure(key)`
- `save_checkpoint(run_id, checkpoint)`
- `load_checkpoint(run_id, checkpoint_id=None)`
- `write_artifact(run_id, name, payload)`
- `read_artifact(run_id, name)`

Storage invariants:
- Writes are idempotent for duplicate event IDs.
- Checkpoints are immutable snapshots.
- Artifact reads are version-aware.

## Layer C: Agent Runtime
Goal: execute any agent with a common lifecycle independent of domain.

Required artifacts:
- `src/framework/runtime/agent_runtime.py`
- `src/framework/runtime/execution_context.py`
- `src/framework/runtime/capability_registry.py`
- `src/framework/runtime/task_router.py`

Runtime lifecycle:
1. Load context from UnifiedStore.
2. Resolve task intent and capability requirements.
3. Select tools/delegates through registry.
4. Execute tool calls under policy and budget limits.
   - block repeated identical tool-call loops via deterministic signatures
   - fail over to lower-priority tools when preferred tools error
5. Produce typed `TaskResult` and emit events.
6. Persist outcomes and hand off to evaluator.

Capability registry requirements:
- Register tool by capability label.
- Support multiple tools per capability with priority.
- Provide fallback ordering if primary tool fails.
- Support cooldown windows for failed tools.
- Emit resolution trace for observability.

## Layer D: Orchestration Kernel
Goal: reusable execution engine supporting multiple coordination modes.

Required artifacts:
- `src/framework/orchestration/task_graph.py`
- `src/framework/orchestration/executor.py`
- `src/framework/orchestration/scheduler.py`
- `src/framework/orchestration/delegation.py`
- `src/framework/orchestration/retry_policy.py`

Kernel responsibilities:
- Build DAG or queue from task specs.
- Enforce dependency ordering.
- Manage retries with backoff policies.
- Support modes:
  - sequential
  - hierarchical delegation
  - event-driven queue
- Emit deterministic schedule traces.

Retry policy rules (initial):
- Max retries per task: configurable, default 2.
- Retry only on transient error classes.
- Hard-fail on policy violations.

## Layer E: Autonomy Controller
Goal: run the system continuously with explicit loop semantics.

Required artifacts:
- `src/framework/autonomy/run_controller.py`
- `src/framework/autonomy/loop.py`
- `src/framework/autonomy/checkpointing.py`
- `src/framework/autonomy/termination.py`

Core loop:
1. Build or fetch cycle task set.
2. Execute cycle.
3. Measure cycle outcomes.
4. Evaluate against gates.
5. Update procedures/policies.
6. Decide continue/pause/stop.
7. Save checkpoint.

Stop conditions:
- Budget exhausted.
- Max cycles reached.
- Repeated critical failure threshold reached.
- Policy violation requiring manual review.

## Layer F: Safety and Governance
Goal: keep autonomous behavior bounded and auditable.

Required artifacts:
- `src/framework/safety/policy_engine.py`
- `src/framework/safety/budget_manager.py`
- `src/framework/safety/limits.py`
- `src/framework/safety/action_guard.py`

Policy engine responsibilities:
- Allowlist/denylist tools and capabilities.
- Validate action class per environment mode.
- Enforce domain-specific risk policies via adapter hooks.
- Detect and deny repeated identical tool-call loops.

Budget manager responsibilities:
- Track runtime wall-clock budget.
- Track step budget.
- Track model/token budget where applicable.
- Expose remaining budget in run context.

## Layer G: Evaluation and Learning
Goal: convert outcomes into strategy updates, not just dashboards.

Required artifacts:
- `src/framework/eval/evaluator.py`
- `src/framework/eval/scorecard.py`
- `src/framework/eval/gates.py`
- `src/framework/learning/policy_updater.py`
- `src/framework/learning/procedure_updater.py`

Evaluation flow:
- Aggregate cycle metrics.
- Compute scorecard against configured targets.
- Emit gate decisions with explicit reasons.
- Generate recommended procedural updates.
- Persist approved procedure/policy updates.

Learning policy requirements:
- Updates must be versioned.
- Updates must include source evidence.
- Updates must be reversible.

## Layer H: Observability and Replay
Goal: transparent system behavior and deterministic debugging.

Required artifacts:
- `src/framework/observability/events.py`
- `src/framework/observability/logger.py`
- `src/framework/observability/replay.py`
- `src/framework/observability/timeline.py`

Required event classes:
- run start/end
- cycle start/end
- task scheduled
- task started/completed/failed
- tool called/result
- gate decision
- policy violation
- checkpoint saved/restored

Replay requirements:
- Given run_id and fixed seed, replay emits same high-level decision trace.
- Differences are surfaced by diff report.

## Layer I: Domain Adapter Interface
Goal: isolate domain specifics so framework remains reusable.

Required artifacts:
- `src/framework/adapters/base.py`
- `src/framework/adapters/startup_vc.py`

Adapter contract methods:
- `build_cycle_tasks(run_context)`
- `simulate_environment(cycle_outputs, run_context)`
- `compute_domain_metrics(simulation_outputs)`
- `suggest_procedure_updates(evaluation_result)`
- `get_domain_policies()`

Rule:
- Core layers never import domain-specific modules directly.

## 6) Determinism Design
Determinism is required for meaningful simulation and debugging.

Implementation rules:
- All randomness comes from injected RNG object.
- Seed is stored in `RunConfig` and all checkpoints.
- Time-dependent logic uses logical cycle clocks, not system wall clock, for decisions.
- External IO/network calls are disabled in constrained mode unless explicitly mocked.

Determinism validation:
- Run same config and seed three times.
- Compare:
  - gate outcomes
  - aggregate metrics
  - key action traces
- Fail if divergence exceeds defined tolerance.

## 7) Unified Storage Deep Requirements
This section details what "unified storage" must support.

Data categories:
- Episodic:
  - action context
  - action outcome
  - success/failure labels
  - failure taxonomy
- Semantic:
  - docs
  - embeddings
  - retrieval metadata
- Procedural:
  - workflow/policy definitions
  - scores
  - provenance
- Run state:
  - active queue
  - scheduler state
  - budget state
  - checkpoints
- Artifacts:
  - reports
  - timelines
  - snapshots

Operational requirements:
- Read-your-write consistency within a single run process.
- Explicit serialization format and version tags.
- Partial failure handling with compensating writes or rollback markers.

Indexing requirements:
- Query by `run_id`, `cycle_id`, `agent_id`, `task_id`, `status`, timestamp.

Retention requirements:
- Keep recent runs fully.
- Optionally compact old detailed events into summaries.

## 8) Orchestration Semantics
The kernel needs explicit semantics to avoid hidden behavior.

Task states:
- pending
- ready
- running
- blocked
- completed
- failed
- skipped

Transition rules:
- `pending -> ready` only when dependencies satisfied.
- `running -> failed` requires typed error code.
- `failed -> ready` only through retry policy.
- `failed -> blocked` when retry exhausted and downstream cannot continue.

Delegation semantics:
- Delegator agent emits `TaskSpec` with objective + constraints.
- Delegate result is validated against `expected_output_schema`.
- Invalid outputs trigger repair path or failure.
- Delegation fan-out is bounded per parent (`max_children_per_parent`) with optional global cap.
- Duplicate delegated objectives under one parent can be suppressed.

## 9) Safety and Kill-Switch Strategy
Autonomous systems must have unambiguous safety controls.

Control levels:
- Level 0: dry run (no side effects)
- Level 1: simulation write-only
- Level 2: bounded real tool calls (optional future)

Kill switches:
- Manual kill switch command.
- Automatic kill on policy severity critical.
- Automatic kill on repeated unrecoverable failures.

Escalation handling:
- Any request outside policy scope is logged as blocked action with reason.

## 10) Evaluation Gate Framework
Gates are decisions, not dashboards.

Gate categories:
- Reliability gate:
  - run completion rate
  - unhandled exception count
- Stability gate:
  - determinism consistency
  - variance within allowed bound
- Learning gate:
  - evidence of improved procedure score
- Safety gate:
  - policy violations threshold
- Efficiency gate:
  - cycle duration and resource use

Gate output shape:
- `gate_name`
- `status` (pass, warn, fail)
- `evidence`
- `recommended_action` (continue, pause, stop, rollback)

## 11) Migration Strategy from Current Code
Perform incremental migration to prevent disruption.

Migration step 1:
- Add framework packages alongside existing modules.
- Keep existing scripts operational.

Migration step 2:
- Wrap existing memory classes under UnifiedStore adapters.

Migration step 3:
- Route existing run flow through orchestration kernel in compatibility mode.

Migration step 4:
- Replace hardcoded measure formulas with adapter-driven simulation outcomes.

Migration step 5:
- Switch scripts to use run controller entrypoint.

## 12) Phase Plan (Detailed)

## Phase 0: Contract Baseline
Duration estimate: 2-3 days

Tasks:
- Define all core schemas in `src/framework/contracts.py`.
- Add strict validation and serialization tests.
- Add mapping doc from existing payloads to contract types.

Exit criteria:
- Contract tests green.
- No breaking changes to existing scripts.

## Phase 1: Unified Storage
Duration estimate: 4-6 days

Tasks:
- Build UnifiedStore facade.
- Implement wrappers for episodic/semantic/procedural memory.
- Add run-state/checkpoint persistence.
- Add artifact writer/reader.

Exit criteria:
- One API can support full run persistence.
- Checkpoint save/load tested end-to-end.

## Phase 2: Runtime + Capability Registry
Duration estimate: 3-5 days

Tasks:
- Implement agent runtime lifecycle.
- Build capability registry and tool dispatch.
- Add execution context with budget/policy handles.

Exit criteria:
- Agent execution can run with no hardcoded tool import paths in orchestrator.

## Phase 3: Orchestration Kernel
Duration estimate: 4-6 days

Tasks:
- Implement task graph model and state machine.
- Implement executor/scheduler/retry policy.
- Add deterministic scheduling mode.

Exit criteria:
- Existing build-measure-learn flow expressed as task graph and executed.

## Phase 4: Autonomy Controller
Duration estimate: 3-5 days

Tasks:
- Implement loop controller with continue/pause/stop decisions.
- Implement checkpoint and resume.
- Add stop condition enforcement.

Exit criteria:
- Multi-cycle autonomous runs possible unattended within limits.

## Phase 5: Safety Layer
Duration estimate: 3-4 days

Tasks:
- Implement policy engine and action guard.
- Implement budget manager.
- Add safety incident logging.

Exit criteria:
- Policy violations blocked and logged with reason codes.

## Phase 6: Evaluation + Learning
Duration estimate: 4-6 days

Tasks:
- Implement scorecards and gate evaluator.
- Implement procedure updater with versioning.
- Add rollback mechanism for bad updates.

Exit criteria:
- Each cycle produces gate results and optional procedure updates.

## Phase 7: Observability + Replay
Duration estimate: 3-5 days

Tasks:
- Implement event model and timeline output.
- Implement replay runner and trace diffing.
- Implement local live dashboard UI for run-event inspection.

Exit criteria:
- One run can be replayed and compared to original.
- Operators can inspect run/cycle/task/tool events live from NDJSON logs.

## Phase 8: Adapter Isolation
Duration estimate: 2-4 days

Tasks:
- Implement adapter base protocol.
- Move startup/VC logic behind adapter interface.

Exit criteria:
- Core runtime runs with adapter injection and no domain imports.

## 13) Test Plan (Deep)
Test families required.

- Contract tests:
  - serialization and validation
  - backward-compatibility guards
- Storage tests:
  - CRUD across all memory types
  - idempotency
  - checkpoint fidelity
- Runtime tests:
  - lifecycle transitions
  - capability dispatch
- Orchestration tests:
  - DAG dependency handling
  - retry semantics
- Autonomy tests:
  - stop conditions
  - pause/resume
- Safety tests:
  - denylist enforcement
  - budget exhaustion
- Evaluation tests:
  - gate logic correctness
  - update versioning
- Replay tests:
  - deterministic trace equivalence

Suggested file set:
- `tests/test_framework_contracts.py`
- `tests/test_unified_store.py`
- `tests/test_runtime_lifecycle.py`
- `tests/test_capability_registry.py`
- `tests/test_orchestration_state_machine.py`
- `tests/test_autonomy_controller.py`
- `tests/test_safety_policy_engine.py`
- `tests/test_evaluation_gates.py`
- `tests/test_replay_determinism.py`

## 14) Operational Commands (Current)
Primary commands currently used:

- `python scripts/seed_memory.py`
- `python scripts/run.py --mode crewai --iterations 3`
- `python scripts/run.py --mode web --iterations 3 --target-url http://localhost:3000`
- `python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson`
- `pytest tests/ -v`

## 15) Immediate Work Order (Current Next Steps)
This is the current best sequence for shipping autonomous product iteration.

1. Configure `scripts/run.py --mode web` with real local product values:
   - `--target-url`
   - `--test-command`
   - `--restart-command`
2. Add project-specific edit templates for approved paths and patterns.
3. Keep policy limits strict:
   - max edits per cycle
   - tests must pass before restart
   - checkpoint each cycle
4. Run one end-to-end local web cycle and verify event trace quality.
5. After stable mock runs, test one controlled real-LLM cycle.
## 14) Operational Commands (Planned)
These should exist once framework baseline is implemented.

- `python scripts/run_autonomous.py --cycles 3 --seed 42`
- `python scripts/run_autonomous.py --resume <run_id>`
- `python scripts/replay_run.py --run-id <run_id>`
- `python scripts/evaluate_run.py --run-id <run_id>`
- `python scripts/run_customer_simulation.py`
- `python scripts/evaluate_customer_simulation.py --summary-path data/memory/customer_matrix_summary.json`

## 15) Immediate Work Order (Next Steps)
This is the best starting sequence right now.

1. Create framework folder skeleton under `src/framework/`.
2. Implement `contracts.py` and `types.py` with full schema coverage.
3. Implement `UnifiedStore` facade and adapter wrappers.
4. Add tests for contract + storage layers.
5. Implement capability registry and agent runtime baseline.
6. Implement task graph and orchestration executor compatibility mode.
7. Replace synthetic measure logic with simulation adapter outputs.
8. Add run controller and checkpoint/resume.
9. Add safety policy + budget controls.
10. Add evaluator/gates and observability/replay.

## 16) Acceptance Criteria for Starting Autonomous Simulation
Before allowing unattended runs, all items below must be true.

- Contracts are stable and tested.
- Unified storage is the only write path for run state/memory.
- Orchestration supports deterministic schedule mode.
- Safety policies and budgets are active.
- Gate-based stop decisions are active.
- Replay works for at least one full run.
- Synthetic metric growth logic has been removed from measure phase.

## 17) Founder Decisions Needed
These decisions should be made before Phase 3 to reduce rework.

- Which autonomy level is allowed by default: dry-run or simulation-write.
- What budgets are hard limits: time, steps, token/cost.
- Which gate failures force auto-stop vs warn-only.
- How aggressive learning updates should be: auto-apply vs review queue.
- What retention window is required for run artifacts.

## 18) Summary
To start this simulation correctly, do not begin with more domain features.

Start by implementing:
- strict contracts
- unified storage
- runtime and orchestration kernel
- safety limits
- evaluation gates
- replayable observability

Once those are in place, the system can be safely "let loose" within constrained autonomy.

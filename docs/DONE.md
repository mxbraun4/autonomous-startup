# Completed Milestones

Shipped features and decisions, for reference. Moved out of `next_steps.md` on 2026-02-23.

---

## Autonomy Capabilities (Shipped)

### Learning Auto-Apply
Procedures and policies update without human approval. The LEARN phase proposes patches, applies them, and emits `policy_patch_applied` / `procedure_updated` observability events.

### Gate-Driven Stop / Pause
`AutonomyLoop` terminates when evaluation gates fail. `TerminationPolicy` returns stop/pause/continue actions based on gate scores.

### Gate-Driven Rollback & Self-Healing
`RunController` self-heals: rolls back to the last checkpoint, re-runs the failed cycle, and escalates to stop after `max_self_heal_attempts` (default 2). Implemented in `src/framework/autonomy/loop.py`.

### Adaptive Policy Controller
`AdaptivePolicyController` runs at the end of each cycle. Raises `autonomy_level` after N consecutive passes, drops it on safety gate failure, tightens/widens `max_steps_per_cycle` based on efficiency and learning gates. All mutations logged as `policy.auto_adjusted` events.

### Self-Diagnosis
`DiagnosticsAgent` scans event windows for tool denials, policy violations, gate drops, and budget warnings. Emits `diagnostics.action_taken` events. Runs as a lightweight background coroutine inside the autonomy loop.

### Dynamic Tool Creation
Product-generated tool specs auto-register as runtime dynamic tools via `CapabilityRegistry.register()`. Tools are persisted to `data/generated_tools/` with retention policy.

### Agent Spawn & Self-Modify
Build phase can spawn outreach clones (governed by `max_agents_per_cycle`). Learned prompt refinements are applied from procedural memory. Prompts are versioned and rolled back if performance degrades for 2 consecutive cycles.

### Product Building (Workspace)
Website builder agent writes HTML/CSS/JS to `workspace/`. Each cycle: `WorkspaceServer` serves files, `WorkspaceHTTPChecker` validates pages/forms/navigation, HTTP scores feed customer simulation parameters, `WorkspaceVersioning` snapshots at `workspace/.versions/cycle_N/`.

### Framework + CrewAI Integration
`scripts/run_framework_simulation.py` wires `StartupVCAdapter` + CrewAI agents through `RunController`, evaluation gates, checkpointing, adaptive policy, and diagnostics. Tool calls bridged via `_bridge_crewai_tools()` shim.

### Domain Policy Hook
`build_startup_vc_domain_policy_hook()` gates outreach sends and web searches per cycle with configurable limits.

### Customer Simulation
Deterministic customer model with state machines (awareness → consideration → signup → active / churned), match scoring calibration, and product surface simulation. Documented in `CUSTOMER_SIMULATION.md`.

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-20 | Full autonomy, no human-in-the-loop | System must schedule, heal, scale, and improve itself |
| 2026-02-20 | Learning update mode: auto-apply | Already implemented; confirmed as desired behavior |
| 2026-02-23 | Framework + CrewAI integration complete | `run_framework_simulation.py` wires full stack |
| 2026-02-23 | Tool-call bridging: monkey-patch `_run` | CrewAI tool invocations routed through `runtime.execute_tool_call()` |
| 2026-02-23 | Domain policy hook for startup-VC | Gates outreach sends and web searches per cycle |
| 2026-02-23 | Gate-driven rollback: implemented | `RunController` self-heal with `max_self_heal_attempts=2` |
| 2026-02-23 | Product-building workspace shipped | Agents write real HTML/CSS/JS, HTTP checks validate, scores feed sim |

# Next Steps: Full Autonomy Roadmap

Last updated: 2026-02-23

Design principle: **zero human intervention**. The system must schedule itself, heal itself, scale itself, and improve itself. Every item in this document removes a dependency on a human operator.

---

## Autonomy Gap Assessment (Current State)

| Capability | Status | What's missing |
|---|---|---|
| Learning auto-apply | **Working** | Procedures and policies update without approval |
| Gate-driven stop/pause | **Working** | Loop terminates when gates fail |
| Gate-driven rollback | **Working** | `RunController` self-heal: rollback to checkpoint, re-run, escalate after `max_self_heal_attempts` |
| Policy auto-escalation | **Working** | `AdaptivePolicyController` adjusts autonomy level and step budgets per gate results |
| Product building | **Working** | Website builder agent writes HTML/CSS/JS to `workspace/`, HTTP checks validate each cycle, scores feed customer sim |
| Self-scheduling | **Not built** | Runs only start when a human calls `run.py` |
| Self-diagnosis | **Working** | `DiagnosticsAgent` scans event windows for tool denials, policy violations, gate drops |
| Auto-budgeting | **Partial** | `BudgetManager.is_critical()` exists but is never called pre-cycle; budgets tracked but not auto-adjusted |
| Dynamic tool creation | **Working** | Product-generated tool specs auto-register as runtime dynamic tools |
| Agent spawn / self-modify | **Working** | Build phase can spawn outreach clones and applies learned prompt refinements |
| Self-deployment | **Partial** | Dynamic tools auto-deploy to local artifacts; full production rollout pipeline pending |

Everything below is ordered to close these gaps, starting from infrastructure foundations and working up to full closed-loop autonomy.

---

## Tier 4: Infrastructure for Autonomy

These are not "nice to have" production upgrades. They are prerequisites for a system that runs itself.

### 4.1 Autonomous Run Scheduler

**Gap closed: self-scheduling.**

The system currently requires `python scripts/run.py` to be called manually. A fully autonomous system must decide when and why to run.

- Build a `RunScheduler` service (long-lived process or systemd/supervisord unit) that:
  - Runs continuously and evaluates trigger predicates on a configurable interval (default: every 30 minutes).
  - Trigger predicates: time-based (cron-like), data-based (new records ingested since last run), performance-based (metrics dropped below threshold), event-based (external webhook fires).
  - Calls `RunController.run()` or `RunController.resume()` when a trigger fires.
  - Enforces a global concurrency lock (file lock or Redis lock) so only one run executes at a time.
  - Logs every trigger evaluation and decision as an observability event.
- Add a `schedules` table or config section in `RunConfig`:
  ```
  schedules:
    - trigger: cron
      expression: "0 */6 * * *"    # every 6 hours
    - trigger: data_ingestion
      min_new_records: 10
    - trigger: metric_drop
      metric: response_rate
      threshold: 0.15
  ```
- The scheduler is the **single most important missing piece** for full autonomy.

### 4.2 Self-Healing Autonomy Loop

**Gaps closed: gate-driven rollback execution, auto-recovery.**

Currently gates can recommend "rollback" but nothing executes it. "Pause" means full stop.

- In `loop.py`, when `TerminationPolicy` returns action="rollback":
  - Automatically call `ProcedureUpdater.rollback()` and `PolicyUpdater.rollback()`.
  - Revert to the last known-good checkpoint.
  - Re-run the failed cycle with the rolled-back configuration.
  - If the re-run also fails, escalate to "stop" and emit a `run.self_heal_failed` event.
- When action="pause" (currently equivalent to stop):
  - Instead of halting, enter a cool-down period (configurable, e.g., 15 minutes).
  - After cool-down, automatically resume from the checkpoint.
  - If the same gate fails again after resume, then stop.
- Add a `max_self_heal_attempts` policy (default: 2) to bound recovery loops.
- Wire `BudgetManager.is_critical()` into the cycle pre-check: if budget is >90% consumed before a cycle starts, skip the cycle and schedule a smaller exploratory run instead.

### 4.3 Adaptive Policy Controller

**Gap closed: policy auto-escalation/tightening.**

The `PolicyEngine` has `set_autonomy_level()`, `add_to_allowlist()`, `remove_from_denylist()` but nothing calls them autonomously.

- Build an `AdaptivePolicyController` that runs at the end of each cycle:
  - Reads the latest `EvaluationResult` (gate scores).
  - If reliability gate passes for N consecutive cycles (default: 3), raise `autonomy_level` by one step.
  - If safety gate fails, immediately drop `autonomy_level` by one step and add the offending tool/action to the denylist.
  - If efficiency gate fails (cycles too slow/expensive), tighten `max_steps_per_cycle` by 10%.
  - If learning gate passes with strong improvement, widen `max_steps_per_cycle` by 10% (up to a hard cap).
- All policy mutations are logged as `policy.auto_adjusted` events with before/after values.
- Add a `policy_adjustment_bounds` config to set floor/ceiling for each adjustable parameter so the system cannot escalate or restrict itself into a degenerate state.

### 4.4 Log Monitor and Self-Diagnosis

**Gap closed: self-diagnosis.**

The observability layer records events to NDJSON but nothing reads them autonomously.

- Build a `DiagnosticsAgent` (not a CrewAI agent -- a lightweight background coroutine or thread):
  - Periodically scans the last N events (configurable window, e.g., last 100 events or last 10 minutes).
  - Detects patterns:
    - 3+ `tool_denied` events for the same tool → disable the tool, activate fallback.
    - 3+ `policy_violation` events in a window → trigger `AdaptivePolicyController` tightening immediately.
    - `budget.warning` events → reduce scope of next cycle (fewer tasks, cheaper model).
    - Monotonically decreasing gate scores across 3+ cycles → trigger strategy-shift (new procedure variant).
  - Emits `diagnostics.action_taken` events for auditability.
- This is the system's "immune system". It reacts to internal symptoms without waiting for the next evaluation gate.

### 4.5 Database Migration (PostgreSQL)

- Migrate structured data (startups, VCs, outreach, episodic memory, run state, budget ledger) from SQLite to PostgreSQL.
- Use Alembic for schema versioning. The system must be able to run its own migrations on startup (auto-migrate on version mismatch).
- Keep SQLite as the local-dev/mock-mode backend. Use the existing `UnifiedStore` facade to swap backends via config, not code changes.
- Add connection pooling (asyncpg) for concurrent agent access.
- Add autonomous vacuum/analyze scheduling so the database maintains itself.

### 4.6 Vector Database Upgrade (Qdrant)

- Replace ChromaDB with Qdrant (self-hosted) for semantic memory.
- Persistent storage with snapshots so vector data survives restarts.
- Metadata filtering for scoped queries (e.g., "find VCs matching this sector AND this stage").
- The `UnifiedStore` semantic backend already abstracts this; implement a `QdrantBackend` that satisfies the same interface.
- Add autonomous index health checks: if query latency exceeds threshold, log a warning and trigger re-indexing.

### 4.7 Redis for Shared State

- Replace Python dicts for working memory with Redis (TTL-based keys).
- Use Redis for:
  - Distributed locking (run scheduler concurrency, agent-level locks).
  - LLM response caching (hash prompt → cache response, configurable TTL).
  - Rate limiter state for external API calls.
  - Pub/sub for internal event broadcasting (diagnostics agent subscribes to events in real time instead of polling NDJSON files).

### 4.8 Durable Workflows (Temporal.io)

- Map `AutonomyLoop` to a Temporal workflow. Each Build-Measure-Learn cycle becomes a workflow step with automatic retry, timeout, and heartbeat.
- Benefits for full autonomy:
  - Survives process crashes. If the machine reboots mid-cycle, Temporal resumes from the last heartbeat.
  - Built-in scheduling (replaces the custom `RunScheduler` if preferred).
  - Visibility UI for inspecting workflow state without a custom dashboard.
- Keep the existing `RunController` as the Temporal activity implementation so the framework logic stays unchanged.

### 4.9 Containerization and Auto-Deployment

- **Dockerfile**: multi-stage build (deps → app). Include health check command.
- **Docker Compose**: full stack (app, PostgreSQL, Redis, Qdrant, Temporal).
- **Auto-restart**: configure restart policies (`restart: unless-stopped`) so crashed containers recover without human intervention.
- **CI/CD pipeline** (GitHub Actions):
  - On push to main: lint, test, build image, push to registry.
  - On tag: deploy to staging automatically.
  - Staging-to-production promotion: gate on all tests passing + last 3 runs completing successfully (use the system's own gate scores as deployment gates).
- **Health endpoints**: `/health` (is the process alive?) and `/ready` (is the system able to accept work?). Kubernetes or Docker health checks use these to auto-restart unhealthy instances.

---

## Tier 5: Autonomous Product Surface

The system should serve users and collect feedback without human mediation.

### 5.1 FastAPI Backend (Self-Serving API)

- REST API layer:
  - `GET /matches?startup_id=X` — return ranked VC matches with explanations. No human curation step.
  - `POST /matches/{id}/feedback` — users submit fit/no-fit signals. Feedback is written directly to episodic memory and influences the next BUILD cycle automatically.
  - `GET /outreach/{startup_id}/drafts` — return auto-generated outreach messages.
  - `POST /outreach/{id}/send` — trigger outreach delivery. The system handles sending, tracking opens/replies, and recording outcomes.
  - `GET /runs/latest` — current run status, metrics, gate decisions.
  - `GET /system/health` — aggregated health: DB, vector store, LLM provider, budget status.
- The API must be stateless and horizontally scalable. All state lives in PostgreSQL/Redis/Qdrant.
- Auto-generated OpenAPI docs at `/docs`.

### 5.2 Autonomous Feedback Loop (No Operator Dashboard Needed)

Instead of building a dashboard for humans to review, build a feedback loop the system consumes directly.

- **Match feedback ingestion**: when a user marks a match as good/bad via the API, the system:
  - Writes to episodic memory.
  - Updates the match scoring model's training signal.
  - If enough negative feedback accumulates (>20% bad in a window), the next BUILD cycle prioritizes scoring model improvement.
- **Outreach outcome ingestion**: email open/click/reply events from SendGrid/Mailgun webhooks are:
  - Written to episodic memory.
  - Used to compute real response_rate and meeting_rate (replacing the synthetic formulas).
  - Fed to the MEASURE phase directly.
- **Product event ingestion**: real user behavior (page views, tool usage, signups) flows in via:
  - PostHog webhook or API poll.
  - Mapped to customer simulation state transitions so the system can compare its simulation model against reality and self-calibrate.

### 5.3 Autonomous Content Publishing

The acquisition engine should publish without human editing.

- Agent generates article drafts (pillar + supporting posts) during BUILD phase.
- Content quality gate: the system self-evaluates each draft against a rubric (readability, keyword coverage, factual accuracy, CTA presence). Only drafts passing the gate are published.
- Publishing pipeline:
  - Write markdown to a designated content directory or headless CMS (e.g., Strapi, Ghost) via API.
  - Trigger static site rebuild (e.g., Next.js ISR, Hugo) automatically.
  - Verify the published page returns 200 and contains expected content.
  - If verification fails, roll back and log the failure.
- Internal linking: after publishing a new article, scan existing articles for linking opportunities and update them automatically.
- Track rankings and traffic via Search Console API. Feed metrics back to Track C evaluation.

### 5.4 Autonomous Utility Tool Deployment

- Agent generates tool specs during BUILD phase.
- Tool implementation pipeline:
  - Generate frontend code (React component or server-rendered page) from spec.
  - Run automated tests against the generated code.
  - If tests pass, deploy to the product site automatically.
  - If tests fail, log the failure, do not deploy, and create a retry task for the next cycle.
- Each tool page includes auto-generated CTAs routing to the matching product.
- Track tool usage and conversion. Feed metrics back to Track C.

### 5.5 Authentication (Machine-to-Machine First)

- JWT-based auth, but optimized for programmatic access first (API keys for integrations, webhook verification).
- User-facing auth (login/signup) only needed when the product surface goes public.
- The system itself uses service accounts for internal API calls (run scheduler → API, webhook handler → API).
- Rate limiting per key, auto-throttle on abuse detection.

---

## Tier 6: Autonomous Intelligence (The System Gets Smarter On Its Own)

### 6.1 Multi-Provider LLM Routing with Autonomous Selection

- Route tasks to different models based on task type and budget:
  - Data validation, formatting → cheapest model (GPT-4o-mini, Haiku).
  - Match reasoning, outreach personalization → strongest model (Claude Opus, GPT-4o).
  - Fallback chain: if primary provider is down/rate-limited, route to secondary automatically.
- **Autonomous model selection**: after each cycle, compare gate scores per model per task type. If a cheaper model produces equivalent quality for a task, the system switches to it permanently. If quality drops, it switches back. No human tuning needed.
- Cost tracking per model per task feeds into `BudgetManager`.

### 6.2 Parallel Agent Execution

- Identify parallelizable branches in the `TaskGraph` DAG automatically.
- Execute independent sub-tasks concurrently (data collection for multiple startups, outreach generation for multiple campaigns).
- Concurrency limits in `BudgetManager` prevent runaway parallelism.
- Use asyncio or a thread pool. If Temporal.io is integrated, use Temporal's native parallelism (child workflows).

### 6.3 Dynamic Agent Factory

**Gap closed: agent spawn.**

- Build an `AgentFactory` that the Strategic Coordinator can invoke:
  - When the system identifies a need (e.g., "outreach volume is too high for one agent"), the coordinator requests a new Outreach Specialist clone.
  - The factory creates a new CrewAI agent with the same role/tools but a fresh working memory.
  - Cloned agents are ephemeral: they exist for one cycle and are destroyed afterward (no unbounded agent growth).
  - Governed by `max_agents_per_cycle` policy (default: 6).
- Agents can also request **specialist tools**: if a task requires a capability that doesn't exist, the agent emits a `capability.request` event. The factory checks a tool template library and registers the tool dynamically via `CapabilityRegistry.register()`.

### 6.4 Self-Improving Prompts

**Gap closed: agent self-modification (at the prompt level).**

- Store all agent prompts (role, goal, backstory) in procedural memory, not in code.
- After each cycle, the LEARN phase evaluates agent performance per role:
  - Which agent contributed most to gate score improvement?
  - Which agent's outputs were lowest quality?
- For underperforming agents, generate a prompt refinement using the LLM: "Given these outcomes, rewrite the agent's backstory to produce better results."
- Version-control prompt variants alongside procedures. A/B test: cycle N uses prompt v3, cycle N+1 uses prompt v4. Auto-select winner based on gate scores.
- Rollback if a new prompt version degrades performance for 2 consecutive cycles.

### 6.5 Advanced Matching Algorithms

- **Collaborative filtering**: "startups similar to X were funded by VCs similar to Y." Build from episodic memory of past match outcomes.
- **Embedding-based similarity**: embed startup descriptions and VC theses in the same vector space via the semantic memory. Match by cosine similarity. Fine-tune embeddings based on feedback signals.
- **Temporal signals**: weight recent VC investments more heavily. Detect VCs actively deploying vs. in-between funds.
- **Negative signals**: learn from rejected matches (founder declined, VC passed). Store in episodic memory, use to penalize similar matches.
- **Graph-based matching**: model the startup-VC ecosystem as a graph (startups, VCs, sectors, stages as nodes; investments, interests, matches as edges). Use graph algorithms (PageRank, community detection) for recommendations.
- The system should **autonomously experiment** with matching algorithm variants. Run variant A for cycles 1-3, variant B for cycles 4-6, compare gate scores, adopt the winner.

### 6.6 Autonomous Anomaly Detection and Circuit Breakers

- **Anomaly detector** (runs inside the `DiagnosticsAgent` from 4.4):
  - Statistical anomaly detection on metric time series (z-score or IQR on last 10 cycle metrics).
  - Detect: sudden metric drops, output quality degradation, unusual tool-call distributions.
- **Circuit breaker pattern**:
  - If an agent fails N times in a row (default: 3), disable it for the current cycle and redistribute its tasks.
  - If a tool fails N times, disable it and activate its fallback via `CapabilityRegistry`.
  - If an LLM provider fails N times, route all traffic to the secondary provider.
  - Circuit breakers auto-reset after a cool-down period (default: 1 cycle).
- **Auto-remediation playbook**: a set of predefined corrective actions stored in procedural memory:
  - "metric_drop" → rollback last procedure update.
  - "budget_critical" → switch all tasks to cheapest model.
  - "tool_failure" → activate fallback tool.
  - "provider_down" → route to secondary LLM.
  - The system can also generate new playbook entries during the LEARN phase.

### 6.7 Multi-Domain Adapter Expansion

- The framework is domain-agnostic. New domains reuse the full stack with only a new adapter.
- Candidate adapters:
  - **Talent-Company matching** (recruiting)
  - **Startup-Accelerator matching**
  - **Co-founder matching**
  - **Partnership matching** (B2B)
- Each adapter defines: data schema, scoring function, outreach templates, evaluation metrics, simulation environment.
- The system can run multiple adapters concurrently on shared infrastructure.
- **Autonomous adapter creation**: given a domain description and sample data, the system generates an adapter skeleton. A human reviews the skeleton once; after that the system iterates autonomously.

---

## Tier 7: Scale and Self-Operation

### 7.1 Autonomous Monitoring

- Export metrics to Prometheus. Grafana dashboards auto-provision from config.
- Key metrics (all collected and acted on without human review):
  - Run completion rate, cycle duration, gate pass rate.
  - Token consumption, API cost, error rate.
  - Match quality scores (precision, recall from feedback).
  - Outreach response rate, meeting rate (from real data).
  - Memory utilization (episodic count, semantic index size, working memory hit rate).
- **Autonomous alerting**: instead of paging a human, alerts trigger the `DiagnosticsAgent`:
  - Budget alert → reduce next cycle scope.
  - Error rate spike → activate circuit breakers.
  - Metric regression → trigger strategy-shift procedure.
  - System health degradation → restart unhealthy services via container orchestration.

### 7.2 Autonomous Data Quality Pipeline

- On every data ingestion (API scrape, user submission, enrichment job):
  - Completeness check: required fields present.
  - Freshness check: data not older than threshold.
  - Deduplication: fuzzy match against existing records; merge or reject.
  - Validity: URLs resolve (async HEAD request), email format correct, sectors match taxonomy.
  - Quality score assigned per record.
- Stale records (>30 days) are automatically queued for re-enrichment in the next BUILD cycle.
- Records below quality threshold are quarantined (excluded from matching) until enriched.
- No human review of data quality. The system trusts its own quality gates.

### 7.3 Autonomous Backup and Recovery

- Automated PostgreSQL backups: daily full + hourly WAL archiving.
- Automated Qdrant snapshots: daily.
- Automated Redis RDB snapshots.
- Run checkpoint export after every successful cycle.
- **Self-recovery**: if the system detects a corrupted database (connection error, integrity check failure):
  - Attempt automatic repair (PostgreSQL: `pg_resetwal` if needed; more commonly: restore from latest backup).
  - If repair succeeds, resume from last checkpoint.
  - If repair fails, enter degraded mode (read-only, no new runs) and emit `system.recovery_failed` event.
- **LLM provider outage recovery**: if the primary provider is unreachable for >5 minutes, route all traffic to the secondary. When the primary recovers (periodic health check), gradually shift traffic back.

### 7.4 Performance Self-Optimization

- Profile cycle execution time and identify bottlenecks after each run.
- Autonomous tuning:
  - If database query time dominates, increase connection pool size.
  - If LLM call time dominates, increase parallelism or switch to a faster model for non-critical tasks.
  - If memory operations dominate, increase cache TTL.
- Batch database writes (accumulate inserts, flush every N records or every T seconds).
- Async tool execution where tools are independent.
- LLM response streaming for faster time-to-first-token in outreach generation.

### 7.5 Autonomous Compliance

- Data retention policies enforced automatically:
  - Auto-purge run artifacts older than the retention window.
  - Anonymize PII in archived episodic memory.
  - Auto-delete user data on account deletion (GDPR right to erasure) triggered by API call.
- Immutable audit log: every system action, policy change, and data access is recorded in an append-only log. The system writes to it; nothing deletes from it.
- The audit log is the system's own accountability mechanism. The `DiagnosticsAgent` can query it to verify that no anomalous actions occurred.

### 7.6 Multi-Tenant Isolation (If Needed)

- Per-tenant database schemas or row-level security.
- Per-tenant policy configurations and budget limits.
- Per-tenant `RunScheduler` instances (each tenant's system runs independently).
- Shared infrastructure with tenant-aware routing.
- Tenant onboarding is automated: API call creates schema, seeds default config, starts scheduler.

---

## Priority Matrix (Full Autonomy Focus)

| Item | Autonomy gap closed | Impact | Effort |
|------|---------------------|--------|--------|
| **4.1** Run Scheduler | Self-scheduling | Critical | Medium |
| **4.2** Self-Healing Loop | Auto-rollback, auto-resume | Critical | Medium |
| **4.3** Adaptive Policy Controller | Policy auto-escalation | Critical | Medium |
| **4.4** Log Monitor / Diagnostics Agent | Self-diagnosis | Critical | Medium |
| **4.5** PostgreSQL migration | Reliability for long-running ops | High | Medium |
| **4.7** Redis shared state | Distributed locking, caching | High | Medium |
| **4.8** Temporal.io | Crash recovery, durable scheduling | High | High |
| **4.9** Docker + CI/CD + auto-restart | Self-deployment, auto-recovery | High | Medium |
| **5.2** Autonomous feedback loop | Closed-loop learning from users | Critical | Medium |
| **5.3** Autonomous content publishing | Self-serve acquisition | High | High |
| **6.1** Multi-provider LLM routing | Self-optimizing cost/quality | High | Medium |
| **6.3** Dynamic Agent Factory | Self-scaling agents | High | High |
| **6.4** Self-improving prompts | Self-optimizing agent quality | High | Medium |
| **6.6** Anomaly detection + circuit breakers | Self-protection | High | Medium |
| **7.1** Autonomous monitoring | Self-aware operations | High | Medium |
| **7.3** Autonomous backup/recovery | Self-healing infrastructure | High | Medium |

### Recommended build order for maximum autonomy, fastest:

1. **4.1** Run Scheduler — the system can trigger itself
2. **4.2** Self-Healing Loop — the system can recover from failures
3. **4.3** Adaptive Policy Controller — the system can adjust its own constraints
4. **4.4** Diagnostics Agent — the system can read its own vital signs
5. **4.5** PostgreSQL + **4.7** Redis — reliable foundations
6. **4.9** Docker + auto-restart — survives crashes at the process level
7. **5.2** Autonomous feedback loop — learns from real users without human mediation
8. **6.1** LLM routing — optimizes its own cost/quality tradeoff
9. **6.6** Circuit breakers — self-protects against cascading failures
10. **4.8** Temporal.io — survives crashes at the workflow level
11. **6.4** Self-improving prompts — gets smarter without human prompt engineering
12. **6.3** Agent Factory — scales itself
13. Everything else in parallel as needed

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-20 | Full autonomy, no human-in-the-loop | System must schedule, heal, scale, and improve itself |
| 2026-02-20 | Learning update mode: auto-apply | Already implemented; confirmed as desired behavior |
| 2026-02-23 | Framework + CrewAI integration complete | `scripts/run.py --mode framework` wires StartupVCAdapter + CrewAI agents through RunController, evaluation gates, checkpointing, adaptive policy, diagnostics |
| 2026-02-23 | Tool-call bridging: monkey-patch `_run` | CrewAI tool invocations routed through `runtime.execute_tool_call()` via `_bridge_crewai_tools()` shim in `startup_vc_agents.py` |
| 2026-02-23 | Domain policy hook for startup-VC | `build_startup_vc_domain_policy_hook()` gates outreach sends and web searches per cycle |
| 2026-02-23 | Gate-driven rollback: implemented | `RunController` self-heal with `max_self_heal_attempts=2` (default), rollback to checkpoint, re-run |
| _pending_ | Default autonomy level for real-LLM runs | Needed before Run Scheduler goes live |
| _pending_ | Hard budget limits (tokens, cost ceiling) | Needed before Run Scheduler goes live |
| _pending_ | Run artifact retention window | Needed for Autonomous Compliance (7.5) |
| _pending_ | Policy adjustment bounds (floor/ceiling) | Bounds for Adaptive Policy Controller (4.3) |

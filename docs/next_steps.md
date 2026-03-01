# Next Steps

Last updated: 2026-02-23

---

## Current Gaps

| Capability | Status | Gap |
|---|---|---|
| Self-scheduling | Not built | Runs only start when a human calls `run.py` |
| Auto-budgeting | Partial | `BudgetManager.is_critical()` exists but is never called pre-cycle |
| Self-deployment | Partial | Dynamic tools auto-deploy locally; no production rollout pipeline |

---

## Near-Term (Build Next)

### 1. Autonomous Run Scheduler

The system currently requires a human to run `python scripts/run.py`. A self-running system must trigger its own runs.

- Long-lived `RunScheduler` process that evaluates trigger predicates on an interval (default: 30 min)
- Triggers: time-based (cron), data-based (new records since last run), performance-based (metrics below threshold)
- Calls `RunController.run()` or `.resume()` when a trigger fires
- Global concurrency lock (file lock) so only one run executes at a time
- Logs every trigger evaluation as an observability event
- **Prerequisite decisions**: default autonomy level for real-LLM runs, hard budget limits (tokens, cost ceiling)

### 2. Pre-Cycle Budget Gate

Wire `BudgetManager.is_critical()` into the cycle pre-check:
- If budget >90% consumed before a cycle starts, skip and schedule a smaller exploratory run
- Track per-model costs and auto-switch to cheaper models when budget is tight

### 3. Containerization & Auto-Restart

- Dockerfile (multi-stage build, health check)
- Docker Compose: app + PostgreSQL + Redis (minimal viable stack)
- Restart policies (`restart: unless-stopped`)
- Health endpoints: `/health`, `/ready`
- CI/CD pipeline (GitHub Actions): lint → test → build → push image

---

## Mid-Term (Infrastructure)

### 4. PostgreSQL Migration

- Migrate structured data from SQLite to PostgreSQL via Alembic
- Keep SQLite as local-dev/mock-mode backend behind `UnifiedStore` facade
- Connection pooling (asyncpg) for concurrent agent access

### 5. Redis for Shared State

- Working memory (TTL-based keys instead of Python dicts)
- Distributed locking for run scheduler concurrency
- LLM response caching (hash prompt → cache, configurable TTL)
- Rate limiter state for external API calls

### 6. FastAPI Backend

- `GET /matches?startup_id=X` — ranked VC matches with explanations
- `POST /matches/{id}/feedback` — user fit/no-fit signals → episodic memory → next BUILD cycle
- `GET /outreach/{startup_id}/drafts` — auto-generated outreach
- `POST /outreach/{id}/send` — trigger delivery, track opens/replies
- `GET /runs/latest` — current run status and metrics
- Stateless, horizontally scalable. All state in PostgreSQL/Redis.

### 7. Autonomous Feedback Loop

- Match feedback ingestion: user marks match good/bad → updates scoring signal → triggers scoring improvement if >20% negative
- Product event ingestion: real user behavior → compare against simulation model → self-calibrate

---

## Long-Term (Scale & Intelligence)

### 8. Multi-Provider LLM Routing

- Route tasks by type and budget (cheap models for formatting, strong models for reasoning)
- Fallback chain: primary provider down → secondary automatically
- After each cycle, compare gate scores per model per task type; auto-switch to cheaper model if quality is equivalent

### 9. Parallel Agent Execution

- Identify parallelizable branches in TaskGraph DAG automatically
- Execute independent sub-tasks concurrently (asyncio or thread pool)
- Concurrency limits in BudgetManager

### 10. Anomaly Detection & Circuit Breakers

- Statistical anomaly detection on metric time series (z-score on last 10 cycles)
- Circuit breaker: agent fails 3x → disable for cycle, redistribute tasks
- Tool fails 3x → disable, activate fallback via CapabilityRegistry
- LLM provider fails 3x → route to secondary
- Auto-reset after cool-down (1 cycle)

### 11. Advanced Matching Algorithms

- Collaborative filtering from episodic memory of past match outcomes
- Embedding-based similarity (startup descriptions + VC theses in same vector space)
- Temporal signals (weight recent VC investments more heavily)
- Negative signals (learn from rejected matches)
- Autonomous A/B testing of algorithm variants across cycles

### 12. Autonomous Content Publishing

- Agent generates article drafts during BUILD phase
- Self-evaluates against rubric (readability, keyword coverage, CTA presence)
- Publishes to headless CMS via API, triggers static site rebuild
- Verifies published page returns 200, rolls back on failure
- Tracks rankings via Search Console API

### 13. Durable Workflows (Temporal.io)

- Map `AutonomyLoop` to Temporal workflow — survives process crashes
- Each Build-Measure-Learn cycle = workflow step with retry, timeout, heartbeat
- Replaces custom RunScheduler if preferred

### 14. Multi-Domain Adapter Expansion

- New domains reuse the full stack with only a new adapter
- Candidates: talent-company matching, startup-accelerator matching, co-founder matching
- Each adapter defines: data schema, scoring function, outreach templates, evaluation metrics

---

## Pending Decisions

| Decision | Needed for |
|----------|-----------|
| Default autonomy level for real-LLM runs | Run Scheduler (#1) |
| Hard budget limits (tokens, cost ceiling) | Run Scheduler (#1), Budget Gate (#2) |
| Run artifact retention window | Compliance |
| Policy adjustment bounds (floor/ceiling) | Adaptive Policy Controller safety |

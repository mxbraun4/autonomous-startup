# Autonomous Startup Multi-Agent System

A multi-agent system built with **CrewAI** that autonomously runs Build-Measure-Learn cycles for a startup-VC marketplace. Agents build a real website, validate it via HTTP, and iterate based on customer simulation feedback.

- Hierarchical multi-agent coordination
- Product-building workspace (agents write HTML/CSS/JS, HTTP validation loop)
- Customer simulation with deterministic match scoring
- Framework guardrails (failover, loop detection, bounded delegation)
- Adaptive autonomy (self-heal, policy tuning, diagnostics)
- Dynamic tool lifecycle and prompt refinement
- Deterministic mock-mode execution

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/seed_memory.py
python scripts/run.py
```

Set `MOCK_MODE=true` in `.env` to run without API keys -- fully deterministic and fast.

## Run Modes

```bash
# Default CrewAI simulation
python scripts/run.py

# Custom iterations with verbosity
python scripts/run.py --mode crewai --iterations 5 --verbose 2

# Framework + workspace mode
python scripts/run_framework_simulation.py --iterations 3

# Framework mode without workspace
python scripts/run_framework_simulation.py --no-workspace

# Web-autonomy mode
python scripts/run.py --mode web --iterations 3 --target-url http://localhost:3000

# Scheduler mode (long-lived trigger loop)
python scripts/run.py --mode scheduler --cron "*/30 * * * *"

# Live dashboard (tail NDJSON events in real time)
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson

# Customer simulation
python scripts/run_customer_simulation.py

# Evaluate hypotheses
python scripts/evaluate_customer_simulation.py \
  --summary-path data/memory/customer_matrix_summary.json --allow-warn

# Tests
pytest tests/ -v
```

## Architecture

### Agent Hierarchy

```
Strategic Coordinator (manager)
    |-> Product Strategy Expert
    |-> Developer Agent
    |-> Reviewer (QA) Agent
    |-> Website Builder (workspace mode)
```

### Execution Paths

- **CrewAI simulation:** `src/crewai_agents/` + `scripts/run.py`
- **Framework simulation:** `src/framework/` + `scripts/run_framework_simulation.py`
- Both paths share the same agent definitions and customer simulation.

### Workspace Build Loop

Agents write to `workspace/` (HTML, CSS, JS files). Each cycle:

1. `WorkspaceServer` serves files on localhost.
2. `WorkspaceHTTPChecker` validates pages, forms, and navigation.
3. HTTP scores feed back into customer simulation parameters.
4. Versioning snapshots are stored at `workspace/.versions/cycle_N/`.

## Project Structure

```
autonomous-startup/
├── src/
│   ├── crewai_agents/     # Agent definitions, tools, crews
│   ├── framework/         # Runtime, orchestration, safety, storage, eval, learning
│   │   ├── adapters/      # Domain adapters (startup_vc, web_product)
│   │   ├── autonomy/      # Run controller, loop, checkpointing, scheduler
│   │   ├── eval/          # Evaluator, scorecard, gates
│   │   ├── learning/      # Procedure/policy updaters
│   │   ├── observability/ # Events, timeline, replay
│   │   ├── orchestration/ # Executor, task graph, delegation
│   │   ├── runtime/       # Agent runtime, capability registry, task router
│   │   ├── safety/        # Policy engine, budget manager, action guard
│   │   └── storage/       # Unified store, episodic/semantic/procedural backends
│   ├── simulation/        # Customer simulation, HTTP checks
│   ├── workspace/         # File tools, HTTP server, versioning
│   ├── data/              # Database layer
│   ├── memory/            # Legacy memory components
│   ├── llm/               # LLM client
│   └── utils/             # Config, logging
├── workspace/             # Agent-built marketplace website
├── scripts/               # Entrypoints (run.py, seed, dashboard, etc.)
├── tests/                 # 176+ tests
└── data/seed/             # Seed data (customers, hypotheses, templates)
```

## Configuration

Settings are managed via `.env` and `src/utils/config.py`:

```bash
# API Keys
OPENROUTER_API_KEY=your_key
ANTHROPIC_API_KEY=your_key     # optional fallback
OPENAI_API_KEY=your_key        # optional fallback

# Per-role models (OpenRouter via LiteLLM)
COORDINATOR_MODEL=openrouter/anthropic/claude-3.5-sonnet
PRODUCT_MODEL=openrouter/google/gemini-2.0-flash-001
DEVELOPER_MODEL=openrouter/openai/gpt-4o-mini
REVIEWER_MODEL=openrouter/openai/gpt-4o-mini

# Mock Mode
MOCK_MODE=true

# Logging
LOG_LEVEL=INFO

# Paths (auto-configured, override if needed)
MEMORY_DATA_DIR=data/memory
GENERATED_TOOLS_DIR=data/generated_tools
GENERATED_TOOLS_RETENTION_DAYS=30
CREWAI_LOCAL_APPDATA_DIR=data/crewai_local
CREWAI_DB_STORAGE_DIR=data/crewai_storage
```

Framework runtime policies (`RunConfig.policies`) control guardrail behavior:
`tool_loop_window`, `max_children_per_parent`, `max_self_heal_attempts`,
`adaptive_policy_enabled`, `diagnostics_enabled`, `exploratory_task_limit`, etc.

## Documentation

| File | Purpose |
|------|---------|
| `README.md` | This file |
| `AGENTS.md` | Developer/agent guide with change rules |
| `PRODUCT_VISION.md` | Product direction and acquisition strategy |
| `CUSTOMER_SIMULATION.md` | Customer simulation spec (state machines, transition logic) |
| `next_steps.md` | Full autonomy roadmap |

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=html
```

## Troubleshooting

**Seed data not loading**
```bash
python scripts/seed_memory.py
```

**Import errors**
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**Tests failing**
```bash
pip install pytest pytest-cov
```

## License

MIT License -- see LICENSE file for details.

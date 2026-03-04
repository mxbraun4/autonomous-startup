# Autonomous Startup Multi-Agent System

A multi-agent system built with **CrewAI** that autonomously runs Build-Measure-Learn cycles for a startup-VC marketplace. Agents build a real website, validate it via HTTP, and iterate based on user feedback.

- Hierarchical multi-agent coordination (coordinator dispatches to specialists)
- Product-building workspace (agents write HTML/CSS/JS + FastAPI backend, HTTP validation loop)
- Serper.dev web search for real startup/VC data collection
- Framework guardrails (failover, loop detection, bounded delegation)
- Adaptive autonomy (self-heal, policy tuning, diagnostics)
- Live observability dashboard and workspace preview
- Deterministic mock-mode execution

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/seed_memory.py
python scripts/run_simulation.py
```

Set `MOCK_MODE=true` in `.env` to run without API keys -- fully deterministic and fast.

## Run Modes

```bash
# Main simulation (Build-Measure-Learn cycles with live dashboard)
python scripts/run_simulation.py
python scripts/run_simulation.py --iterations 5 --verbose 2
python scripts/run_simulation.py --no-workspace

# Generic entrypoint (multiple modes)
python scripts/run.py
python scripts/run.py --mode crewai --iterations 5 --verbose 2
python scripts/run.py --mode web --iterations 3 --target-url http://localhost:3000
python scripts/run.py --mode scheduler --cron "*/30 * * * *"
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson
python scripts/run.py --mode preview --port 3000 --open-browser

# Framework simulation (alternative orchestration path)
python scripts/run_framework_simulation.py --iterations 3
python scripts/run_framework_simulation.py --no-workspace

# Live dashboard (standalone)
python scripts/live_dashboard.py --open-browser

# Workspace preview (standalone, auto-refreshes on file changes)
python scripts/serve_workspace.py --open-browser

# Clean all runtime data for a fresh run
python scripts/clean.py
python scripts/clean.py --yes  # skip confirmation

# Tests
pytest tests/ -v
```

## Architecture

### Agent Hierarchy

```
Strategic Coordinator (learn phase — analyzes results, extracts insights)
BUILD Coordinator (build phase — dispatches to specialists via tool calls)
    |-> Product Strategy Expert (inspects workspace, writes build specs)
    |-> Developer Agent (implements HTML/CSS/JS + Python backend)
    |-> Reviewer (QA) Agent (syntax checks, HTTP validation, PASS/FAIL)
Data Strategy Expert (data collection — web search, database population)
```

### Execution Paths

- **CrewAI simulation:** `src/crewai_agents/` + `scripts/run_simulation.py`
- **Framework simulation:** `src/framework/` + `scripts/run_framework_simulation.py`
- Both paths share the same agent definitions and workspace tools.

### Workspace Build Loop

Agents write to `workspace/` (HTML, CSS, JS, Python files). Each cycle:

1. Product strategist surveys workspace and writes a build spec.
2. Developer implements the spec as workspace files.
3. Reviewer runs QA checks (syntax, HTTP validation, content quality).
4. If QA fails, coordinator dispatches developer for fixes, then re-reviews.
5. User feedback from `workspace/feedback.db` is fed into the next iteration.
6. Versioning snapshots are stored at `workspace/.versions/cycle_N/`.

## Project Structure

```
autonomous-startup/
├── src/
│   ├── crewai_agents/     # Agent definitions, tools, crews, dispatch
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
│   ├── simulation/        # HTTP checks
│   ├── workspace_tools/   # File tools, HTTP server, versioning
│   ├── database/          # Database layer
│   ├── llm/               # LLM client
│   └── utils/             # Config, logging
├── workspace/             # Agent-built marketplace website
├── scripts/               # Entrypoints (run_simulation, clean, dashboard, etc.)
├── tests/                 # 566 tests
├── data/seed/             # Seed data (templates)
└── docs/                  # Product vision, next steps
```

## Configuration

Settings are managed via `.env` and `src/utils/config.py`:

```bash
# API Keys
OPENROUTER_API_KEY=your_key
ANTHROPIC_API_KEY=your_key     # optional fallback
OPENAI_API_KEY=your_key        # optional fallback
SERPER_API_KEY=your_key        # optional; web search degrades gracefully without it

# Per-role models (OpenRouter via LiteLLM)
COORDINATOR_MODEL=openrouter/moonshotai/kimi-k2.5
PRODUCT_MODEL=openrouter/deepseek/deepseek-v3.2
DEVELOPER_MODEL=openrouter/qwen/qwen3-coder-next
REVIEWER_MODEL=openrouter/qwen/qwen3-coder-next

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
| `docs/PRODUCT_VISION.md` | Product direction and acquisition strategy |
| `docs/next_steps.md` | Remaining work and priorities |

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

**Start fresh (wipe workspace, databases, memory)**
```bash
python scripts/clean.py --yes
```

## License

MIT License

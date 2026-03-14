# Autonomous Startup Multi-Agent System

A multi-agent system built with **CrewAI** that autonomously runs Build-Measure-Learn cycles for a startup-VC marketplace. Agents build a real **Flask + SQLite + Jinja** web application, validate it via HTTP, collect LLM-powered customer feedback, and iterate.

- Hierarchical multi-agent coordination (coordinator dispatches to specialists)
- Product-building workspace (agents write a Flask app with SQLite backend and Jinja templates)
- LLM-powered customer testing (3 personas give structured feedback each cycle)
- Consensus memory (agents share insights via a shared board)
- CrewAI native function calling with monkey-patched text-response handling
- Live observability dashboard and workspace preview
- Deterministic mock-mode execution

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/seed_memory.py
python scripts/run_simulation.py
```

Set `MOCK_MODE=true` in `.env` to run without API keys — fully deterministic and fast.

## Run Modes

```bash
# Main simulation (Build-Measure-Learn cycles with live dashboard)
python scripts/run_simulation.py
python scripts/run_simulation.py --iterations 5 --verbose 2
python scripts/run_simulation.py --no-workspace

# Generic entrypoint
python scripts/run.py
python scripts/run.py --mode crewai --iterations 5 --verbose 2
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson
python scripts/run.py --mode preview --port 3000 --open-browser

# Live dashboard (standalone)
python scripts/live_dashboard.py --open-browser

# Workspace preview (launches Flask app if app.py exists, otherwise serves static files)
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
    |-> Product Strategy Expert (inspects workspace, plans routes/features/tables)
    |-> Developer Agent (implements Flask app, Jinja templates, SQLite schemas)
    |-> Reviewer (QA) Agent (syntax checks, HTTP route validation, code review)
Data Strategy Expert (data collection — web search, database population)
```

### Tech Stack (Agent-Built Product)

Agents build a Flask web application in `workspace/`:

- **`app.py`** — Flask routes, database logic, form handling (reads `FLASK_RUN_HOST`/`FLASK_RUN_PORT` from env)
- **`templates/`** — Jinja2 HTML templates with template inheritance (`base.html`)
- **`static/`** — CSS and JS assets referenced from templates
- **`.db` files** — SQLite databases for startups, investors, users, etc.

### Build-Measure-Learn Cycle

Each iteration runs:

1. **BUILD** — Coordinator dispatches product strategist (plan), developer (implement), reviewer (QA).
2. **Quality Gate** — Syntax check, workspace content inventory, Flask route HTTP validation.
3. **Customer Testing** — 3 LLM personas (Founder, VC Partner, Journalist) review rendered pages and submit structured feedback.
4. **EVALUATE** — Evaluator scores the cycle, recommends continue/pause/rollback.
5. **LEARN** — Procedure and policy updaters extract insights for the next iteration.

### CrewAI Patches

Two monkey-patches address CrewAI 1.9.x limitations:

- **`patch_crewai.py`** — Nudges short text responses (< 200 chars) back to tool usage for up to 50% of `max_iter`, preventing agents from exiting after "thinking aloud."
- **Single tool call awareness** — All agent backstories instruct "call ONE tool at a time" since CrewAI's native handler only processes the first tool call.

## Project Structure

```
autonomous-startup/
├── src/
│   ├── crewai_agents/     # Agent definitions, tools, crews, dispatch, CrewAI patches
│   ├── framework/         # Storage, eval, learning, observability
│   │   ├── eval/          # Evaluator, scorecard, gates
│   │   ├── learning/      # Procedure/policy updaters
│   │   ├── observability/ # Event logger
│   │   └── storage/       # Unified store, episodic/semantic/procedural backends
│   ├── simulation/        # HTTP checks, customer testing (LLM personas)
│   ├── workspace_tools/   # File tools, Flask/static HTTP server, versioning
│   ├── database/          # Database layer
│   ├── llm/               # LLM client
│   └── utils/             # Config, logging
├── workspace/             # Agent-built Flask app (app.py, templates/, static/)
├── scripts/               # Entrypoints (run_simulation, clean, dashboard, etc.)
├── tests/                 # Test suite
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
COORDINATOR_MODEL=openrouter/minimax/minimax-m2.5
PRODUCT_MODEL=openrouter/minimax/minimax-m2.5
DEVELOPER_MODEL=openrouter/minimax/minimax-m2.5
REVIEWER_MODEL=openrouter/minimax/minimax-m2.5
CUSTOMER_MODEL=openrouter/minimax/minimax-m2.5

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

**Import errors**
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**Start fresh (wipe workspace, databases, memory)**
```bash
python scripts/clean.py --yes
```

## License

MIT License

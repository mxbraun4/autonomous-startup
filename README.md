# The Autonomous Startup

**Honors Seminar Thesis** by Raphael Brandmuller and Maximilian Braun

University of Regensburg, Faculty of Business, Economics and Management Information Systems
Chair of Machine Learning and Uncertainty Quantification

---

This repository contains the prototype system developed as part of the seminar thesis *The Autonomous Startup*. The thesis investigates whether autonomous AI agents can collectively perform the core functions of a startup organization, operationalized through the iterative Build-Measure-Learn (BML) cycle. The prototype implements a multi-agent system that autonomously builds, tests, and iterates on a web application over repeated cycles without human intervention.

The system is built with **CrewAI** and uses functionally specialized agents to run Build-Measure-Learn cycles for a startup-VC matching platform. Agents construct a real **Flask + SQLite + Jinja** web application, validate it via HTTP, collect LLM-powered customer feedback, and refine their approach across iterations through a multi-tier memory architecture.

## Key Capabilities

- Hierarchical multi-agent coordination (coordinator dispatches to specialists)
- Product-building workspace (agents write a Flask app with SQLite backend and Jinja templates)
- Parallel and sequential agent dispatch via native tool calls
- LLM-powered customer testing (3 personas give structured feedback each cycle)
- Multi-tier memory: episodic (ChromaDB + SQLite), procedural (versioned workflows), consensus (shared knowledge board)
- Memory compaction (era summaries, stale pruning) for long-running sessions
- Live observability dashboard and workspace preview server
- Deterministic mock-mode execution for testing without API keys

## Quick Start

```bash
pip install -r requirements.txt
python scripts/run.py
```

Set `MOCK_MODE=true` to run without API keys — fully deterministic and fast.

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
    |-> Reviewer Agent (syntax checks, HTTP route validation, code review)
```

### Build-Measure-Learn Cycle

Each iteration runs sequentially:

1. **BUILD** — Coordinator assembles context from memory and prior feedback, then dispatches product strategist (plan), developer (implement), and reviewer (validate). An idle-cycle guardrail forces a fallback dispatch if the coordinator completes without delegating any agent.
2. **MEASURE** — 3 LLM personas (Founder, VC Partner, Journalist) visit the live Flask app, interact with it, and submit structured feedback (bugs, friction, feature requests, praise) to a feedback database.
3. **LEARN** — Coordinator extracts insights, updates procedural memory with versioned workflows, persists learnings to consensus and episodic memory, and generates role-specific prompt overrides for the next iteration.

### Agent Tools

Agents interact with the system through CrewAI `@tool` decorated functions:

| Tool | Purpose |
|------|---------|
| `dispatch_task` | Coordinator dispatches a task to a specialist agent |
| `dispatch_parallel` | Dispatch 2-3 agent tasks in parallel |
| `share_insight` | Write findings to consensus memory board |
| `get_team_insights` | Read insights shared by other agents |
| `get_cycle_history` | Access episodic memory from prior cycles |
| `get_database_stats` | Query startup/VC database statistics |
| `run_quality_checks_tool` | Run Python syntax checks and optional pytest |
| `mark_feedback_addressed_tool` | Close addressed customer feedback items |
| `read_workspace_file` | Read files from the workspace |
| `write_workspace_file` | Write/create files in the workspace |
| `list_workspace_files` | List workspace directory contents |
| `run_workspace_sql` | Execute SQL against workspace SQLite databases |
| `check_workspace_http` | Start Flask/static server and validate HTTP endpoints |
| `submit_test_feedback` | Inject test feedback into the feedback database |

### Memory System

| Type | Purpose |
|------|---------|
| **Episodic** | Per-cycle action/outcome records stored in SQLite with ChromaDB embeddings for semantic search. Old episodes are summarized into era summaries. |
| **Procedural** | Versioned workflows that improve over iterations. Each Learn phase saves a new version with a performance score. |
| **Consensus** | Shared knowledge board — agents post and read insights. Entries support supersession chains linking updated entries to predecessors. |

### CrewAI Adaptations

Two runtime adaptations address CrewAI 1.9.x limitations:

- **`patch_crewai.py`** — Intercepts LiteLLM completion responses and clears the content field when tool calls are present, preventing CrewAI from mistaking a spurious content fragment for a final answer.
- **Event stack reset** — CrewAI's internal event bus leaks scope entries on exceptions; the stack is reset before each phase to prevent `StackDepthExceededError`.

## Project Structure

```
autonomous-startup/
├── src/
│   ├── crewai_agents/     # Agent definitions, tools, crews, dispatch, CrewAI patches
│   ├── framework/         # Storage, learning, observability
│   │   ├── learning/      # Procedure updater
│   │   ├── observability/ # Event logger, dashboard helpers
│   │   └── storage/       # Unified store, episodic/procedural/consensus backends
│   ├── simulation/        # HTTP checks, customer testing (LLM personas)
│   ├── workspace_tools/   # File tools, Flask/static HTTP server
│   ├── database/          # Startup/VC database layer
│   └── utils/             # Config, logging
├── workspace/             # Agent-built Flask app (app.py, templates/, static/)
├── data/                  # Runtime memory stores and event logs
├── scripts/               # Entrypoints (run_simulation, clean, dashboard, etc.)
└── tests/                 # Test suite
```

## Configuration

Settings are managed via environment variables and `src/utils/config.py`:

```bash
# API Keys
OPENROUTER_API_KEY=your_key
ANTHROPIC_API_KEY=your_key     # optional fallback
OPENAI_API_KEY=your_key        # optional fallback

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
CREWAI_LOCAL_APPDATA_DIR=data/crewai_local
CREWAI_DB_STORAGE_DIR=data/crewai_storage
```

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

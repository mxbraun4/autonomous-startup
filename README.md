# Autonomous Startup Multi-Agent System

A production-ready hierarchical multi-agent system built with **CrewAI** that autonomously executes the Build-Measure-Learn cycle for a startup-VC matching platform.

## Overview

This system demonstrates:
- **Hierarchical multi-agent coordination** (Manager -> Specialists -> Tools)
- **Build-Measure-Learn cycle** execution with learning
- **Memory systems** for context and learning
- **Simulated ecosystem** with startup and VC agents
- **Autonomous improvement** across iterations
- **Framework guardrails** for tool failover, loop detection, and bounded delegation
- **Deterministic mock-mode execution** with local-only runtime storage

## CrewAI Benefits

- Production-ready framework
- Built-in memory and delegation
- Rich tool ecosystem
- Better maintainability

## Quick Start

### Prerequisites

- Python 3.11 or higher
- pip or Poetry for package management

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd autonomous-startup

# Install dependencies
pip install -r requirements.txt

# Or using Poetry
poetry install
```

### Setup

1. Create `.env` file:
```bash
cp .env.example .env
```

2. (Optional) Add API keys to `.env`:
```bash
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
MOCK_MODE=true  # Set to false for real LLM calls
```

In `MOCK_MODE=true`, CrewAI runs with a deterministic local mock LLM and stores runtime DB files in:
- `data/crewai_local/`
- `data/crewai_storage/`

3. Seed memory systems:
```bash
python scripts/seed_memory.py
```

### Run Simulation

```bash
# Unified runner (default mode: crewai)
python scripts/run.py

# Explicit CrewAI mode
python scripts/run.py --mode crewai

# Custom iterations with verbosity
python scripts/run.py --mode crewai --iterations 5 --verbose 2

# Web-autonomy mode
python scripts/run.py --mode web --iterations 3 --target-url http://localhost:3000

# Live dashboard mode (tail NDJSON events in real time)
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson

# List available safe edit templates
python scripts/run.py --mode web --list-edit-templates

# Run web autonomy with a bounded edit template
python scripts/run.py --mode web --edit-template readme_run_command_note --edit-replace "# Unified runner (default mode: crewai and web)"

# Use project-specific template catalog (JSON)
python scripts/run.py --mode web --list-edit-templates --edit-template-file data/seed/web_edit_templates.json

# Quick integration test
python scripts/test_crewai_quick.py

# Deterministic customer simulation scenario matrix (Track D)
python scripts/run_customer_simulation.py

# Optional: include visitor cohort/acquisition signals
python scripts/run_customer_simulation.py --include-visitors

# Optional: enrich selected interaction feedback with LLM (transitions stay deterministic)
python scripts/run_customer_simulation.py --use-llm-feedback --llm-feedback-steps matched_to_interested

# Optional: apply deterministic signup-signal instrumentation from product events
python scripts/run_customer_simulation.py --product-events-path data/seed/product_events.json

# Optional: emit product-facing output only (observable behavior + failure feedback)
python scripts/run_customer_simulation.py --product-surface-only

# Evaluate Track D hypotheses against scenario summary
python scripts/evaluate_customer_simulation.py --summary-path data/memory/customer_matrix_summary.json --allow-warn
```

`--edit-template-file` defaults to `data/seed/web_edit_templates.json`.

## Architecture

### Documentation Map

Use this order to avoid duplication:

1. `README.md` - overview and navigation
2. `QUICKSTART.md` - operational commands
3. `plan.md` - architecture and roadmap source of truth
4. `PRODUCT_VISION.md` and `EXPERIMENT.md` - product and experiment source docs
5. `CUSTOMER_SIMULATION.md` - constrained simulation assumptions

### Current Execution Paths

- **CrewAI simulation path (active):** `src/crewai_agents/` + scripts in `scripts/`
- **Framework kernel path (implemented modules):** `src/framework/` runtime, orchestration, safety, storage

The CrewAI simulation remains the default runnable path. Framework modules are available and tested, and are being progressively integrated.

### Agent Hierarchy

```
Strategic Coordinator (manager)
    |
    |-> Data Strategy Expert
    |       |-> get_startups_tool
    |       |-> data_validator_tool
    |
    |-> Product Strategy Expert
    |       |-> tool_builder_tool
    |
    |-> Outreach Strategy Expert
            |-> content_generator_tool
            |-> analytics_tool
```

### Memory Systems

1. **Semantic Memory** - In-memory vector store for knowledge retrieval
   - Stores: Startup data, VC profiles, market knowledge
   - Search: Cosine similarity on embeddings

2. **Episodic Memory** - SQLite database for experiences
   - Stores: Agent actions, outcomes, success/failure
   - Enables: Learning from past experiences

3. **Procedural Memory** - JSON files for workflows
   - Stores: Successful workflows and best practices
   - Enables: Reuse of proven strategies

### Simulated External Actors

- **Startup Agents**: Respond to outreach based on personalization and VC match quality
- **VC Agents**: Evaluate startups based on sector, stage, and geography alignment

### Framework Runtime Guardrails

- **Capability failover with cooldowns**: tool calls can fall back to lower-priority tools when primary tools fail
- **Tool-call loop detection**: repeated identical tool signatures are denied by policy/runtime safeguards
- **Bounded delegation**: orchestration enforces delegation depth and child-task limits
- **Deterministic scheduling/retries**: seeded tie-breaks and transient-only retry policies

## Project Structure

```
autonomous-startup/
|-- src/
|   |-- crewai_agents/    # CrewAI implementation
|   |   |-- tools.py      # @tool decorated functions
|   |   |-- agents.py     # Agent definitions
|   |   |-- crews.py      # Crew orchestration
|   |   |-- mock_llm.py   # Deterministic local mock LLM
|   |   |-- runtime_env.py # Runtime path/telemetry bootstrap
|   |   |-- __init__.py
|   |-- framework/        # Layered framework kernel (runtime/orchestration/safety/storage)
|   |   |-- runtime/
|   |   |-- orchestration/
|   |   |-- safety/
|   |   |-- storage/
|   |-- memory/           # Memory systems
|   |   |-- semantic.py
|   |   |-- episodic.py
|   |   |-- procedural.py
|   |-- simulation/       # Simulated agents
|   |   |-- startup_agent.py
|   |   |-- vc_agent.py
|   |   |-- scenarios.py
|   |   |-- customer_environment.py
|   |   |-- customer_scenario_matrix.py
|   |   |-- customer_hypotheses.py
|   |-- llm/              # LLM client
|   |   |-- client.py
|   |   |-- prompts.py
|   |-- utils/            # Utilities
|       |-- config.py
|       |-- logging.py
|-- data/
|   |-- seed/             # Seed data
|   |   |-- startups.json
|   |   |-- vcs.json
|   |   |-- knowledge.json
|   |-- crewai_local/     # CrewAI appdata redirection (runtime generated)
|   |-- crewai_storage/   # CrewAI task output DBs (runtime generated)
|   |   |-- customers.json
|   |   |-- customer_hypotheses.json
|   |-- memory/           # Runtime data
|       |-- episodic.db
|       |-- workflows.json
|-- scripts/
|   |-- _bootstrap.py     # Shared script bootstrap helpers
|   |-- seed_memory.py    # Initialize memories
|   |-- run.py            # Unified runner (crewai/web/dashboard)
|   |-- run_simulation.py # CrewAI compatibility runner
|   |-- run_web_autonomy.py # Localhost web autonomy
|   |-- live_dashboard.py # Live observability UI
|   |-- test_crewai_quick.py # Quick test
|   |-- run_customer_simulation.py # Deterministic customer scenario runner
|   |-- evaluate_customer_simulation.py # Track D hypothesis evaluator
|-- tests/
    |-- test_crewai_integration.py
```

## Testing

Run tests:

```bash
# Run all tests
pytest tests/ -v

# Run CrewAI integration tests
pytest tests/test_crewai_integration.py -v

# Run framework runtime/orchestration/safety tests
pytest tests/test_agent_runtime.py tests/test_orchestration/test_orchestration.py tests/test_safety/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Configuration

Settings are managed via `.env` file and `src/utils/config.py`:

```python
# API Keys
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key

# Mock Mode (true = no API calls, false = real LLM)
MOCK_MODE=true

# Logging
LOG_LEVEL=INFO

# Paths (auto-configured, override if needed)
MEMORY_DATA_DIR=data/memory
MEMORY_EMBEDDING_MODEL=default
MEMORY_WM_DECAY_RATE=0.95
MEMORY_WM_DEFAULT_MAX_TOKENS=4000
CREWAI_LOCAL_APPDATA_DIR=data/crewai_local
CREWAI_DB_STORAGE_DIR=data/crewai_storage
CREWAI_STORAGE_NAMESPACE=autonomous-startup
```

Framework runtime and orchestration controls are configured through `RunConfig.policies` (not environment variables), including:
- `tool_loop_window`
- `tool_loop_max_repeats`
- `max_children_per_parent`
- `max_total_delegated_tasks`
- `dedupe_delegated_objectives`
- `loop_window_size`
- `max_identical_tool_calls`

## Runtime Expectations

Mock-mode runs are deterministic and primarily used to validate orchestration, guardrails, and end-to-end flow completion.
Treat response/meeting metrics as run outputs to inspect, not fixed targets.

## Next Steps (Production)

To evolve this prototype into production:

### Data Layer
- [ ] Replace SQLite with PostgreSQL
- [ ] Replace in-memory vectors with Qdrant/Pinecone
- [ ] Add real data scrapers (Crunchbase API, etc.)

### Infrastructure
- [ ] Add Temporal.io for durable workflows
- [ ] Implement proper caching (Redis)
- [ ] Add message queue (RabbitMQ/Kafka)

### API & UI
- [ ] Build FastAPI backend
- [x] Create local live dashboard (`scripts/live_dashboard.py`)
- [ ] Add authentication

### Deployment
- [ ] Dockerize services
- [ ] Kubernetes deployment
- [ ] CI/CD pipeline
- [ ] Monitoring and observability

### Advanced Features
- [ ] Real tool building and execution
- [ ] Multi-provider LLM fallback
- [ ] Advanced VC matching algorithms
- [ ] Email integration for outreach

## Architecture Decisions

| Component | Prototype | Production |
|-----------|-----------|------------|
| Vector DB | In-memory dict | Qdrant/Pinecone |
| Structured DB | SQLite | PostgreSQL |
| Cache/Queue | Python dict | Redis |
| LLM | Mock + Haiku | Multi-provider |
| Orchestration | CrewAI | CrewAI + Temporal.io |
| Deployment | Local | Kubernetes |

## Troubleshooting

### Seed data not loading
```bash
# Ensure you're in project root
python scripts/seed_memory.py
```

### Import errors
```bash
# Check Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Tests failing
```bash
# Install test dependencies
pip install pytest pytest-cov
```

## License

MIT License - See LICENSE file for details

## Acknowledgments

- Built using CrewAI for agent orchestration
- Claude (Anthropic) and GPT (OpenAI) for LLM capabilities
- Inspired by Build-Measure-Learn methodology

---

**Note**: This is a simulation-based prototype designed to demonstrate multi-agent coordination patterns. It uses mock data and simulated behaviors. For production use, replace simulated components with real implementations.

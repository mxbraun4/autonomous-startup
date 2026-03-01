# Agent Guide

## Mission
Build and maintain a CrewAI-based autonomous startup simulation for a startup-VC matching platform.

The system must:
- stay runnable in constrained mock-mode environments
- preserve the Build-Measure-Learn loop
- improve matching and outreach over iterations
- support acquisition via SEO content and on-page startup/VC tools
- include constrained customer simulation for pre-production validation

## Source of Truth Docs
- `README.md`: setup and operational commands
- `PRODUCT_VISION.md`: product direction, value proposition, acquisition layer
- `CUSTOMER_SIMULATION.md`: constrained customer model, state machines, parameters
- `next_steps.md`: current priorities and open work items

## Workstream Priorities
1. Matching quality and explainability
2. Outreach quality and conversion outcomes
3. Acquisition layer (articles + utility tools) with clear funnel mapping
4. Constrained customer simulation and reproducibility
5. Reliability and maintainability of orchestration/tools/data layers

## Environment
- Python 3.11+
- Run commands from repository root (`autonomous-startup/`)
- Install dependencies with `pip install -r requirements.txt` or `poetry install`
- Create `.env` from `.env.example`
- Default to `MOCK_MODE=true` unless a task explicitly requires real model calls

## Core Commands
- Initialize memory and DB:
  - `python scripts/seed_memory.py`
- Quick integration check:
  - `python scripts/test_crewai_quick.py`
- Run simulation (CrewAI mode):
  - `python scripts/run.py --mode crewai --iterations 3 --verbose 2`
- Run simulation (framework + workspace mode):
  - `python scripts/run_framework_simulation.py --iterations 3`
- Run tests:
  - `pytest tests/ -v`
- Targeted integration test:
  - `pytest tests/test_crewai_integration.py -v`
- Optional formatting/linting:
  - `black src tests scripts`
  - `ruff check src tests scripts`

## Project Map
- `src/crewai_agents/agents.py`: agent roles, LLM selection, tool wiring
- `src/crewai_agents/tools.py`: CrewAI `@tool` functions and JSON tool outputs
- `src/crewai_agents/crews.py`: task creation and Build-Measure-Learn orchestration
- `src/data/database.py`: SQLite persistence for startups, VCs, and outreach
- `src/memory/`: semantic/episodic/procedural memory components
- `src/simulation/`: simulated startup and VC behavior, predefined scenarios
- `src/simulation/http_checks.py`: HTTP validation checks
- `src/workspace/file_tools.py`: sandboxed file tools for workspace
- `src/workspace/server.py`: workspace HTTP server
- `src/workspace/versioning.py`: workspace snapshots
- `src/framework/adapters/startup_vc.py`: domain adapter with workspace mode
- `src/framework/runtime/startup_vc_agents.py`: CrewAI-backed agent wrappers
- `src/utils/config.py`: environment-backed settings and file paths
- `scripts/`: entrypoints for seeding, simulation runs, and quick validation
- `scripts/run_framework_simulation.py`: framework + workspace simulation runner

## Change Rules
- Keep tool contracts stable:
  - Preserve `@tool` decorators
  - Return JSON-serializable string responses from tools
- Keep orchestration contract stable:
  - `run_build_measure_learn_cycle()` must return keys `iterations` and `metrics_evolution`
- Preserve constrained customer simulation assumptions from `CUSTOMER_SIMULATION.md`:
  - no external network dependency for customer behavior decisions
  - deterministic/reproducible behavior for fixed inputs
  - bounded state transitions
- Route new configuration through `src/utils/config.py` instead of hardcoding
- Use `StartupDatabase` for DB interactions; avoid ad hoc SQL outside `src/data/database.py`
- If adding a new tool, wire it through the correct agent in `src/crewai_agents/agents.py`
- When adding workspace file tools, wire them through `src/workspace/file_tools.py`
- When modifying workspace pages, ensure HTTP checks still pass
- Keep scripts runnable from repo root and avoid breaking current CLI flags
- For acquisition features, maintain funnel continuity:
  - `Article -> Tool -> Signup -> Match -> Outreach`
  - every content/tool artifact should point to a core product action

## Data and Side Effects
- Runtime memory artifacts are under `data/memory/`
- Collected startup/VC data is stored in `data/collected/startups.db`
- `scripts/seed_memory.py` clears and reseeds memory systems; do not run casually during debugging if data retention matters
- If customer cohorts are introduced, keep them in deterministic seed data files under `data/seed/`

## Testing Expectations Before Handoff
- Run at least one relevant test path for changed modules
- For tool/agent/crew changes, run:
  - `python scripts/test_crewai_quick.py`
  - `pytest tests/test_crewai_integration.py -v`
- For end-to-end behavior changes, run one simulation iteration and confirm output completes:
  - `python scripts/run.py --mode crewai --iterations 1 --verbose 1`
- For customer simulation changes, verify reproducibility with fixed parameters/seed and report conversion deltas

## Safety
- Never commit secrets (`.env` is ignored)
- Prefer mock mode for routine development and CI stability
- If enabling real API calls (`MOCK_MODE=false`), require valid API keys in `.env`
- Avoid introducing live-network dependencies for constrained simulation paths

## Docs Sync
If you change commands, flags, architecture, or product assumptions, update:
- `README.md`
- `PRODUCT_VISION.md`
- `CUSTOMER_SIMULATION.md`
- `next_steps.md`

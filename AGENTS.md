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
- `PRODUCT_VISION.md`: product direction, value proposition, acquisition layer
- `EXPERIMENT.md`: hypotheses, tracks, success criteria, decision gates
- `CUSTOMER_SIMULATION.md`: constrained customer model, state machines, parameters
- `plan.md`: implementation roadmap, milestones, and execution order
- `README.md` and `QUICKSTART.md`: setup and operational commands

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
- Run simulation:
  - `python scripts/run.py --mode crewai --iterations 3 --verbose 2`
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
- `src/utils/config.py`: environment-backed settings and file paths
- `scripts/`: entrypoints for seeding, simulation runs, and quick validation

## Change Rules
- Keep tool contracts stable:
  - Preserve `@tool` decorators
  - Return JSON-serializable string responses from tools
- Keep orchestration contract stable:
  - `run_build_measure_learn_cycle()` must return keys `iterations` and `metrics_evolution`
- Align implementation work to one or more experiment tracks in `EXPERIMENT.md` (A-D)
- Preserve constrained customer simulation assumptions from `CUSTOMER_SIMULATION.md`:
  - no external network dependency for customer behavior decisions
  - deterministic/reproducible behavior for fixed inputs
  - bounded state transitions
- Route new configuration through `src/utils/config.py` instead of hardcoding
- Use `StartupDatabase` for DB interactions; avoid ad hoc SQL outside `src/data/database.py`
- If adding a new tool, wire it through the correct agent in `src/crewai_agents/agents.py`
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
- For experiment-sensitive changes, verify outputs map to `EXPERIMENT.md` success criteria and note which track(s) were affected
- For customer simulation changes, verify reproducibility with fixed parameters/seed and report conversion deltas

## Safety
- Never commit secrets (`.env` is ignored)
- Prefer mock mode for routine development and CI stability
- If enabling real API calls (`MOCK_MODE=false`), require valid API keys in `.env`
- Avoid introducing live-network dependencies for constrained simulation paths

## Docs Sync
If you change commands, flags, architecture, product assumptions, or experiment logic, update:
- `README.md`
- `QUICKSTART.md`
- `PRODUCT_VISION.md`
- `EXPERIMENT.md`
- `CUSTOMER_SIMULATION.md`
- `plan.md`

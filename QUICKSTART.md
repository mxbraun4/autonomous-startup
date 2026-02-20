# Quick Start Guide

Get the autonomous startup simulation running in 5 minutes!

## Step 1: Install Dependencies

```bash
cd autonomous-startup
pip install -r requirements.txt
```

Expected output:
```
Successfully installed crewai crewai-tools anthropic openai pydantic...
```

## Step 2: Create Environment File

```bash
# Copy example env file
cp .env.example .env
```

The default `.env` has `MOCK_MODE=true`, which means:
- No API keys needed
- No API costs
- Fast execution
- Deterministic results
- Deterministic local mock LLM (no external model calls)
- Workspace-local CrewAI runtime storage (`data/crewai_local/`, `data/crewai_storage/`)

## Step 3: Seed Memory Systems

```bash
python scripts/seed_memory.py
```

Expected output:
```
INFO - Seeding semantic memory...
INFO - Added 10 knowledge documents
INFO - Added 10 startups
INFO - Added 10 VCs
INFO - Total semantic memory size: 30 documents

=== Memory Systems Summary ===
Semantic Memory: 30 documents
Episodic Memory: 3 episodes
Procedural Memory: 2 workflows

Ready to run simulation!
```

## Step 4: Run Your First Simulation

```bash
python scripts/run.py
```

This runs 3 Build-Measure-Learn iterations and shows:
- Agent coordination
- Memory evolution
- Performance improvement
- Dynamic tool auto-registration/deployment artifacts under `data/generated_tools/`

### With Options

```bash
# Custom iterations with verbosity
python scripts/run.py --mode crewai --iterations 5 --verbose 2

# Web-autonomy mode
python scripts/run.py --mode web --iterations 3 --target-url http://localhost:3000

# Scheduler mode (single evaluation/dispatch pass)
python scripts/run.py --mode scheduler --once --cron "* * * * *"

# Scheduler mode from JSON schedule config file
python scripts/run.py --mode scheduler --once --schedules-file data/seed/scheduler_schedules.json

# Live dashboard mode
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson

# List available safe edit templates
python scripts/run.py --mode web --list-edit-templates

# Run with one bounded edit template
python scripts/run.py --mode web --edit-template readme_run_command_note --edit-replace "# Unified runner (default mode: crewai and web)"

# Web autonomy with self-heal/adaptive/diagnostics controls
python scripts/run.py --mode web --max-self-heal-attempts 2 --auto-resume-on-pause --pause-cooldown-seconds 15 --adaptive-policy-reliability-streak 3 --diagnostics-window-size 100

# Load project-specific templates from JSON
python scripts/run.py --mode web --list-edit-templates --edit-template-file data/seed/web_edit_templates.json

# Quick integration test
python scripts/test_crewai_quick.py

# Deterministic customer simulation scenario matrix
python scripts/run_customer_simulation.py

# Optional: include visitor cohort/acquisition signals
python scripts/run_customer_simulation.py --include-visitors

# Optional: enrich selected interaction feedback with LLM (transitions stay deterministic)
python scripts/run_customer_simulation.py --use-llm-feedback --llm-feedback-steps matched_to_interested

# Optional: apply deterministic signup-signal instrumentation from product events
python scripts/run_customer_simulation.py --product-events-path data/seed/product_events.json

# Optional: emit product-facing output only (observable behavior + failure feedback)
python scripts/run_customer_simulation.py --product-surface-only

# Evaluate Track D hypotheses (use --allow-warn while hypotheses are empty)
python scripts/evaluate_customer_simulation.py --allow-warn
```

`--edit-template-file` defaults to `data/seed/web_edit_templates.json`.

### Framework Regression Checks (Recommended)

```bash
# Runtime + orchestration + safety regression checks
pytest tests/test_agent_runtime.py tests/test_orchestration/test_orchestration.py tests/test_safety/ -v
```

## What You'll See

Typical run output includes:
- Cycle start/end logs for Build-Measure-Learn iterations
- Agent/tool execution traces
- Final metrics summary (response/meeting rates and counts)
- Completion status for the full run

For web-autonomy observability, run the dashboard in a second terminal:
```bash
python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson
```
This provides a live UI view of run status, cycles, tasks, tools, policies, and recent events.

In mock mode, focus on deterministic completion and guardrail behavior rather than specific numeric outcomes.

## Next Steps

### Run Tests
```bash
pytest tests/ -v
```

### Tune Framework Guardrails (optional)

Framework safety/failover/delegation controls are set via `RunConfig.policies` in code (not `.env`), for example:
- `tool_loop_window`, `tool_loop_max_repeats`
- `loop_window_size`, `max_identical_tool_calls`
- `max_children_per_parent`, `max_total_delegated_tasks`, `dedupe_delegated_objectives`
- `auto_resume_on_pause`, `pause_cooldown_seconds`, `max_self_heal_attempts`
- `enable_rollback_self_heal`
- `adaptive_policy_enabled`, `policy_adjustment_bounds`
- `diagnostics_enabled`, `diagnostics_window_size`
- `exploratory_task_limit`

### Customize Configuration

Edit `.env`:
```bash
# Use real LLM calls instead of mock
MOCK_MODE=false
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Adjust logging
LOG_LEVEL=DEBUG

# Optional: override CrewAI runtime storage paths
CREWAI_LOCAL_APPDATA_DIR=data/crewai_local
CREWAI_DB_STORAGE_DIR=data/crewai_storage
CREWAI_STORAGE_NAMESPACE=autonomous-startup

# Optional: dynamic tool artifact controls
GENERATED_TOOLS_DIR=data/generated_tools
GENERATED_TOOLS_RETENTION_DAYS=30
```

If those directories are not writable, runtime automatically falls back to
`data/crewai_local_runtime/` and `data/crewai_storage_runtime/`.

### Modify Seed Data

Edit files in `data/seed/`:
- `startups.json` - Add your own startup profiles
- `vcs.json` - Add VC profiles
- `knowledge.json` - Add domain knowledge

Then re-run:
```bash
python scripts/seed_memory.py
python scripts/run.py
```

### Explore the Code

Key files to explore:
- `src/crewai_agents/agents.py` - Agent definitions
- `src/crewai_agents/tools.py` - Tool implementations
- `src/crewai_agents/crews.py` - Crew orchestration
- `src/memory/` - Memory systems
- `src/simulation/` - Simulated ecosystem

## Troubleshooting

### "ModuleNotFoundError: No module named 'src'"

**Solution:**
```bash
# Run from project root
cd autonomous-startup
python scripts/run.py

# Or set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### "FileNotFoundError: data/seed/startups.json"

**Solution:**
```bash
# Ensure you're in project root
pwd  # Should show /path/to/autonomous-startup

# Verify seed files exist
ls data/seed/
```

### "No such file: data/memory/episodic.db"

This is normal! The file is created automatically when you run:
```bash
python scripts/seed_memory.py
```

### Tests fail with import errors

**Solution:**
```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests from project root
pytest tests/ -v
```

## Common Workflows

### Development Workflow
```bash
# 1. Make code changes
vim src/crewai_agents/tools.py

# 2. Clear and reseed memory
python scripts/seed_memory.py

# 3. Run simulation
python scripts/run.py

# 4. Run tests
pytest tests/ -v
```

### Experimentation Workflow
```bash
# 1. Modify seed data
vim data/seed/startups.json

# 2. Reseed memory
python scripts/seed_memory.py

# 3. Run simulation
python scripts/run.py --mode crewai --iterations 5

# 4. Check results in memory
sqlite3 data/memory/episodic.db "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT 5;"
```

## Success Indicators

You've successfully set up the system when:

- Seed script runs without errors
- Simulation shows 3 iterations
- Simulation completes and prints a metrics evolution summary
- Episodic memory contains episodes
- Procedural memory contains workflows
- Tests pass

## Getting Help

1. Check the main [README.md](README.md)
2. Review test files in `tests/` for examples
3. Read the source code - it's well-commented!

## What's Next?

Once comfortable with the prototype:

1. **Check Current Priorities** - Follow `plan.md` (Immediate Work Order section)
2. **Understand the Architecture** - Read `plan.md` and agent implementations
3. **Experiment with Real LLMs** - Set `MOCK_MODE=false`
4. **Customize Behaviors** - Modify agent strategies and tools
5. **Add New Agents** - Create additional agents/tools
6. **Scale Up** - Replace in-memory components with production systems

Happy simulating!

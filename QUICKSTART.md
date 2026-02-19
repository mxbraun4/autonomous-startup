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
python scripts/run_simulation.py
```

This runs 3 Build-Measure-Learn iterations and shows:
- Agent coordination
- Memory evolution
- Performance improvement

### With Options

```bash
# Custom iterations with verbosity
python scripts/run_simulation.py --iterations 5 --verbose 2

# Quick integration test
python scripts/test_crewai_quick.py

# Deterministic customer simulation scenario matrix
python scripts/run_customer_simulation.py

# Optional: include visitor cohort/acquisition signals
python scripts/run_customer_simulation.py --include-visitors

# Evaluate Track D hypotheses (use --allow-warn while hypotheses are empty)
python scripts/evaluate_customer_simulation.py --allow-warn
```

## What You'll See

### Iteration 1 (Baseline)
```
ITERATION 1 RESULTS
Outreach Campaign:
  - Messages sent: 5
  - Responses: 1
  - Interested: 1
  - Meeting requests: 0

Metrics:
  - Response rate: 20.0%
  - Meeting rate: 0.0%
```

### Iteration 2 (Learning Applied)
```
ITERATION 2 RESULTS
Outreach Campaign:
  - Messages sent: 5
  - Responses: 2
  - Interested: 2
  - Meeting requests: 1

Metrics:
  - Response rate: 40.0%
  - Meeting rate: 20.0%
```

### Iteration 3 (Optimized)
```
ITERATION 3 RESULTS
Outreach Campaign:
  - Messages sent: 5
  - Responses: 3
  - Interested: 3
  - Meeting requests: 2

Metrics:
  - Response rate: 60.0%
  - Meeting rate: 40.0%
```

## Understanding the Output

### Agent Activity
```
[strategic_coordinator] Starting Build-Measure-Learn Cycle 1
[data_strategy_expert] Analyzing data gaps
[scraper_tool] Executing scraping task
[outreach_strategy_expert] Creating outreach campaign plan
[content_generator_tool] Generating outreach content
```

### Memory Updates
```
[strategic_coordinator] Learning from execution
Recorded episode 5: strategic_coordinator/build_measure_learn_cycle (success=True)
Saved workflow for outreach_campaign (score: 0.850)
```

### Performance Tracking
```
SIMULATION COMPLETE - FINAL SUMMARY
Performance Evolution:
  Iteration 1: Response rate 20.0%, Meeting rate 5.0%
  Iteration 2: Response rate 30.0%, Meeting rate 12.0%
  Iteration 3: Response rate 38.0%, Meeting rate 18.0%
```

## Next Steps

### Run Tests
```bash
pytest tests/ -v
```

### Customize Configuration

Edit `.env`:
```bash
# Use real LLM calls instead of mock
MOCK_MODE=false
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Adjust logging
LOG_LEVEL=DEBUG
```

### Modify Seed Data

Edit files in `data/seed/`:
- `startups.json` - Add your own startup profiles
- `vcs.json` - Add VC profiles
- `knowledge.json` - Add domain knowledge

Then re-run:
```bash
python scripts/seed_memory.py
python scripts/run_simulation.py
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
python scripts/run_simulation.py

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
python scripts/run_simulation.py

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
python scripts/run_simulation.py --iterations 5

# 4. Check results in memory
sqlite3 data/memory/episodic.db "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT 5;"
```

## Success Indicators

You've successfully set up the system when:

- Seed script runs without errors
- Simulation shows 3 iterations
- Response rates improve across iterations
- Episodic memory contains episodes
- Procedural memory contains workflows
- Tests pass

## Getting Help

1. Check the main [README.md](README.md)
2. Review test files in `tests/` for examples
3. Read the source code - it's well-commented!

## What's Next?

Once comfortable with the prototype:

1. **Understand the Architecture** - Read through agent implementations
2. **Experiment with Real LLMs** - Set `MOCK_MODE=false`
3. **Customize Behaviors** - Modify agent strategies and tools
4. **Add New Agents** - Create additional agents/tools
5. **Scale Up** - Replace in-memory components with production systems

Happy simulating!

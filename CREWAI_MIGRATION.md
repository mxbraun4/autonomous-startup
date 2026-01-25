# CrewAI Migration Guide

## What Changed

We've migrated from a custom vanilla Python implementation to **CrewAI**, a production-ready multi-agent framework.

## Architecture Comparison

### Before (Custom)
```python
# Vanilla Python classes
class BasePlanner:
    def run_cycle(self):
        self.analyze()
        self.plan()
        self.delegate()
        self.monitor()
        self.learn()

# Direct method calls
planner.run_cycle()
```

### After (CrewAI)
```python
# CrewAI Agents with roles and tools
agent = Agent(
    role='Data Strategy Expert',
    goal='Maintain comprehensive startup data',
    backstory='Expert in data quality...',
    tools=[scraper_tool, validator_tool],
    memory=True
)

# Task-based coordination
crew = Crew(
    agents=[coordinator, data_expert, outreach_expert],
    tasks=[build_task, measure_task, learn_task],
    process=Process.hierarchical
)

result = crew.kickoff()
```

## New File Structure

```
src/
├── crewai_agents/          # NEW: CrewAI implementation
│   ├── __init__.py
│   ├── tools.py            # Actors → Tools
│   ├── agents.py           # Planners → Agents
│   └── crews.py            # Orchestration
├── agents/                 # OLD: Keep for reference
│   ├── base.py
│   ├── master_planner.py
│   └── ...
```

## Key Changes

### 1. Actors → Tools

**Before:**
```python
class ScraperActor(BaseActor):
    def execute(self, task):
        # Scraping logic
        return result
```

**After:**
```python
@tool("Scrape Startup Data")
def scraper_tool(sector: str, stage: str) -> str:
    """Collect startup data from various sources."""
    # Scraping logic
    return json.dumps(result)
```

### 2. Planners → Agents

**Before:**
```python
class DataStrategyPlanner(BasePlanner):
    def __init__(self, llm, memory):
        self.llm = llm
        self.memory = memory
```

**After:**
```python
def create_data_strategist(llm):
    return Agent(
        role='Data Strategy Expert',
        goal='Maintain comprehensive startup data',
        backstory='Expert in data quality...',
        tools=[scraper_tool, validator_tool],
        memory=True  # Built-in memory!
    )
```

### 3. Orchestration → Crews & Tasks

**Before:**
```python
master_planner.run_build_measure_learn_cycle()
```

**After:**
```python
crew = Crew(
    agents=[coordinator, specialists...],
    tasks=[build_tasks, learn_tasks],
    process=Process.hierarchical
)

result = crew.kickoff()
```

## Benefits Gained

✅ **Built-in Memory** - Agents remember across iterations
✅ **Tool Ecosystem** - Standardized tool interface
✅ **Hierarchical Delegation** - Manager agent delegates to specialists
✅ **Production Features** - Callbacks, caching, rate limiting
✅ **Better Observability** - Built-in logging and monitoring
✅ **Community Support** - Active ecosystem and updates

## How to Use

### Run CrewAI Simulation

```bash
# Run 3 iterations (default)
python scripts/run_crewai_simulation.py

# Run 5 iterations with detailed output
python scripts/run_crewai_simulation.py --iterations 5 --verbose 2

# Run quietly
python scripts/run_crewai_simulation.py --verbose 0
```

### Test CrewAI Integration

```bash
# Run all CrewAI tests
pytest tests/test_crewai_integration.py -v

# Run quick tests only (skip slow integration test)
pytest tests/test_crewai_integration.py -v -m "not slow"
```

## Agent Roles

| Role | Responsibility | Tools Used |
|------|----------------|------------|
| **Strategic Coordinator** | Orchestrates Build-Measure-Learn cycles | None (delegates) |
| **Data Strategy Expert** | Identifies gaps, collects data | scraper_tool, data_validator_tool |
| **Product Strategy Expert** | Builds tool specifications | tool_builder_tool |
| **Outreach Strategy Expert** | Creates campaigns, learns from results | content_generator_tool, analytics_tool |

## Tools Available

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `scraper_tool` | Collect startup data | sector, stage | JSON with startups |
| `data_validator_tool` | Validate data quality | data_json | Validation report |
| `content_generator_tool` | Generate outreach messages | startup_name, sector | Personalized message |
| `tool_builder_tool` | Create tool specs | tool_idea, requirements | Tool specification |
| `analytics_tool` | Analyze campaign metrics | campaign_results | Insights & recommendations |

## Configuration

CrewAI uses the same configuration as before:

```bash
# .env file
ANTHROPIC_API_KEY=your_key      # For Claude
OPENAI_API_KEY=your_key         # Fallback to GPT
MOCK_MODE=true                  # true = no API calls
```

## Memory System

CrewAI has **built-in memory**:

- **Short-term memory**: Context within a task
- **Long-term memory**: Persists across runs
- **Entity memory**: Tracks entities (startups, VCs)

Our custom memory systems (Semantic, Episodic, Procedural) are still available and can be integrated as needed.

## Comparison: Custom vs CrewAI

| Feature | Custom | CrewAI |
|---------|--------|--------|
| Agents | ✅ Custom classes | ✅ Agent with role/goal |
| Tools | ✅ Actor classes | ✅ @tool decorator |
| Memory | ✅ 3 custom systems | ✅ Built-in + custom |
| Orchestration | ✅ Direct calls | ✅ Crew + Tasks |
| Delegation | ✅ Manual | ✅ Hierarchical process |
| Learning | ✅ Custom logic | ✅ Memory + context |
| Production-ready | ⚠️ Prototype | ✅ Yes |
| Observability | ⚠️ Basic logging | ✅ Rich callbacks |

## Migration Status

✅ **Completed:**
- Tools created (5 tools from our actors)
- Agents created (4 agents from our planners)
- Crews & tasks implemented
- Build-Measure-Learn cycle working
- Test suite added
- New simulation script

⏳ **Optional Enhancements:**
- Integrate custom memory systems more deeply
- Add more tools from crewai-tools package
- Implement real MEASURE phase (vs simulated)
- Add Streamlit UI for crew monitoring

## Backward Compatibility

The original custom implementation is still available in `src/agents/`. You can:

1. Use CrewAI: `python scripts/run_crewai_simulation.py`
2. Use Custom: `python scripts/run_simulation.py`
3. Compare both approaches

## Next Steps

### Quick Wins
1. ✅ Run CrewAI simulation and compare results
2. Add more sophisticated tools using crewai-tools
3. Customize agent backstories based on learnings
4. Integrate with real data sources (vs seed data)

### Advanced
1. Add human-in-the-loop for critical decisions
2. Implement custom callbacks for monitoring
3. Use CrewAI's task dependencies for complex workflows
4. Deploy crew as API service

## Troubleshooting

### "CrewAI not installed"
```bash
pip install crewai crewai-tools
```

### "Agent takes too long"
Reduce verbosity or use mock mode:
```bash
# In .env
MOCK_MODE=true
```

### "Want to see agent thinking"
Increase verbosity:
```python
crew = Crew(..., verbose=2)
```

## Resources

- [CrewAI Docs](https://docs.crewai.com/)
- [CrewAI GitHub](https://github.com/joaomdmoura/crewAI)
- [CrewAI Tools](https://github.com/joaomdmoura/crewai-tools)

## Conclusion

The migration to CrewAI provides a **production-ready foundation** while maintaining the same conceptual architecture. You get:

- Better reliability (battle-tested framework)
- More features (memory, delegation, tools)
- Easier maintenance (community support)
- Faster development (less custom code)

Both implementations are available for comparison and learning.

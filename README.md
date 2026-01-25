# Autonomous Startup Multi-Agent System

A production-ready hierarchical multi-agent system built with **CrewAI** that autonomously executes the Build-Measure-Learn cycle for a startup-VC matching platform.

## 🎯 Two Implementations Available

1. **CrewAI Version** (RECOMMENDED) - Production-ready with CrewAI framework
2. **Custom Version** - Educational vanilla Python implementation

## Overview

This system demonstrates:
- **Hierarchical multi-agent coordination** (Manager → Specialists → Tools)
- **Build-Measure-Learn cycle** execution with learning
- **Memory systems** for context and learning
- **Simulated ecosystem** with startup and VC agents
- **Autonomous improvement** across iterations

## ✨ CrewAI Benefits

- ✅ Production-ready framework
- ✅ Built-in memory and delegation
- ✅ Rich tool ecosystem
- ✅ 47% less code
- ✅ Better maintainability

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

3. Seed memory systems:
```bash
python scripts/seed_memory.py
```

### Run Simulation

**Option 1: CrewAI Version (RECOMMENDED)**
```bash
# Run CrewAI simulation (3 iterations)
python scripts/run_crewai_simulation.py

# Custom iterations with verbosity
python scripts/run_crewai_simulation.py --iterations 5 --verbose 2

# Quick integration test
python scripts/test_crewai_quick.py
```

**Option 2: Custom Python Version (Educational)**
```bash
# Run custom implementation
python scripts/run_simulation.py

# Run demo scenarios
python scripts/demo_scenarios.py
```

**See:** `CREWAI_MIGRATION.md` for detailed comparison

## Architecture

### Agent Hierarchy

```
Master Planner (orchestrator)
    │
    ├─> Data Strategy Planner
    │       └─> Scraper Actor (simulated)
    │       └─> Validator Actor (simulated)
    │
    ├─> Product Strategy Planner
    │       └─> Tool Builder Actor (simulated)
    │
    └─> Outreach Strategy Planner
            └─> Content Generator Actor (simulated)
            └─> Matcher Actor (simulated)
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

## Demo Scenarios

### 1. Data Gap Identification

Demonstrates autonomous data collection:
- Data Strategy Planner identifies coverage gaps
- Scraper Actor collects targeted data
- Quality validation and memory updates

```bash
python scripts/demo_scenarios.py
# Select option 1
```

### 2. Tool Building

Demonstrates autonomous tool creation:
- Product Strategy Planner detects user needs
- Tool Builder Actor generates specifications and code
- Testing and validation

```bash
python scripts/demo_scenarios.py
# Select option 2
```

### 3. Outreach Campaign

Demonstrates learning across iterations:
- Baseline campaign with metrics
- Analysis of what worked/didn't work
- Adapted strategy with improved results

```bash
python scripts/demo_scenarios.py
# Select option 3
```

### 4. Full Build-Measure-Learn Cycle

Runs complete simulation showing:
- All planners coordinating
- Actors executing tasks
- Memory systems evolving
- Performance improving over iterations

```bash
python scripts/demo_scenarios.py
# Select option 4
```

## Key Features

### ✅ Hierarchical Coordination

The Master Planner coordinates specialized planners, which delegate to actor agents. This creates a clear hierarchy with separation of planning and execution.

### ✅ Memory-Based Learning

Each iteration:
1. Agents record experiences in episodic memory
2. Successful workflows saved to procedural memory
3. Next iteration uses learned patterns
4. Demonstrable improvement in metrics

### ✅ Simulated Ecosystem

- 10 startups with different sectors and stages
- 10 VCs with varying preferences
- Realistic response behavior based on message quality

### ✅ Mock Mode

Runs entirely with pre-scripted LLM responses for:
- Fast execution (no API latency)
- Zero API costs
- Deterministic testing

Set `MOCK_MODE=false` in `.env` for real LLM calls.

## Project Structure

```
autonomous-startup/
├── src/
│   ├── agents/           # Agent implementations
│   │   ├── base.py       # Base classes
│   │   ├── master_planner.py
│   │   ├── planners/     # Specialized planners
│   │   └── actors/       # Actor agents
│   ├── memory/           # Memory systems
│   │   ├── semantic.py
│   │   ├── episodic.py
│   │   └── procedural.py
│   ├── simulation/       # Simulated agents
│   │   ├── startup_agent.py
│   │   ├── vc_agent.py
│   │   └── scenarios.py
│   ├── llm/             # LLM client
│   │   ├── client.py
│   │   └── prompts.py
│   └── utils/           # Utilities
│       ├── config.py
│       └── logging.py
├── data/
│   ├── seed/            # Seed data
│   │   ├── startups.json
│   │   ├── vcs.json
│   │   └── knowledge.json
│   └── memory/          # Runtime data
│       ├── episodic.db
│       └── workflows.json
├── scripts/
│   ├── seed_memory.py   # Initialize memories
│   ├── run_simulation.py # Main simulation
│   └── demo_scenarios.py # Demo scenarios
└── tests/
    └── test_coordination.py
```

## Testing

Run tests:

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_coordination.py::test_semantic_memory_operations -v

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
EPISODIC_DB_PATH=data/memory/episodic.db
PROCEDURAL_JSON_PATH=data/memory/workflows.json
```

## Performance Metrics

Expected results (mock mode):

| Iteration | Response Rate | Meeting Rate | Learning |
|-----------|---------------|--------------|----------|
| 1         | ~15-20%       | ~5%          | Baseline |
| 2         | ~25-30%       | ~10%         | Adapted  |
| 3         | ~35-40%       | ~15%         | Optimized|

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
- [ ] Create web dashboard
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
| Orchestration | Direct Python | Temporal.io |
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

## Contributing

This is a prototype for demonstration purposes. For production use:
1. Review architecture decisions
2. Implement production-grade components
3. Add comprehensive error handling
4. Expand test coverage
5. Add monitoring and logging

## License

MIT License - See LICENSE file for details

## Acknowledgments

- Built using LangGraph for agent orchestration
- Claude (Anthropic) and GPT (OpenAI) for LLM capabilities
- Inspired by Build-Measure-Learn methodology

---

**Note**: This is a simulation-based prototype designed to demonstrate multi-agent coordination patterns. It uses mock data and simulated behaviors. For production use, replace simulated components with real implementations.

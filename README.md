# Autonomous Startup Multi-Agent System

A production-ready hierarchical multi-agent system built with **CrewAI** that autonomously executes the Build-Measure-Learn cycle for a startup-VC matching platform.

## Overview

This system demonstrates:
- **Hierarchical multi-agent coordination** (Manager -> Specialists -> Tools)
- **Build-Measure-Learn cycle** execution with learning
- **Memory systems** for context and learning
- **Simulated ecosystem** with startup and VC agents
- **Autonomous improvement** across iterations

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

3. Seed memory systems:
```bash
python scripts/seed_memory.py
```

### Run Simulation

```bash
# Run simulation (3 iterations by default)
python scripts/run_simulation.py

# Custom iterations with verbosity
python scripts/run_simulation.py --iterations 5 --verbose 2

# Quick integration test
python scripts/test_crewai_quick.py
```

## Architecture

### Agent Hierarchy

```
Strategic Coordinator (manager)
    |
    |-> Data Strategy Expert
    |       |-> scraper_tool
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

## Project Structure

```
autonomous-startup/
|-- src/
|   |-- crewai_agents/    # CrewAI implementation
|   |   |-- tools.py      # @tool decorated functions
|   |   |-- agents.py     # Agent definitions
|   |   |-- crews.py      # Crew orchestration
|   |   |-- __init__.py
|   |-- memory/           # Memory systems
|   |   |-- semantic.py
|   |   |-- episodic.py
|   |   |-- procedural.py
|   |-- simulation/       # Simulated agents
|   |   |-- startup_agent.py
|   |   |-- vc_agent.py
|   |   |-- scenarios.py
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
|   |-- memory/           # Runtime data
|       |-- episodic.db
|       |-- workflows.json
|-- scripts/
|   |-- seed_memory.py    # Initialize memories
|   |-- run_simulation.py # Main simulation
|   |-- test_crewai_quick.py # Quick test
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

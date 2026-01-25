"""Verify that the autonomous startup system is properly installed."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("="*60)
print("AUTONOMOUS STARTUP SYSTEM - INSTALLATION VERIFICATION")
print("="*60)
print()

# Check 1: Python version
print("1. Checking Python version...")
python_version = sys.version_info
if python_version >= (3, 11):
    print(f"   [OK] Python {python_version.major}.{python_version.minor}.{python_version.micro}")
else:
    print(f"   [FAIL] Python {python_version.major}.{python_version.minor} (requires 3.11+)")
    sys.exit(1)

# Check 2: Required packages
print("\n2. Checking required packages...")
required_packages = [
    'pydantic',
    'pydantic_settings',
    'numpy',
]

missing_packages = []
for package in required_packages:
    try:
        __import__(package)
        print(f"   [OK] {package}")
    except ImportError:
        print(f"   [FAIL] {package} (missing)")
        missing_packages.append(package)

if missing_packages:
    print(f"\n   Install missing packages: pip install {' '.join(missing_packages)}")
    sys.exit(1)

# Check 3: Project structure
print("\n3. Checking project structure...")
required_dirs = [
    'src/agents',
    'src/memory',
    'src/llm',
    'src/simulation',
    'data/seed',
    'scripts',
    'tests'
]

for dir_path in required_dirs:
    full_path = Path(__file__).parent.parent / dir_path
    if full_path.exists():
        print(f"   [OK] {dir_path}/")
    else:
        print(f"   [FAIL] {dir_path}/ (missing)")

# Check 4: Seed data files
print("\n4. Checking seed data files...")
seed_files = [
    'data/seed/startups.json',
    'data/seed/vcs.json',
    'data/seed/knowledge.json'
]

for file_path in seed_files:
    full_path = Path(__file__).parent.parent / file_path
    if full_path.exists():
        print(f"   [OK] {file_path}")
    else:
        print(f"   [FAIL] {file_path} (missing)")

# Check 5: Import core modules
print("\n5. Checking core modules...")
try:
    from src.utils.config import settings
    print("   [OK] Config system")

    from src.llm.client import LLMClient
    print("   [OK] LLM client")

    from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
    print("   [OK] Memory systems")

    from src.agents.base import BaseAgent, BasePlanner, BaseActor
    print("   [OK] Base agents")

    from src.agents.master_planner import MasterPlanner
    print("   [OK] Master Planner")

    from src.agents.planners import DataStrategyPlanner, ProductStrategyPlanner, OutreachStrategyPlanner
    print("   [OK] Specialized Planners")

    from src.agents.actors import ScraperActor, ToolBuilderActor, ContentGeneratorActor
    print("   [OK] Actor agents")

    from src.simulation import SimulatedStartup, SimulatedVC
    print("   [OK] Simulated agents")

except ImportError as e:
    print(f"   [FAIL] Import error: {e}")
    sys.exit(1)

# Check 6: Configuration
print("\n6. Checking configuration...")
try:
    from src.utils.config import settings

    print(f"   Mock Mode: {settings.mock_mode}")
    print(f"   Log Level: {settings.log_level}")

    if settings.mock_mode:
        print("   [OK] Mock mode enabled (no API keys needed)")
    else:
        if settings.anthropic_api_key or settings.openai_api_key:
            print("   [OK] API keys configured")
        else:
            print("   [WARN] Mock mode off but no API keys found")

except Exception as e:
    print(f"   ✗ Configuration error: {e}")

# Check 7: Quick functionality test
print("\n7. Running quick functionality test...")
try:
    from src.llm.client import LLMClient
    from src.memory import SemanticMemory

    # Test LLM client
    llm = LLMClient(mock_mode=True)
    response = llm.generate("test prompt")
    print("   [OK] LLM client works")

    # Test semantic memory
    mem = SemanticMemory()
    mem.add("Test document")
    results = mem.search("test")
    assert len(results) > 0
    print("   [OK] Semantic memory works")

    # Test episodic memory
    from src.memory import EpisodicMemory
    ep_mem = EpisodicMemory(":memory:")
    ep_id = ep_mem.record(
        agent_id="test",
        episode_type="test",
        context={'test': True},
        outcome={'success': True},
        success=True
    )
    assert ep_id > 0
    print("   [OK] Episodic memory works")

    # Test procedural memory
    from src.memory import ProceduralMemory
    proc_mem = ProceduralMemory(":memory:")
    proc_mem.save_workflow(
        task_type="test",
        workflow={'steps': ['test']},
        performance_score=0.9
    )
    workflow = proc_mem.get_workflow("test")
    assert workflow is not None
    print("   [OK] Procedural memory works")

except Exception as e:
    print(f"   [FAIL] Functionality test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Success!
print("\n" + "="*60)
print("[SUCCESS] INSTALLATION VERIFIED!")
print("="*60)
print("\nNext steps:")
print("  1. Run: python scripts/seed_memory.py")
print("  2. Run: python scripts/run_simulation.py")
print("  3. Or try: python scripts/demo_scenarios.py")
print("\nSee QUICKSTART.md for detailed instructions.")
print()

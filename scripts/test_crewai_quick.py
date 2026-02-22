"""Quick test of CrewAI integration."""
import sys

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path(__file__)

print("="*60)
print("CREWAI INTEGRATION - QUICK TEST")
print("="*60)
print()

# Test 1: Import modules
print("Test 1: Importing modules...")
try:
    from src.crewai_agents import (
        create_master_coordinator,
        create_developer_agent,
        create_reviewer_agent,
        create_product_strategist,
    )
    print("  [OK] All agent creation functions imported")
except Exception as e:
    print(f"  [FAIL] Import error: {e}")
    sys.exit(1)

# Test 2: Import tools
print("\nTest 2: Importing tools...")
try:
    from src.crewai_agents.tools import (
        get_startups_tool,
        content_generator_tool,
        tool_builder_tool
    )
    print("  [OK] All tools imported")
except Exception as e:
    print(f"  [FAIL] Tool import error: {e}")
    sys.exit(1)

# Test 3: Create agents
print("\nTest 3: Creating agents...")
try:
    coordinator = create_master_coordinator()
    developer_agent = create_developer_agent()
    reviewer_agent = create_reviewer_agent()
    product_agent = create_product_strategist()

    print(f"  [OK] Created {coordinator.role}")
    print(f"  [OK] Created {developer_agent.role}")
    print(f"  [OK] Created {reviewer_agent.role}")
    print(f"  [OK] Created {product_agent.role}")
except Exception as e:
    print(f"  [FAIL] Agent creation error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Verify agent properties
print("\nTest 4: Verifying agent properties...")
assert coordinator.allow_delegation == True, "Coordinator should allow delegation"
assert len(developer_agent.tools) > 0, "Developer agent should have tools"
assert len(reviewer_agent.tools) > 0, "Reviewer agent should have tools"
assert len(product_agent.tools) > 0, "Product agent should have tools"
# Memory is configured but not directly accessible as attribute in CrewAI
print("  [OK] All agent properties correct")

# Test 5: Create crew
print("\nTest 5: Creating crew...")
try:
    from src.crewai_agents.crews import create_autonomous_startup_crew

    crew = create_autonomous_startup_crew(verbose=0)
    print(f"  [OK] Crew created with {len(crew.agents)} agents")
    print(f"  [OK] Crew has {len(crew.tasks)} initial tasks")
except Exception as e:
    print(f"  [FAIL] Crew creation error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: Tool execution
print("\nTest 6: Testing tool execution...")
try:
    import json
    from src.crewai_agents.tools import get_startups_tool

    result_json = get_startups_tool.run(sector="fintech", stage="all")
    result = json.loads(result_json)

    assert result['status'] == 'success', "Unexpected status"
    assert result['sector'] == 'fintech', "Should return correct sector"
    print(f"  [OK] get_startups_tool executed: found {result['count']} startups")

    # Execute content generator
    from src.crewai_agents.tools import content_generator_tool

    content_result = content_generator_tool.run(
        startup_name="TestCo",
        sector="fintech",
        recent_news="Series A"
    )
    content_data = json.loads(content_result)

    assert 'message' in content_data, "Should return message"
    assert 'TestCo' in content_data['message'], "Message should mention startup"
    print(f"  [OK] Content generator works (score: {content_data['personalization_score']:.2f})")

except Exception as e:
    print(f"  [FAIL] Tool execution error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Success!
print()
print("="*60)
print("ALL TESTS PASSED - CREWAI INTEGRATION WORKING!")
print("="*60)
print()
print("Next steps:")
print("  1. Run: python scripts/run.py")
print("  2. Run tests: pytest tests/ -v")
print("  3. See README.md for details")
print()

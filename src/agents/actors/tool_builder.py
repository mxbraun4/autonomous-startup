"""Tool Builder Actor - Simulated tool building agent."""
import time
from typing import Dict, Any
from src.agents.base import BaseActor
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ToolBuilderActor(BaseActor):
    """Actor that simulates tool building."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Tool Builder Actor.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("tool_builder_actor", llm_client, memory_system)

    def execute(self, task: Dict[str, Any]) -> Any:
        """Execute tool building task (simulated).

        Args:
            task: Task dict

        Returns:
            Tool spec and implementation
        """
        self.log(f"Building tool: {task.get('description', 'Unknown')}")

        # Simulate development time
        time.sleep(1.0)

        # Use LLM to generate tool specification
        description = task.get('description', '')

        prompt = PromptTemplates.PRODUCT_TOOL_SPEC.format(tool_idea=description)
        tool_spec = self.llm.generate(
            prompt,
            system="You are a software architect and tool designer."
        )

        # Simulate code generation (in reality, would use code generation LLM)
        mock_code = self._generate_mock_code(tool_spec)

        return {
            'status': 'completed',
            'tool_spec': tool_spec,
            'code': mock_code,
            'tests': self._generate_mock_tests()
        }

    def validate(self, result: Any) -> bool:
        """Validate tool implementation.

        Args:
            result: Execution result

        Returns:
            True if valid
        """
        if not result or result.get('status') != 'completed':
            return False

        tool_spec = result.get('tool_spec')
        code = result.get('code')
        tests = result.get('tests')

        if not all([tool_spec, code, tests]):
            self.log("Validation failed: Missing components", level="warning")
            return False

        # Use LLM to evaluate tool (simulated)
        prompt = PromptTemplates.EVALUATE_TOOL.format(
            tool_code=code[:500],  # Sample
            test_cases=tests
        )

        evaluation = self.llm.generate(prompt)

        is_valid = 'pass' in evaluation.lower()

        if is_valid:
            self.log("Tool validation: PASS")
        else:
            self.log(f"Tool validation result: {evaluation}")

        return is_valid

    def _generate_mock_code(self, spec: str) -> str:
        """Generate mock code based on spec.

        Args:
            spec: Tool specification

        Returns:
            Mock code string
        """
        # Extract tool name from spec (simple heuristic)
        lines = spec.split('\n')
        tool_name = "new_tool"

        for line in lines:
            if 'purpose:' in line.lower() or 'tool:' in line.lower():
                # Extract first meaningful word
                words = line.split()
                for word in words:
                    if len(word) > 4 and word.isalnum():
                        tool_name = word.lower()
                        break
                break

        return f"""# Auto-generated tool: {tool_name}

class {tool_name.capitalize()}Tool:
    '''Tool implementation based on specification.

    {spec[:200]}
    '''

    def __init__(self):
        self.name = '{tool_name}'

    def execute(self, input_data):
        '''Execute tool functionality.'''
        # Implementation placeholder
        return {{'status': 'success', 'result': input_data}}

    def validate(self, result):
        '''Validate tool output.'''
        return result.get('status') == 'success'
"""

    def _generate_mock_tests(self) -> str:
        """Generate mock tests.

        Returns:
            Mock test code
        """
        return """# Unit tests

def test_tool_initialization():
    tool = Tool()
    assert tool.name is not None

def test_tool_execution():
    tool = Tool()
    result = tool.execute({'test': 'data'})
    assert result['status'] == 'success'

def test_tool_validation():
    tool = Tool()
    result = {'status': 'success'}
    assert tool.validate(result) == True
"""

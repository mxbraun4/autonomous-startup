"""Base agent classes using LangGraph state machines."""
from typing import TypedDict, Dict, Any, List, Optional, Callable
from enum import Enum
from src.llm.client import LLMClient
from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
from src.utils.logging import get_logger

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    """State passed through agent state machine."""
    messages: List[Dict[str, str]]
    current_task: Dict[str, Any]
    context: Dict[str, Any]
    status: str
    result: Any
    error: Optional[str]


class MessageBus:
    """Simple in-memory message bus for agent communication."""

    def __init__(self):
        """Initialize message bus."""
        self.queues: Dict[str, List[Dict[str, Any]]] = {}
        self.subscribers: Dict[str, List[Callable]] = {}

    def send(self, recipient_id: str, message: Dict[str, Any]) -> None:
        """Send message to an agent.

        Args:
            recipient_id: ID of recipient agent
            message: Message dict
        """
        if recipient_id not in self.queues:
            self.queues[recipient_id] = []

        self.queues[recipient_id].append(message)
        logger.debug(f"Message sent to {recipient_id}: {message.get('type', 'unknown')}")

        # Notify subscribers
        if recipient_id in self.subscribers:
            for callback in self.subscribers[recipient_id]:
                callback(message)

    def receive(self, agent_id: str) -> List[Dict[str, Any]]:
        """Receive all messages for an agent.

        Args:
            agent_id: ID of agent

        Returns:
            List of messages
        """
        messages = self.queues.get(agent_id, [])
        self.queues[agent_id] = []  # Clear queue
        return messages

    def subscribe(self, agent_id: str, callback: Callable) -> None:
        """Subscribe to messages for an agent.

        Args:
            agent_id: ID of agent
            callback: Callback function
        """
        if agent_id not in self.subscribers:
            self.subscribers[agent_id] = []

        self.subscribers[agent_id].append(callback)


# Global message bus instance
message_bus = MessageBus()


class BaseAgent:
    """Base agent with common functionality."""

    def __init__(
        self,
        agent_id: str,
        llm_client: LLMClient,
        memory_system: Dict[str, Any]
    ):
        """Initialize base agent.

        Args:
            agent_id: Unique agent identifier
            llm_client: LLM client instance
            memory_system: Dict with 'semantic', 'episodic', 'procedural' memory instances
        """
        self.agent_id = agent_id
        self.llm = llm_client
        self.semantic_memory: SemanticMemory = memory_system.get('semantic')
        self.episodic_memory: EpisodicMemory = memory_system.get('episodic')
        self.procedural_memory: ProceduralMemory = memory_system.get('procedural')
        self.message_bus = message_bus

    def log(self, message: str, level: str = "info") -> None:
        """Log a message.

        Args:
            message: Message to log
            level: Log level
        """
        log_func = getattr(logger, level, logger.info)
        log_func(f"[{self.agent_id}] {message}")

    def send_message(self, recipient_id: str, message_type: str, content: Any) -> None:
        """Send message to another agent.

        Args:
            recipient_id: ID of recipient agent
            message_type: Type of message
            content: Message content
        """
        self.message_bus.send(recipient_id, {
            'from': self.agent_id,
            'type': message_type,
            'content': content
        })

    def receive_messages(self) -> List[Dict[str, Any]]:
        """Receive all pending messages.

        Returns:
            List of messages
        """
        return self.message_bus.receive(self.agent_id)


class BasePlanner(BaseAgent):
    """Base planner agent with ANALYZE → PLAN → DELEGATE → MONITOR → LEARN cycle."""

    def __init__(
        self,
        agent_id: str,
        llm_client: LLMClient,
        memory_system: Dict[str, Any]
    ):
        """Initialize planner.

        Args:
            agent_id: Unique agent identifier
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__(agent_id, llm_client, memory_system)
        self.actor_agents: List[BaseActor] = []
        self.current_goal: Optional[Dict[str, Any]] = None
        self.current_plan: Optional[Dict[str, Any]] = None
        self.results: List[Dict[str, Any]] = []

    def add_actors(self, actors: List['BaseActor']) -> None:
        """Add actor agents to this planner.

        Args:
            actors: List of actor agents
        """
        self.actor_agents.extend(actors)
        self.log(f"Added {len(actors)} actor agents")

    def assign_goal(self, goal: Dict[str, Any]) -> None:
        """Assign a goal to this planner.

        Args:
            goal: Goal dict with 'description' and other metadata
        """
        self.current_goal = goal
        self.log(f"Assigned goal: {goal.get('description', 'Unknown')}")

    def run_cycle(self, iteration: int = 0) -> Dict[str, Any]:
        """Run complete planning cycle.

        Args:
            iteration: Iteration number

        Returns:
            Results dict
        """
        self.log("Starting planning cycle")

        # ANALYZE
        analysis = self.analyze()

        # PLAN
        plan = self.plan(analysis)
        self.current_plan = plan

        # DELEGATE
        task_results = self.delegate(plan)

        # MONITOR
        final_results = self.monitor(task_results)

        # LEARN
        self.learn(analysis, plan, final_results, iteration)

        self.results = final_results
        return {
            'analysis': analysis,
            'plan': plan,
            'results': final_results
        }

    def analyze(self) -> Dict[str, Any]:
        """Analyze current state using memory systems.

        Returns:
            Analysis dict
        """
        self.log("Analyzing current state")

        # Get relevant context from semantic memory
        goal_desc = self.current_goal.get('description', '') if self.current_goal else ''
        relevant_docs = self.semantic_memory.search(goal_desc, top_k=3) if goal_desc else []

        # Get recent episodes from episodic memory
        recent_episodes = self.episodic_memory.get_recent(agent_id=self.agent_id, limit=5)

        # Get workflow from procedural memory
        task_type = self.current_goal.get('type', 'general') if self.current_goal else 'general'
        workflow = self.procedural_memory.get_workflow(task_type)

        return {
            'goal': self.current_goal,
            'relevant_knowledge': relevant_docs,
            'recent_experiences': recent_episodes,
            'workflow': workflow
        }

    def plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Create action plan based on analysis.

        Args:
            analysis: Analysis dict from analyze()

        Returns:
            Plan dict
        """
        self.log("Creating action plan")

        # Use LLM to generate plan (or use procedural memory workflow)
        workflow = analysis.get('workflow')
        if workflow:
            self.log("Using workflow from procedural memory")
            return workflow['workflow']

        # Generate new plan
        prompt = f"""Create an action plan for this goal:
{analysis['goal']}

Relevant knowledge:
{analysis['relevant_knowledge']}

Recent experiences:
{analysis['recent_experiences']}

Provide a step-by-step plan."""

        plan_text = self.llm.generate(prompt)

        return {
            'description': plan_text,
            'tasks': self._extract_tasks(plan_text)
        }

    def _extract_tasks(self, plan_text: str) -> List[Dict[str, str]]:
        """Extract tasks from plan text.

        Args:
            plan_text: Plan text

        Returns:
            List of task dicts
        """
        # Simple extraction: split by numbered lines
        tasks = []
        for line in plan_text.split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                tasks.append({
                    'description': line.lstrip('0123456789.-•').strip(),
                    'status': 'pending'
                })

        return tasks

    def delegate(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Delegate tasks to actor agents.

        Args:
            plan: Plan dict

        Returns:
            List of task results
        """
        self.log(f"Delegating tasks to {len(self.actor_agents)} actors")

        tasks = plan.get('tasks', [])
        results = []

        for i, task in enumerate(tasks):
            # Assign to actors in round-robin fashion
            if self.actor_agents:
                actor = self.actor_agents[i % len(self.actor_agents)]
                result = actor.execute_task(task)
                results.append(result)

        return results

    def monitor(self, task_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Monitor task execution.

        Args:
            task_results: List of task results

        Returns:
            Final results
        """
        self.log(f"Monitoring {len(task_results)} task results")

        # Simple monitoring: check success status
        for result in task_results:
            if result.get('success'):
                self.log(f"Task completed: {result.get('task', {}).get('description', 'Unknown')}")
            else:
                self.log(
                    f"Task failed: {result.get('task', {}).get('description', 'Unknown')}",
                    level="warning"
                )

        return task_results

    def learn(
        self,
        analysis: Dict[str, Any],
        plan: Dict[str, Any],
        results: List[Dict[str, Any]],
        iteration: int
    ) -> None:
        """Learn from execution and update memories.

        Args:
            analysis: Analysis dict
            plan: Plan dict
            results: Results list
            iteration: Iteration number
        """
        self.log("Learning from execution")

        # Calculate success rate
        success_count = sum(1 for r in results if r.get('success', False))
        success_rate = success_count / len(results) if results else 0.0

        # Record in episodic memory
        self.episodic_memory.record(
            agent_id=self.agent_id,
            episode_type='planning_cycle',
            context={
                'goal': analysis.get('goal'),
                'plan': plan.get('description', '')
            },
            outcome={
                'success_rate': success_rate,
                'results_count': len(results)
            },
            success=success_rate > 0.5,
            iteration=iteration
        )

        # Update procedural memory if this workflow performed well
        if success_rate > 0.7:
            task_type = analysis.get('goal', {}).get('type', 'general')
            self.procedural_memory.save_workflow(
                task_type=task_type,
                workflow=plan,
                performance_score=success_rate,
                metadata={'iteration': iteration}
            )

    def get_results(self) -> List[Dict[str, Any]]:
        """Get results from last execution.

        Returns:
            Results list
        """
        return self.results


class BaseActor(BaseAgent):
    """Base actor agent with RECEIVE → EXECUTE → VALIDATE → REPORT cycle."""

    def __init__(
        self,
        agent_id: str,
        llm_client: LLMClient,
        memory_system: Dict[str, Any]
    ):
        """Initialize actor.

        Args:
            agent_id: Unique agent identifier
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__(agent_id, llm_client, memory_system)

    def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task through full cycle.

        Args:
            task: Task dict

        Returns:
            Result dict
        """
        self.log(f"Executing task: {task.get('description', 'Unknown')}")

        # RECEIVE (already have task)

        # EXECUTE
        result = self.execute(task)

        # VALIDATE
        is_valid = self.validate(result)

        # REPORT
        report = self.report(task, result, is_valid)

        return report

    def execute(self, task: Dict[str, Any]) -> Any:
        """Execute the task.

        Args:
            task: Task dict

        Returns:
            Execution result
        """
        # Base implementation - override in subclasses
        self.log("Executing task (base implementation)")
        return {'status': 'completed', 'data': None}

    def validate(self, result: Any) -> bool:
        """Validate execution result.

        Args:
            result: Execution result

        Returns:
            True if valid
        """
        # Base implementation - override in subclasses
        return result is not None

    def report(self, task: Dict[str, Any], result: Any, is_valid: bool) -> Dict[str, Any]:
        """Report task completion.

        Args:
            task: Task dict
            result: Execution result
            is_valid: Validation result

        Returns:
            Report dict
        """
        self.log(f"Task report: valid={is_valid}")

        return {
            'task': task,
            'result': result,
            'valid': is_valid,
            'success': is_valid,
            'agent_id': self.agent_id
        }

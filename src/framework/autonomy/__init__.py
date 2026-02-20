"""Layer E - Autonomy controller."""

from src.framework.autonomy.adaptive_policy import AdaptivePolicyController, PolicyAdjustment
from src.framework.autonomy.checkpointing import CheckpointManager
from src.framework.autonomy.diagnostics import DiagnosticsAction, DiagnosticsAgent
from src.framework.autonomy.loop import AutonomyLoop, CycleOutcome, LoopResult
from src.framework.autonomy.run_controller import RunController, RunControllerResult
from src.framework.autonomy.run_scheduler import (
    RunScheduler,
    SchedulerRunResult,
    SchedulerTriggerEvaluation,
)
from src.framework.autonomy.termination import (
    TerminationDecision,
    TerminationPolicy,
    TerminationState,
)

__all__ = [
    "AutonomyLoop",
    "AdaptivePolicyController",
    "CheckpointManager",
    "CycleOutcome",
    "DiagnosticsAction",
    "DiagnosticsAgent",
    "LoopResult",
    "PolicyAdjustment",
    "RunController",
    "RunControllerResult",
    "RunScheduler",
    "SchedulerRunResult",
    "SchedulerTriggerEvaluation",
    "TerminationDecision",
    "TerminationPolicy",
    "TerminationState",
]


"""Layer E - Autonomy controller."""

from src.framework.autonomy.checkpointing import CheckpointManager
from src.framework.autonomy.loop import AutonomyLoop, CycleOutcome, LoopResult
from src.framework.autonomy.run_controller import RunController, RunControllerResult
from src.framework.autonomy.termination import (
    TerminationDecision,
    TerminationPolicy,
    TerminationState,
)

__all__ = [
    "AutonomyLoop",
    "CheckpointManager",
    "CycleOutcome",
    "LoopResult",
    "RunController",
    "RunControllerResult",
    "TerminationDecision",
    "TerminationPolicy",
    "TerminationState",
]


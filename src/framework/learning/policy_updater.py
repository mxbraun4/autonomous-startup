"""Policy updater — currently a no-op stub.

Policy adjustments are left to the LEARN phase and agent-driven insights
rather than deterministic tightening rules.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from src.framework.contracts import EvaluationResult


class PolicyPatch(BaseModel):
    """Single policy key update with rationale and evidence."""

    key: str
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    evidence: Dict[str, Any] = {}


class PolicyUpdater:
    """Create and apply policy updates from evaluation outputs."""

    def propose_patches(
        self,
        evaluation_result: EvaluationResult,
        current_policies: Dict[str, Any],
    ) -> List[PolicyPatch]:
        """Generate policy patches from gate outcomes.

        Currently returns no patches — policy adjustments are left to the
        LEARN phase and agent-driven insights rather than deterministic
        tightening rules.
        """
        return []

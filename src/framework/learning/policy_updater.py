"""Policy updater with versioned, reversible changes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer

from src.framework.contracts import EvaluationResult


class PolicyPatch(BaseModel):
    """Single policy key update with rationale and evidence."""

    key: str
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    evidence: Dict[str, Any] = Field(default_factory=dict)


class PolicyVersion(BaseModel):
    """Snapshot of policy configuration at a version."""

    version: int
    policies: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    source_evidence: Dict[str, Any] = Field(default_factory=dict)
    created_by: str = "policy_updater"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    based_on_version: Optional[int] = None

    @field_serializer("created_at")
    @classmethod
    def _serialize_created_at(cls, value: datetime) -> str:
        return value.isoformat()


class PolicyUpdater:
    """Create and apply policy updates from evaluation outputs."""

    def __init__(self) -> None:
        self._history: List[PolicyVersion] = []

    def propose_patches(
        self,
        evaluation_result: EvaluationResult,
        current_policies: Dict[str, Any],
    ) -> List[PolicyPatch]:
        """Generate policy patches from gate outcomes."""
        patches: Dict[str, PolicyPatch] = {}
        current = dict(current_policies or {})

        for gate in evaluation_result.gates:
            gate_name = gate.gate_name
            gate_status = gate.gate_status
            if gate_status == "pass":
                continue

            if gate_name == "safety":
                max_identical = int(current.get("max_identical_tool_calls", 5))
                self._set_patch(
                    patches=patches,
                    key="max_identical_tool_calls",
                    old_value=max_identical,
                    new_value=max(1, max_identical - 1),
                    reason=f"Tighten loop guard due to safety gate={gate_status}",
                    evidence=gate.evidence,
                )

                loop_window = int(current.get("loop_window_size", 20))
                self._set_patch(
                    patches=patches,
                    key="loop_window_size",
                    old_value=loop_window,
                    new_value=max(5, loop_window - 5),
                    reason=f"Reduce loop window due to safety gate={gate_status}",
                    evidence=gate.evidence,
                )

            if gate_name == "reliability":
                max_children = int(current.get("max_children_per_parent", 10))
                self._set_patch(
                    patches=patches,
                    key="max_children_per_parent",
                    old_value=max_children,
                    new_value=max(1, max_children - 1),
                    reason=f"Reduce delegation fan-out due to reliability gate={gate_status}",
                    evidence=gate.evidence,
                )
                self._set_patch(
                    patches=patches,
                    key="dedupe_delegated_objectives",
                    old_value=bool(current.get("dedupe_delegated_objectives", False)),
                    new_value=True,
                    reason="Enable delegated objective dedupe for reliability recovery",
                    evidence=gate.evidence,
                )

            if gate_name == "efficiency":
                max_total = current.get("max_total_delegated_tasks")
                if max_total is None:
                    new_value = 30
                else:
                    new_value = max(5, int(max_total) - 5)
                self._set_patch(
                    patches=patches,
                    key="max_total_delegated_tasks",
                    old_value=max_total,
                    new_value=new_value,
                    reason=f"Constrain delegated workload due to efficiency gate={gate_status}",
                    evidence=gate.evidence,
                )

        return list(patches.values())

    def apply_patches(
        self,
        current_policies: Dict[str, Any],
        patches: List[PolicyPatch],
        source_evidence: Optional[Dict[str, Any]] = None,
        created_by: str = "policy_updater",
    ) -> PolicyVersion:
        """Apply patches and store a versioned snapshot."""
        base = dict(current_policies or {})
        self._ensure_initial_version(base, created_by=created_by)

        next_policies = deepcopy(base)
        for patch in patches:
            next_policies[patch.key] = patch.new_value

        version = self._history[-1].version + 1
        snapshot = PolicyVersion(
            version=version,
            policies=next_policies,
            reason="applied_patches",
            source_evidence=source_evidence or {},
            created_by=created_by,
            based_on_version=self._history[-1].version,
        )
        self._history.append(snapshot)
        return snapshot

    def rollback_to_version(
        self,
        version: int,
        created_by: str = "policy_updater",
    ) -> Optional[PolicyVersion]:
        """Rollback by creating a new snapshot copied from an older version."""
        target = next((entry for entry in self._history if entry.version == version), None)
        if target is None:
            return None

        new_version = self._history[-1].version + 1
        snapshot = PolicyVersion(
            version=new_version,
            policies=deepcopy(target.policies),
            reason=f"rollback_to_v{version}",
            source_evidence={"rollback_target_version": version},
            created_by=created_by,
            based_on_version=self._history[-1].version,
        )
        self._history.append(snapshot)
        return snapshot

    def history(self) -> List[PolicyVersion]:
        """Return immutable copy of version history."""
        return [entry.model_copy(deep=True) for entry in self._history]

    @staticmethod
    def _set_patch(
        patches: Dict[str, PolicyPatch],
        key: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        evidence: Dict[str, Any],
    ) -> None:
        patches[key] = PolicyPatch(
            key=key,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            evidence=evidence,
        )

    def _ensure_initial_version(self, policies: Dict[str, Any], created_by: str) -> None:
        if self._history:
            return
        self._history.append(
            PolicyVersion(
                version=1,
                policies=deepcopy(policies),
                reason="initial",
                created_by=created_by,
            )
        )


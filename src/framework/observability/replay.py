"""Replay utilities and deterministic trace comparison."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from src.framework.observability.events import ObservabilityEvent


class ReplayResult(BaseModel):
    """Replay output for one run."""

    run_id: str
    event_count: int
    decision_trace: List[Dict[str, Any]] = Field(default_factory=list)
    trace_hash: str = ""


class ReplayDiff(BaseModel):
    """Trace comparison between two runs."""

    left_run_id: str
    right_run_id: str
    left_hash: str
    right_hash: str
    is_equal: bool
    mismatch_indices: List[int] = Field(default_factory=list)
    left_length: int = 0
    right_length: int = 0
    summary: str = ""


class ReplayEngine:
    """Build deterministic traces and compare runs."""

    def __init__(self, event_logger: Any) -> None:
        self._event_logger = event_logger

    def replay_run(self, run_id: str) -> ReplayResult:
        """Extract a deterministic decision trace for a run."""
        events: List[ObservabilityEvent] = self._event_logger.get_events(run_id=run_id)
        ordered = sorted(events, key=lambda e: (e.sequence, e.timestamp_utc))
        trace = _decision_trace(ordered)
        trace_hash = _trace_hash(trace)
        return ReplayResult(
            run_id=run_id,
            event_count=len(ordered),
            decision_trace=trace,
            trace_hash=trace_hash,
        )

    def compare_runs(self, left_run_id: str, right_run_id: str) -> ReplayDiff:
        """Compare two runs via decision-trace hashing + positional diff."""
        left = self.replay_run(left_run_id)
        right = self.replay_run(right_run_id)
        mismatch_indices = _mismatch_indices(left.decision_trace, right.decision_trace)
        is_equal = left.trace_hash == right.trace_hash and not mismatch_indices
        summary = (
            "traces_equal"
            if is_equal
            else (
                f"traces_differ: mismatches={len(mismatch_indices)}, "
                f"left_len={len(left.decision_trace)}, right_len={len(right.decision_trace)}"
            )
        )
        return ReplayDiff(
            left_run_id=left_run_id,
            right_run_id=right_run_id,
            left_hash=left.trace_hash,
            right_hash=right.trace_hash,
            is_equal=is_equal,
            mismatch_indices=mismatch_indices,
            left_length=len(left.decision_trace),
            right_length=len(right.decision_trace),
            summary=summary,
        )


def _decision_trace(events: List[ObservabilityEvent]) -> List[Dict[str, Any]]:
    trace: List[Dict[str, Any]] = []

    included_types = {
        "run_start",
        "run_end",
        "cycle_start",
        "cycle_end",
        "task_started",
        "task_completed",
        "task_failed",
        "tool_result",
        "gate_decision",
        "policy_violation",
        "checkpoint_saved",
        "checkpoint_restored",
    }

    for event in events:
        if event.event_type not in included_types:
            continue
        normalized = {
            "event_type": event.event_type,
            "cycle_id": event.cycle_id,
            "detail": _detail(event.event_type, event.payload),
        }
        trace.append(normalized)
    return trace


def _detail(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if event_type in {"task_started", "task_completed", "task_failed"}:
        return {
            "task_id": payload.get("task_id"),
            "task_status": payload.get("task_status"),
            "error_category": payload.get("error_category"),
        }
    if event_type == "tool_result":
        return {
            "tool_name": payload.get("tool_name"),
            "call_status": payload.get("call_status"),
            "denied_reason": payload.get("denied_reason"),
        }
    if event_type == "gate_decision":
        return {
            "overall_status": payload.get("overall_status"),
            "recommended_action": payload.get("recommended_action"),
        }
    if event_type == "cycle_end":
        return {
            "termination_action": payload.get("termination_action"),
            "termination_reason": payload.get("termination_reason"),
            "evaluation_status": payload.get("evaluation_status"),
        }
    if event_type == "policy_violation":
        return {"reason": payload.get("reason")}
    if event_type in {"checkpoint_saved", "checkpoint_restored"}:
        return {"path": payload.get("checkpoint_path")}
    return {}


def _trace_hash(trace: List[Dict[str, Any]]) -> str:
    encoded = json.dumps(trace, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mismatch_indices(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[int]:
    mismatches: List[int] = []
    max_len = max(len(left), len(right))
    for idx in range(max_len):
        left_item = left[idx] if idx < len(left) else {"_missing": "left"}
        right_item = right[idx] if idx < len(right) else {"_missing": "right"}
        if left_item != right_item:
            mismatches.append(idx)
    return mismatches


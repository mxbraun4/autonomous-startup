"""Helpers for live dashboard snapshots from observability event streams."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.framework.observability.events import ObservabilityEvent


def load_events_from_ndjson(
    events_path: str | Path,
    *,
    max_events: int = 5000,
) -> List[ObservabilityEvent]:
    """Load and parse the newest events from an NDJSON event file.

    Invalid JSON lines are ignored to keep dashboard rendering resilient while
    a producer is concurrently writing to the same file.
    """
    path = Path(events_path)
    if not path.exists() or not path.is_file():
        return []

    tail: deque[str] = deque(maxlen=max(1, int(max_events)))
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                tail.append(line)

    events: List[ObservabilityEvent] = []
    for line in tail:
        try:
            raw = json.loads(line)
            event = ObservabilityEvent.model_validate(raw)
        except Exception:
            continue
        events.append(event)

    events.sort(key=lambda item: (item.sequence, item.timestamp_utc))
    return events


def build_snapshot_from_ndjson(
    events_path: str | Path,
    *,
    run_id: Optional[str] = None,
    max_events: int = 5000,
    recent_limit: int = 60,
) -> Dict[str, Any]:
    """Build a dashboard-ready snapshot directly from an NDJSON file."""
    events = load_events_from_ndjson(events_path, max_events=max_events)
    snapshot = build_run_snapshot(events, run_id=run_id, recent_limit=recent_limit)
    snapshot["events_path"] = str(events_path)
    return snapshot


def build_run_snapshot(
    events: Iterable[ObservabilityEvent],
    *,
    run_id: Optional[str] = None,
    recent_limit: int = 60,
) -> Dict[str, Any]:
    """Build a run snapshot used by the live dashboard UI."""
    ordered = sorted(list(events), key=lambda item: (item.sequence, item.timestamp_utc))
    run_ids = _list_run_ids(ordered)

    if run_id:
        selected_run_id = run_id
        scoped = [event for event in ordered if event.run_id == run_id or event.run_id is None]
    else:
        selected_run_id = run_ids[0] if run_ids else None
        scoped = [
            event for event in ordered
            if selected_run_id is None or event.run_id == selected_run_id or event.run_id is None
        ]

    event_counts = Counter(event.event_type for event in scoped)
    tool_counter: Counter[str] = Counter()
    active_tasks: Dict[str, Dict[str, Any]] = {}
    cycle_rows: Dict[int, Dict[str, Any]] = {}
    last_gate_payload: Dict[str, Any] = {}
    last_cycle_end_payload: Dict[str, Any] = {}
    llm_calls: List[Dict[str, Any]] = []
    agent_exchanges: List[Dict[str, Any]] = []
    run_started_at: Optional[str] = None
    run_ended_at: Optional[str] = None

    for event in scoped:
        payload = event.payload or {}
        cycle_id = _resolve_cycle_id(event)
        if cycle_id is not None:
            row = _cycle_row(cycle_rows, cycle_id)
            row["event_count"] += 1
            if event.event_type == "task_started":
                row["tasks_started"] += 1
            elif event.event_type == "task_completed":
                row["tasks_completed"] += 1
            elif event.event_type == "task_failed":
                row["tasks_failed"] += 1
            elif event.event_type == "tool_called":
                row["tools_called"] += 1
            elif event.event_type == "policy_violation":
                row["policy_violations"] += 1
            elif event.event_type == "cycle_end":
                row["total_tasks"] = _safe_int(payload.get("total_tasks"))
                row["completed_count"] = _safe_int(payload.get("completed_count"))
                row["failed_count"] = _safe_int(payload.get("failed_count"))
                row["skipped_count"] = _safe_int(payload.get("skipped_count"))
                row["evaluation_status"] = str(payload.get("evaluation_status", ""))
                row["evaluation_action"] = str(payload.get("evaluation_action", ""))
                row["termination_action"] = str(payload.get("termination_action", ""))
                row["termination_reason"] = str(payload.get("termination_reason", ""))
                for task_key, task_info in list(active_tasks.items()):
                    if _safe_int(task_info.get("cycle_id")) == cycle_id:
                        active_tasks.pop(task_key, None)

        if event.event_type == "run_start" and run_started_at is None:
            run_started_at = event.timestamp_utc.isoformat()
        elif event.event_type == "run_end":
            run_ended_at = event.timestamp_utc.isoformat()
            active_tasks.clear()

        task_id = _task_id_from_payload(payload)
        if event.event_type == "task_started" and task_id:
            active_tasks[task_id] = {
                "task_id": task_id,
                "cycle_id": cycle_id,
                "agent_role": str(payload.get("agent_role", "")),
                "objective": _truncate(str(payload.get("objective", "")), limit=120),
                "started_at_utc": event.timestamp_utc.isoformat(),
            }
        elif event.event_type in {"task_completed", "task_failed"} and task_id:
            active_tasks.pop(task_id, None)

        if event.event_type == "tool_called":
            tool_name = str(payload.get("tool_name", "")).strip() or "<unknown>"
            tool_counter[tool_name] += 1
        elif event.event_type == "gate_decision":
            last_gate_payload = dict(payload)
        elif event.event_type == "cycle_end":
            last_cycle_end_payload = dict(payload)
        elif event.event_type == "llm_call":
            llm_calls.append({
                "sequence": event.sequence,
                "cycle_id": cycle_id,
                "agent": str(payload.get("agent", "")),
                "model": str(payload.get("model", "")),
                "message_summary": _truncate(str(payload.get("message_summary", "")), limit=150),
                "message_full": str(payload.get("message_summary", "")),
                "response_summary": _truncate(str(payload.get("response_summary", "")), limit=150),
                "response_full": str(payload.get("response_summary", "")),
                "duration_ms": payload.get("duration_ms", 0),
            })
        elif event.event_type == "agent_exchange":
            agent_exchanges.append({
                "sequence": event.sequence,
                "cycle_id": cycle_id,
                "from_agent": str(payload.get("from_agent", "")),
                "exchange_type": str(payload.get("exchange_type", "")),
                "key": str(payload.get("key", payload.get("topic", ""))),
                "value_summary": _truncate(
                    str(payload.get("value_summary", payload.get("count", ""))),
                    limit=150,
                ),
                "value_full": str(payload.get("value_summary", payload.get("count", ""))),
            })

    cycle_summaries = [cycle_rows[key] for key in sorted(cycle_rows)]
    top_tools = [
        {"tool_name": tool_name, "count": count}
        for tool_name, count in tool_counter.most_common(10)
    ]
    latest_gate = _normalize_gate_payload(last_gate_payload)

    run_status = _derive_run_status(
        run_ended=event_counts.get("run_end", 0) > 0,
        final_action=str(last_cycle_end_payload.get("termination_action", "")),
        final_reason=str(last_cycle_end_payload.get("termination_reason", "")),
    )

    recent_rows = [
        {
            "sequence": event.sequence,
            "timestamp_utc": event.timestamp_utc.isoformat(),
            "event_type": event.event_type,
            "cycle_id": _resolve_cycle_id(event),
            "summary": _event_summary(event),
        }
        for event in reversed(scoped[-max(1, int(recent_limit)) :])
    ]

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "available_run_ids": run_ids,
        "selected_run_id": selected_run_id,
        "source_event_count": len(ordered),
        "run_event_count": len(scoped),
        "event_counts": dict(sorted(event_counts.items())),
        "run": {
            "status": run_status,
            "started": event_counts.get("run_start", 0) > 0,
            "ended": event_counts.get("run_end", 0) > 0,
            "started_at_utc": run_started_at,
            "ended_at_utc": run_ended_at,
            "final_action": str(last_cycle_end_payload.get("termination_action", "")),
            "final_reason": str(last_cycle_end_payload.get("termination_reason", "")),
            "evaluation_status": str(
                last_cycle_end_payload.get("evaluation_status", latest_gate.get("overall_status", ""))
            ),
            "evaluation_action": str(
                last_cycle_end_payload.get(
                    "evaluation_action",
                    latest_gate.get("recommended_action", ""),
                )
            ),
            "last_checkpoint_path": str(last_cycle_end_payload.get("checkpoint_path", "")),
        },
        "tasks": {
            "started": event_counts.get("task_started", 0),
            "completed": event_counts.get("task_completed", 0),
            "failed": event_counts.get("task_failed", 0),
            "in_progress": len(active_tasks),
        },
        "tools": {
            "called": event_counts.get("tool_called", 0),
            "denied": event_counts.get("tool_denied", 0),
            "errors": event_counts.get("tool_error", 0),
            "results": event_counts.get("tool_result", 0),
            "top_called": top_tools,
        },
        "policy_violations": event_counts.get("policy_violation", 0),
        "cycle_count": len(cycle_summaries),
        "cycles": cycle_summaries,
        "active_tasks": list(active_tasks.values()),
        "latest_gate": latest_gate,
        "llm_calls": list(reversed(llm_calls[-50:])),
        "agent_exchanges": list(reversed(agent_exchanges[-50:])),
        "recent_events": recent_rows,
    }


def _list_run_ids(events: Iterable[ObservabilityEvent]) -> List[str]:
    latest_sequence: Dict[str, int] = {}
    for event in events:
        if not event.run_id:
            continue
        previous = latest_sequence.get(event.run_id)
        if previous is None or event.sequence > previous:
            latest_sequence[event.run_id] = event.sequence
    return [
        run_id
        for run_id, _ in sorted(
            latest_sequence.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_cycle_id(event: ObservabilityEvent) -> Optional[int]:
    if event.cycle_id is not None:
        return int(event.cycle_id)

    payload_cycle = event.payload.get("cycle_id")
    if payload_cycle is None:
        return None
    return _safe_int(payload_cycle)


def _task_id_from_payload(payload: Dict[str, Any]) -> str:
    task_id = payload.get("task_id")
    if task_id is None:
        return ""
    return str(task_id).strip()


def _cycle_row(rows: Dict[int, Dict[str, Any]], cycle_id: int) -> Dict[str, Any]:
    if cycle_id not in rows:
        rows[cycle_id] = {
            "cycle_id": cycle_id,
            "event_count": 0,
            "tasks_started": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tools_called": 0,
            "policy_violations": 0,
            "total_tasks": None,
            "completed_count": None,
            "failed_count": None,
            "skipped_count": None,
            "evaluation_status": "",
            "evaluation_action": "",
            "termination_action": "",
            "termination_reason": "",
        }
    return rows[cycle_id]


def _normalize_gate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload:
        return {"overall_status": "", "recommended_action": "", "summary": "", "gates": []}

    gate_rows: List[Dict[str, str]] = []
    for gate in payload.get("gates", []):
        if not isinstance(gate, dict):
            continue
        gate_rows.append(
            {
                "gate_name": str(gate.get("gate_name", "")),
                "gate_status": str(gate.get("gate_status", "")),
                "recommended_action": str(gate.get("recommended_action", "")),
            }
        )

    return {
        "overall_status": str(payload.get("overall_status", "")),
        "recommended_action": str(payload.get("recommended_action", "")),
        "summary": str(payload.get("summary", "")),
        "gates": gate_rows,
    }


def _derive_run_status(*, run_ended: bool, final_action: str, final_reason: str) -> str:
    if not run_ended:
        return "running"
    if final_action == "pause":
        return "paused"
    if final_action == "stop":
        if final_reason == "max_cycles_reached":
            return "completed"
        return "stopped"
    return "completed"


def _truncate(text: str, *, limit: int = 120) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _event_summary(event: ObservabilityEvent) -> str:
    payload = event.payload or {}
    event_type = event.event_type

    if event_type.startswith("task_"):
        task_id = _task_id_from_payload(payload)
        objective = str(payload.get("objective", ""))
        status = str(payload.get("task_status", ""))
        text = f"{task_id} {objective} {status}".strip()
        return _truncate(" ".join(text.split()), limit=140)

    if event_type.startswith("tool_"):
        tool_name = str(payload.get("tool_name", "")).strip()
        capability = str(payload.get("capability", "")).strip()
        denied = str(payload.get("denied_reason", "")).strip()
        err = str(payload.get("error_message", "")).strip()
        text = " ".join(part for part in [tool_name, capability, denied, err] if part)
        return _truncate(text, limit=140)

    if event_type == "cycle_end":
        text = (
            f"eval={payload.get('evaluation_status', '')} "
            f"action={payload.get('termination_action', '')} "
            f"reason={payload.get('termination_reason', '')}"
        )
        return _truncate(" ".join(text.split()), limit=140)

    if event_type == "policy_violation":
        return _truncate(str(payload.get("reason", "policy violation")), limit=140)

    if event_type in {"run_start", "run_end", "cycle_start"}:
        text = " ".join(
            [
                str(payload.get("run_id", "")),
                str(payload.get("cycle_id", "")),
            ]
        ).strip()
        return _truncate(text, limit=140)

    if event_type == "llm_call":
        agent = str(payload.get("agent", "")).strip()
        model = str(payload.get("model", "")).strip()
        dur = payload.get("duration_ms", "")
        text = f"{agent} model={model} {dur}ms"
        return _truncate(" ".join(text.split()), limit=140)

    if event_type == "agent_exchange":
        from_agent = str(payload.get("from_agent", "")).strip()
        ex_type = str(payload.get("exchange_type", "")).strip()
        key = str(payload.get("key", payload.get("topic", ""))).strip()
        text = f"{from_agent} {ex_type} {key}"
        return _truncate(" ".join(text.split()), limit=140)

    return ""

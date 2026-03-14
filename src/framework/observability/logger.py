"""Structured event logger for framework observability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.framework.observability.events import ObservabilityEvent, create_event


def _to_payload_dict(payload: Any) -> Dict[str, Any]:
    """Normalize payload into a JSON-serializable dictionary."""
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(payload, "model_dump"):
        try:
            return payload.model_dump(mode="json")
        except Exception:
            return payload.model_dump()
    if hasattr(payload, "__dict__"):
        try:
            return dict(payload.__dict__)
        except Exception:
            pass
    return {"value": str(payload)}


def _extract_run_id(payload: Any, payload_dict: Dict[str, Any]) -> Optional[str]:
    if "run_id" in payload_dict and payload_dict["run_id"] is not None:
        return str(payload_dict["run_id"])
    if hasattr(payload, "run_id"):
        value = getattr(payload, "run_id")
        if value is not None:
            return str(value)
    return None


def _extract_cycle_id(payload: Any, payload_dict: Dict[str, Any]) -> Optional[int]:
    if "cycle_id" in payload_dict and payload_dict["cycle_id"] is not None:
        try:
            return int(payload_dict["cycle_id"])
        except (TypeError, ValueError):
            return None
    if hasattr(payload, "cycle_id"):
        value = getattr(payload, "cycle_id")
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


class EventLogger:
    """In-memory + optional NDJSON event logger with emit() interface."""

    def __init__(
        self,
        persist_path: Optional[str] = None,
        max_events: int = 100_000,
    ) -> None:
        self._events: List[ObservabilityEvent] = []
        self._sequence = 0
        self._max_events = max_events
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path is not None:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: Any) -> None:
        """Record a structured event."""
        payload_dict = _to_payload_dict(payload)
        run_id = _extract_run_id(payload, payload_dict)
        cycle_id = _extract_cycle_id(payload, payload_dict)

        self._sequence += 1
        event = create_event(
            sequence=self._sequence,
            event_type=event_type,
            run_id=run_id,
            cycle_id=cycle_id,
            payload=payload_dict,
        )
        self._append(event)

        # Derive policy_violation from tool_denied events.
        if event_type == "tool_denied":
            denied_reason = str(payload_dict.get("denied_reason", "")).lower()
            if denied_reason:
                self._sequence += 1
                derived = create_event(
                    sequence=self._sequence,
                    event_type="policy_violation",
                    run_id=run_id,
                    cycle_id=cycle_id,
                    payload={"reason": payload_dict.get("denied_reason", "")},
                    metadata={"derived_from": "tool_denied"},
                )
                self._append(derived)

    def get_events(
        self,
        *,
        run_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[ObservabilityEvent]:
        """Return events filtered by run and/or type."""
        events = self._events
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        if event_type is not None:
            events = [event for event in events if event.event_type == event_type]
        return list(events)

    def clear(self) -> None:
        self._events.clear()
        self._sequence = 0

    @property
    def size(self) -> int:
        return len(self._events)

    def _append(self, event: ObservabilityEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

        if self._persist_path is not None:
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=True))
                f.write("\n")


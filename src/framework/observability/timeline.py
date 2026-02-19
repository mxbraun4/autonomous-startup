"""Timeline builder for run event inspection."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.observability.events import ObservabilityEvent


class Timeline(BaseModel):
    """Structured timeline representation for one run."""

    run_id: str
    total_events: int = 0
    event_counts: Dict[str, int] = Field(default_factory=dict)
    cycles: Dict[int, List[ObservabilityEvent]] = Field(default_factory=dict)
    unscoped_events: List[ObservabilityEvent] = Field(default_factory=list)


class TimelineBuilder:
    """Convert event streams into cycle-oriented timeline views."""

    @staticmethod
    def build(
        events: List[ObservabilityEvent],
        *,
        run_id: Optional[str] = None,
    ) -> Timeline:
        filtered = [
            event for event in events if run_id is None or event.run_id == run_id
        ]
        ordered = sorted(filtered, key=lambda e: (e.sequence, e.timestamp_utc))

        resolved_run_id = run_id or (ordered[0].run_id if ordered else "")
        timeline = Timeline(run_id=resolved_run_id, total_events=len(ordered))

        for event in ordered:
            timeline.event_counts[event.event_type] = (
                timeline.event_counts.get(event.event_type, 0) + 1
            )
            if event.cycle_id is None:
                timeline.unscoped_events.append(event)
            else:
                timeline.cycles.setdefault(event.cycle_id, []).append(event)

        return timeline


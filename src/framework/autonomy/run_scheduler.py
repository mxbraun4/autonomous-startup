"""Autonomous run scheduler with trigger predicates and global lock."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class SchedulerTriggerEvaluation(BaseModel):
    """One trigger evaluation outcome."""

    trigger: str
    schedule_index: int
    fired: bool = False
    reason: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)


class SchedulerRunResult(BaseModel):
    """Outcome of a single scheduler evaluation/dispatch pass."""

    triggered: bool = False
    dispatched: bool = False
    dispatch_mode: str = "none"  # none | run | resume | locked
    reason: str = ""
    evaluations: List[SchedulerTriggerEvaluation] = Field(default_factory=list)
    run_result: Optional[Dict[str, Any]] = None


class RunScheduler:
    """Evaluate configured triggers and dispatch autonomous runs."""

    def __init__(
        self,
        *,
        run_controller: Any,
        schedules: Optional[List[Dict[str, Any]]] = None,
        evaluation_interval_seconds: float = 1800.0,
        lock_path: str = "data/memory/run_scheduler.lock",
        stale_lock_seconds: float = 6 * 3600,
        event_emitter: Any = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        data_ingestion_fn: Optional[Callable[[Dict[str, Any]], int]] = None,
        metric_value_fn: Optional[Callable[..., Optional[float]]] = None,
        event_trigger_fn: Optional[Callable[..., bool]] = None,
        resume_checkpoint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._run_controller = run_controller
        self._schedules = list(schedules or [])
        self._evaluation_interval_seconds = max(1.0, float(evaluation_interval_seconds))
        self._lock_path = Path(lock_path)
        self._stale_lock_seconds = max(1.0, float(stale_lock_seconds))
        self._event_emitter = event_emitter
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._sleep_fn = sleep_fn
        self._data_ingestion_fn = data_ingestion_fn
        self._metric_value_fn = metric_value_fn
        self._event_trigger_fn = event_trigger_fn
        self._resume_checkpoint_fn = resume_checkpoint_fn
        self._last_cron_markers: Dict[str, str] = {}
        self._lock_held = False

    def evaluate_triggers(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> List[SchedulerTriggerEvaluation]:
        """Evaluate all schedules and return trigger decisions."""
        current = now or self._normalize_now(self._now_fn())
        evaluations: List[SchedulerTriggerEvaluation] = []
        for idx, schedule in enumerate(self._schedules):
            evaluations.append(self._evaluate_schedule(idx, schedule, current))
        return evaluations

    def run_once(self) -> SchedulerRunResult:
        """Run one scheduler iteration: evaluate triggers and dispatch."""
        now = self._normalize_now(self._now_fn())
        evaluations = self.evaluate_triggers(now=now)
        triggered = any(entry.fired for entry in evaluations)
        self._emit(
            "scheduler.evaluated",
            {
                "timestamp_utc": now.isoformat(),
                "triggered": triggered,
                "evaluations": [entry.model_dump(mode="json") for entry in evaluations],
            },
        )

        if not triggered:
            return SchedulerRunResult(
                triggered=False,
                dispatched=False,
                dispatch_mode="none",
                reason="no_trigger_fired",
                evaluations=evaluations,
            )

        if not self._acquire_lock():
            result = SchedulerRunResult(
                triggered=True,
                dispatched=False,
                dispatch_mode="locked",
                reason="concurrency_lock_active",
                evaluations=evaluations,
            )
            self._emit("scheduler.skipped_locked", result.model_dump(mode="json"))
            return result

        try:
            checkpoint_path = self._resolve_resume_checkpoint()
            mode = "run"
            if checkpoint_path:
                mode = "resume"
                run_result = self._run_controller.resume(checkpoint_path)
            else:
                run_result = self._run_controller.run()

            payload = (
                run_result.model_dump(mode="json")
                if hasattr(run_result, "model_dump")
                else {"value": str(run_result)}
            )
            result = SchedulerRunResult(
                triggered=True,
                dispatched=True,
                dispatch_mode=mode,
                reason="dispatched",
                evaluations=evaluations,
                run_result=payload,
            )
            self._emit("scheduler.run_dispatched", result.model_dump(mode="json"))
            return result
        finally:
            self._release_lock()

    def serve_forever(self, *, max_loops: Optional[int] = None) -> int:
        """Run continuous scheduler loop; returns executed iteration count."""
        loops = 0
        while max_loops is None or loops < max_loops:
            self.run_once()
            loops += 1
            self._sleep_fn(self._evaluation_interval_seconds)
        return loops

    def _evaluate_schedule(
        self,
        index: int,
        schedule: Dict[str, Any],
        now: datetime,
    ) -> SchedulerTriggerEvaluation:
        trigger = str(schedule.get("trigger", "")).strip().lower()
        if trigger == "cron":
            expression = str(schedule.get("expression", "* * * * *"))
            if not _cron_matches(expression, now):
                return SchedulerTriggerEvaluation(
                    trigger="cron",
                    schedule_index=index,
                    fired=False,
                    reason="cron_not_matched",
                    details={"expression": expression},
                )
            minute_marker = now.strftime("%Y%m%d%H%M")
            marker_key = f"{index}:{expression}"
            if self._last_cron_markers.get(marker_key) == minute_marker:
                return SchedulerTriggerEvaluation(
                    trigger="cron",
                    schedule_index=index,
                    fired=False,
                    reason="cron_already_fired_this_minute",
                    details={"expression": expression},
                )
            self._last_cron_markers[marker_key] = minute_marker
            return SchedulerTriggerEvaluation(
                trigger="cron",
                schedule_index=index,
                fired=True,
                reason="cron_matched",
                details={"expression": expression},
            )

        if trigger == "data_ingestion":
            if self._data_ingestion_fn is None:
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason="missing_data_ingestion_fn",
                )
            try:
                new_records = int(self._data_ingestion_fn(schedule))
            except Exception as exc:
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason=f"data_ingestion_error:{exc}",
                )
            threshold = _safe_int(schedule.get("min_new_records"), 1)
            fired = new_records >= threshold
            return SchedulerTriggerEvaluation(
                trigger=trigger,
                schedule_index=index,
                fired=fired,
                reason="threshold_met" if fired else "threshold_not_met",
                details={
                    "new_records": new_records,
                    "min_new_records": threshold,
                },
            )

        if trigger == "metric_drop":
            metric = str(schedule.get("metric", "")).strip()
            threshold_raw = schedule.get("threshold")
            if self._metric_value_fn is None or not metric or threshold_raw is None:
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason="missing_metric_config_or_callback",
                    details={"metric": metric},
                )
            try:
                threshold = float(threshold_raw)
            except (TypeError, ValueError):
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason="invalid_metric_threshold",
                    details={"metric": metric, "threshold": threshold_raw},
                )
            current = self._resolve_metric_value(metric, schedule)
            if current is None:
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason="metric_unavailable",
                    details={"metric": metric},
                )
            fired = float(current) <= threshold
            return SchedulerTriggerEvaluation(
                trigger=trigger,
                schedule_index=index,
                fired=fired,
                reason="metric_below_threshold" if fired else "metric_above_threshold",
                details={
                    "metric": metric,
                    "value": float(current),
                    "threshold": threshold,
                },
            )

        if trigger == "event":
            if self._event_trigger_fn is None:
                return SchedulerTriggerEvaluation(
                    trigger=trigger,
                    schedule_index=index,
                    fired=False,
                    reason="missing_event_trigger_fn",
                )
            event_name = str(schedule.get("event_name", "")).strip()
            fired = self._resolve_event_trigger(event_name, schedule)
            return SchedulerTriggerEvaluation(
                trigger=trigger,
                schedule_index=index,
                fired=bool(fired),
                reason="event_fired" if fired else "event_not_fired",
                details={"event_name": event_name},
            )

        return SchedulerTriggerEvaluation(
            trigger=trigger or "unknown",
            schedule_index=index,
            fired=False,
            reason="unsupported_trigger",
            details={"schedule": schedule},
        )

    def _resolve_metric_value(
        self,
        metric: str,
        schedule: Dict[str, Any],
    ) -> Optional[float]:
        fn = self._metric_value_fn
        if fn is None:
            return None
        try:
            value = fn(metric, schedule)
        except TypeError:
            try:
                value = fn(metric)
            except Exception:
                return None
        except Exception:
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _resolve_event_trigger(self, event_name: str, schedule: Dict[str, Any]) -> bool:
        fn = self._event_trigger_fn
        if fn is None:
            return False
        try:
            return bool(fn(event_name, schedule))
        except TypeError:
            try:
                return bool(fn(schedule))
            except TypeError:
                try:
                    return bool(fn(event_name))
                except Exception:
                    return False
            except Exception:
                return False
        except Exception:
            return False

    def _resolve_resume_checkpoint(self) -> Optional[str]:
        if self._resume_checkpoint_fn is None:
            return None
        try:
            value = self._resume_checkpoint_fn()
        except Exception:
            return None
        if value is None:
            return None
        checkpoint = str(value).strip()
        return checkpoint or None

    def _acquire_lock(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        if self._lock_path.exists():
            try:
                age = time.time() - self._lock_path.stat().st_mtime
                if age >= self._stale_lock_seconds:
                    self._lock_path.unlink(missing_ok=True)
            except Exception:
                return False

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self._lock_path), flags)
        except FileExistsError:
            return False
        except Exception:
            return False

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    f"pid={os.getpid()} created_utc={datetime.now(timezone.utc).isoformat()}\n"
                )
            self._lock_held = True
            return True
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            self._lock_path.unlink(missing_ok=True)
            return False

    def _release_lock(self) -> None:
        if not self._lock_held:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._lock_held = False

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter.emit(event_type, payload)
        except Exception:
            pass

    @staticmethod
    def _normalize_now(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _cron_matches(expression: str, now: datetime) -> bool:
    parts = expression.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, weekday = parts
    cron_weekday = (now.weekday() + 1) % 7  # python Mon=0 -> cron Mon=1, Sun=0
    return (
        _field_matches(now.minute, minute, 0, 59)
        and _field_matches(now.hour, hour, 0, 23)
        and _field_matches(now.day, day, 1, 31)
        and _field_matches(now.month, month, 1, 12)
        and _field_matches(cron_weekday, weekday, 0, 7)
    )


def _field_matches(value: int, expr: str, minimum: int, maximum: int) -> bool:
    for token in expr.split(","):
        item = token.strip()
        if not item:
            continue
        if item == "*":
            return True
        if item.startswith("*/"):
            step = _safe_int(item[2:], 0)
            if step <= 0:
                continue
            if value % step == 0:
                return True
            continue
        if "-" in item:
            start_raw, end_raw = item.split("-", 1)
            start = _safe_int(start_raw, minimum)
            end = _safe_int(end_raw, maximum)
            if start > end:
                start, end = end, start
            if start <= value <= end:
                return True
            continue
        number = _safe_int(item, minimum - 1)
        if number == 7 and maximum == 7:
            number = 0
        if minimum <= number <= maximum and number == value:
            return True
    return False

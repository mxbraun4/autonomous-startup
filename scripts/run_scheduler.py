"""Run long-lived autonomous scheduler for web-product framework runs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import re
from typing import Dict, List, Optional

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path(__file__)

from src.framework.autonomy import RunScheduler
from src.framework.observability import EventLogger
from src.framework.runtime.web_edit_templates import list_edit_templates
from src.utils.config import settings
from src.utils.logging import get_logger, setup_logging

try:
    from scripts.run_web_autonomy import (
        build_web_arg_parser,
        create_web_run_controller,
    )
except ImportError:
    from run_web_autonomy import build_web_arg_parser, create_web_run_controller

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parent = build_web_arg_parser(add_help=False)
    parser = argparse.ArgumentParser(
        description="Run long-lived autonomous scheduler for web autonomy runs",
        parents=[parent],
        add_help=True,
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=1800.0)
    parser.add_argument("--max-loops", type=int, default=None)
    parser.add_argument("--lock-path", default="data/memory/run_scheduler.lock")
    parser.add_argument("--stale-lock-seconds", type=float, default=21600.0)
    parser.add_argument("--cron", action="append", default=[])
    parser.add_argument("--metric-drop", action="append", default=[])
    parser.add_argument("--data-trigger-min-new-records", type=int, default=0)
    parser.add_argument("--event-flag-file", default="")
    parser.add_argument("--resume-checkpoint-file", default="")
    parser.add_argument(
        "--resume-latest-checkpoint",
        dest="resume_latest_checkpoint",
        action="store_true",
    )
    parser.add_argument(
        "--no-resume-latest-checkpoint",
        dest="resume_latest_checkpoint",
        action="store_false",
    )
    parser.set_defaults(resume_latest_checkpoint=True)
    return parser


def _print_edit_templates(template_file: str) -> None:
    rows = list_edit_templates(template_file or None)
    if not rows:
        print("No edit templates available.")
        return
    print("Available edit templates:")
    for row in rows:
        print(f"  - {row['name']}: {row['description']} [path={row['path']}]")


def _build_schedules(args: argparse.Namespace) -> List[Dict[str, object]]:
    schedules: List[Dict[str, object]] = []

    schedules_file = str(getattr(args, "schedules_file", "") or "").strip()
    if schedules_file:
        schedules.extend(_load_schedules_file(Path(schedules_file)))

    for raw in args.schedule_json or []:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Each --schedule-json value must decode to an object")
        schedules.append(parsed)

    for expression in args.cron or []:
        schedules.append({"trigger": "cron", "expression": str(expression)})

    for raw in args.metric_drop or []:
        metric, threshold = _parse_metric_drop(raw)
        schedules.append(
            {
                "trigger": "metric_drop",
                "metric": metric,
                "threshold": threshold,
            }
        )

    min_new_records = int(args.data_trigger_min_new_records or 0)
    if min_new_records > 0:
        schedules.append(
            {
                "trigger": "data_ingestion",
                "min_new_records": min_new_records,
            }
        )

    if args.event_flag_file:
        schedules.append(
            {
                "trigger": "event",
                "event_name": "flag_file",
                "flag_file": str(args.event_flag_file),
                "consume": True,
            }
        )

    if not schedules:
        schedules.append({"trigger": "cron", "expression": "*/30 * * * *"})

    return schedules


def _load_schedules_file(path: Path) -> list[dict]:
    if not path.exists():
        raise ValueError(f"Schedules file not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Schedules file is not valid JSON: {path}") from exc

    if isinstance(parsed, list):
        raw_items = parsed
    elif isinstance(parsed, dict):
        raw_items = parsed.get("schedules")
    else:
        raise ValueError(f"Schedules file must be a list or object with 'schedules': {path}")

    if not isinstance(raw_items, list):
        raise ValueError(f"Schedules file missing list 'schedules': {path}")

    schedules: list[dict] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid schedule entry in {path}: {entry!r}")
        schedules.append(dict(entry))
    return schedules


def _parse_metric_drop(value: str) -> tuple[str, float]:
    raw = str(value or "").strip()
    if ":" not in raw:
        raise ValueError(f"Invalid --metric-drop value '{value}'. Expected metric:threshold")
    metric, threshold = raw.split(":", 1)
    metric = metric.strip()
    if not metric:
        raise ValueError(f"Invalid --metric-drop value '{value}'. Metric cannot be empty")
    try:
        threshold_value = float(threshold.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid --metric-drop value '{value}'. Threshold must be numeric"
        ) from exc
    return metric, threshold_value


class _WebRunControllerFactory:
    """Build a fresh web run controller for each scheduler dispatch."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args

    def run(self):  # noqa: ANN201
        controller, _events, run_id, template_name = create_web_run_controller(self._args)
        if template_name:
            logger.info("Using edit template: %s", template_name)
        logger.info("Scheduler dispatch run_id=%s mode=run", run_id)
        return controller.run()

    def resume(self, checkpoint_path: str):  # noqa: ANN201
        args = argparse.Namespace(**vars(self._args))
        checkpoint_run_id = _checkpoint_run_id(Path(checkpoint_path))
        if checkpoint_run_id:
            args.run_id = checkpoint_run_id
        controller, _events, run_id, template_name = create_web_run_controller(args)
        if template_name:
            logger.info("Using edit template: %s", template_name)
        logger.info(
            "Scheduler dispatch run_id=%s mode=resume checkpoint=%s",
            run_id,
            checkpoint_path,
        )
        return controller.resume(checkpoint_path)


def _make_data_ingestion_counter() -> callable:
    db_path = Path(settings.startup_db_path).resolve()
    last_count: Optional[int] = None

    def _count(_schedule: Dict[str, object]) -> int:
        nonlocal last_count
        current = _startup_count(db_path)
        if last_count is None:
            last_count = current
            return 0
        delta = max(0, current - last_count)
        last_count = current
        return delta

    return _count


def _startup_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM startups")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _make_metric_reader(events_path: Path) -> callable:
    def _read(metric: str, _schedule: Dict[str, object]) -> Optional[float]:
        if not events_path.exists():
            return None
        latest: Optional[float] = None
        try:
            with events_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("event_type") != "gate_decision":
                        continue
                    payload = entry.get("payload") or {}
                    metadata = payload.get("metadata") or {}
                    scorecard = metadata.get("scorecard") or {}
                    value = scorecard.get(metric)
                    if value is None:
                        value = payload.get(metric)
                    try:
                        latest = float(value)
                    except (TypeError, ValueError):
                        continue
        except Exception:
            return None
        return latest

    return _read


def _event_flag_trigger(_event_name: str, schedule: Dict[str, object]) -> bool:
    marker = str(schedule.get("flag_file") or "").strip()
    if not marker:
        return False
    path = Path(marker)
    if not path.exists():
        return False
    consume = bool(schedule.get("consume", True))
    if consume:
        try:
            path.unlink()
        except Exception:
            pass
    return True


def _build_resume_checkpoint_reader(
    resume_checkpoint_file: str,
    *,
    checkpoint_dir: str,
    resume_latest_checkpoint: bool,
) -> callable:
    path = Path(str(resume_checkpoint_file or "").strip()) if resume_checkpoint_file else None
    latest_returned: Optional[str] = None

    def _read() -> Optional[str]:
        nonlocal latest_returned
        if path is None:
            candidate = None
        elif path.exists():
            # Accept either a checkpoint path file or a file containing the path.
            if path.suffix.lower() == ".json":
                candidate = str(path)
            else:
                try:
                    candidate = path.read_text(encoding="utf-8").strip()
                except Exception:
                    candidate = None
        else:
            candidate = None

        if not candidate and resume_latest_checkpoint:
            candidate = _latest_checkpoint_path(Path(checkpoint_dir))

        if not candidate:
            return None

        resolved = str(Path(candidate).resolve())
        if resolved == latest_returned:
            return None
        latest_returned = resolved
        return resolved

    return _read


def _latest_checkpoint_path(checkpoint_dir: Path) -> Optional[str]:
    if not checkpoint_dir.exists():
        return None
    candidates = []
    for path in checkpoint_dir.glob("*.json"):
        name = path.name.lower()
        if name.endswith(".wm.json"):
            continue
        if re.search(r"_cycle_\d+_step_\d+\.json$", path.name):
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            _checkpoint_cycle_step(item)[0],
            _checkpoint_cycle_step(item)[1],
            item.stat().st_mtime,
            item.name,
        ),
        reverse=True,
    )
    return str(candidates[0].resolve())


def _checkpoint_run_id(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    run_id = data.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return None


def _checkpoint_cycle_step(path: Path) -> tuple[int, int]:
    match = re.search(r"_cycle_(\d+)_step_(\d+)\.json$", path.name)
    if not match:
        return (0, 0)
    try:
        cycle = int(match.group(1))
    except ValueError:
        cycle = 0
    try:
        step = int(match.group(2))
    except ValueError:
        step = 0
    return (cycle, step)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_edit_templates:
        _print_edit_templates(args.edit_template_file)
        return

    setup_logging(args.log_level)
    schedules = _build_schedules(args)
    args.run_schedules = [dict(item) for item in schedules]

    events_path = Path(args.events_path).resolve()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    scheduler_events = EventLogger(persist_path=str(events_path))

    run_controller = _WebRunControllerFactory(args)
    scheduler = RunScheduler(
        run_controller=run_controller,
        schedules=schedules,
        evaluation_interval_seconds=float(args.interval_seconds),
        lock_path=str(Path(args.lock_path).resolve()),
        stale_lock_seconds=float(args.stale_lock_seconds),
        event_emitter=scheduler_events,
        data_ingestion_fn=_make_data_ingestion_counter(),
        metric_value_fn=_make_metric_reader(events_path),
        event_trigger_fn=_event_flag_trigger,
        resume_checkpoint_fn=_build_resume_checkpoint_reader(
            args.resume_checkpoint_file,
            checkpoint_dir=str(args.checkpoint_dir),
            resume_latest_checkpoint=bool(args.resume_latest_checkpoint),
        ),
    )

    print("\n" + "=" * 60)
    print("WEB AUTONOMY SCHEDULER")
    print("=" * 60)
    print(f"Interval seconds: {float(args.interval_seconds):.1f}")
    print(f"Lock path: {Path(args.lock_path).resolve()}")
    print(f"Checkpoint dir: {Path(args.checkpoint_dir).resolve()}")
    print(f"Resume latest checkpoint: {bool(args.resume_latest_checkpoint)}")
    print(f"Schedules configured: {len(schedules)}")
    for idx, schedule in enumerate(schedules, 1):
        print(f"  {idx}. {schedule}")
    print("=" * 60 + "\n")

    if args.once:
        result = scheduler.run_once()
        print("Scheduler run_once result:")
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    loops = scheduler.serve_forever(max_loops=args.max_loops)
    print(f"Scheduler stopped after {loops} loop(s).")


if __name__ == "__main__":
    main()

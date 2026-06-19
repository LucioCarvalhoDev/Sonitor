import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from app import settings
from app.collectors import CollectorRepository, Metric, MetricResult, Snapshot
from app.execution import get_executor
from app.routines import store
from app.routines.model import Routine

# Splits a log into iteration blocks: each block starts with a "--- ... ---" header.
_BLOCK_SPLIT = re.compile(r"(?m)^(?=--- )")
_ITERATION_RE = re.compile(r"Iteration (\d+)")


def log_paths(routine: Routine) -> List[Path]:
    """The files this routine logs to, taken from ``[log].log_to`` in the .sonitor.

    Routines written before ``log_to`` existed have an empty list; for those we
    fall back to the historical implicit path so old files keep working.
    """
    if routine.log_to:
        paths = [Path(p) for p in routine.log_to]
    else:
        paths = [settings.LOGS_DIR / f"{routine.uuid}.log"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    return paths


def _read_blocks(path: Path) -> List[str]:
    if not path.exists():
        return []
    content = path.read_text()
    return [block.strip() for block in _BLOCK_SPLIT.split(content) if block.strip()]


def _next_iteration(blocks: List[str]) -> int:
    iterations = [int(m.group(1)) for block in blocks for m in [_ITERATION_RE.search(block)] if m]
    return (max(iterations) + 1) if iterations else 1


def build_metrics(routine: Routine) -> List[Metric]:
    metrics: List[Metric] = []
    for spec in routine.metrics:
        metric_cls = CollectorRepository.resolve(spec["name"])
        metrics.append(metric_cls(spec.get("args", [])))
    return metrics


def run_once(routine: Routine) -> List[Path]:
    """Run every metric once, then append a Snapshot block to each log file.

    Each target file is rotated independently, so a file's iteration counter
    reflects only its own history.
    """
    metrics = build_metrics(routine)
    executor = get_executor(routine.target)
    results: List[MetricResult] = [executor.collect(metric) for metric in metrics]

    paths = log_paths(routine)
    for path in paths:
        blocks = _read_blocks(path)
        iteration = _next_iteration(blocks)
        blocks.append(Snapshot(results, iteration).as_text())

        if routine.log_max_lines > 0:
            blocks = blocks[-routine.log_max_lines:]
        path.write_text("\n\n".join(blocks) + "\n")

    routine.last_run_at = datetime.now(timezone.utc)
    store.save(routine)
    return paths


def reset(routine: Routine) -> None:
    """Clear every log file the routine writes to."""
    for path in log_paths(routine):
        if path.exists():
            path.write_text("")

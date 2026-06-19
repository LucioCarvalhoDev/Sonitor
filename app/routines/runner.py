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


def log_path(routine: Routine) -> Path:
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return settings.LOGS_DIR / f"{routine.uuid}.log"


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


def run_once(routine: Routine) -> Path:
    """Run every metric of the routine once, append a Snapshot block, rotate, persist."""
    metrics = build_metrics(routine)
    executor = get_executor(routine.target)
    results: List[MetricResult] = [executor.collect(metric) for metric in metrics]

    path = log_path(routine)
    blocks = _read_blocks(path)
    iteration = _next_iteration(blocks)
    blocks.append(Snapshot(results, iteration).as_text())

    if routine.log_max_lines > 0:
        blocks = blocks[-routine.log_max_lines:]
    path.write_text("\n\n".join(blocks) + "\n")

    routine.last_run_at = datetime.now(timezone.utc)
    store.save(routine)
    return path


def reset(routine: Routine) -> None:
    """Clear the routine's log file."""
    path = log_path(routine)
    if path.exists():
        path.write_text("")

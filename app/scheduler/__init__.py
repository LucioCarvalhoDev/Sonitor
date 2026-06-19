from typing import Dict, Type

from app import settings
from app.scheduler.base import Scheduler
from app.scheduler.cron import CronScheduler
from app.scheduler.inproc import InprocScheduler

SCHEDULERS: Dict[str, Type[Scheduler]] = {
    CronScheduler.name: CronScheduler,
    InprocScheduler.name: InprocScheduler,
}

__all__ = ["Scheduler", "CronScheduler", "InprocScheduler", "get_scheduler", "SCHEDULERS"]


def get_scheduler(name: str | None = None) -> Scheduler:
    """Instantiate a scheduler by name, defaulting to ``settings.DEFAULT_SCHEDULER``."""
    name = name or settings.DEFAULT_SCHEDULER
    scheduler_cls = SCHEDULERS.get(name)
    if scheduler_cls is None:
        known = ", ".join(sorted(SCHEDULERS))
        raise ValueError(f"Unknown scheduler '{name}'. Available: {known}.")
    return scheduler_cls()

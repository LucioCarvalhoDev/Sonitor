from typing import List

from app.routines.model import Routine
from app.scheduler.base import Scheduler

_NOT_IMPLEMENTED = (
    "The in-process scheduler is not implemented yet. Use the 'cron' scheduler."
)


class InprocScheduler(Scheduler):
    """Placeholder for a long-running in-process scheduler (sub-minute capable).

    The interface is wired so it can be selected via ``get_scheduler('inproc')``;
    the real loop will land in a later version.
    """

    name = "inproc"

    def enable(self, routine: Routine) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def disable(self, routine: Routine) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def is_enabled(self, routine: Routine) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def list_enabled(self) -> List[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

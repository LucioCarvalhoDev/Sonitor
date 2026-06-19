import abc
from typing import List

from app.routines.model import Routine


class Scheduler(abc.ABC):
    """Generic scheduler contract.

    Implementations hook a routine into some recurring execution mechanism
    (the system cron, an in-process loop, ...). The rest of Sonitor depends only
    on this interface, so schedulers are interchangeable via ``get_scheduler``.
    """

    name: str = "_"

    @abc.abstractmethod
    def enable(self, routine: Routine) -> None:
        """Register the routine for recurring execution at its period."""

    @abc.abstractmethod
    def disable(self, routine: Routine) -> None:
        """Remove the routine from recurring execution."""

    @abc.abstractmethod
    def is_enabled(self, routine: Routine) -> bool:
        """Whether the routine is currently scheduled."""

    @abc.abstractmethod
    def list_enabled(self) -> List[str]:
        """Return the uuids of all routines currently scheduled."""

import re
import sys
from subprocess import run
from typing import List

from app import settings
from app.routines.model import Routine
from app.scheduler.base import Scheduler

_PERIOD_RE = re.compile(r"^(\d+)([smhd])$")
_MARKER_RE = re.compile(r"^# sonitor:(\S+)\s*$")


def period_to_cron(period: str) -> str:
    """Translate a routine period into a 5-field cron expression.

    Cron's finest granularity is one minute, so sub-minute periods are rejected
    (use the in-process scheduler once it lands).
    """
    match = _PERIOD_RE.match(period.strip())
    if not match:
        raise ValueError(f"Invalid period '{period}'. Use s|m|h|d (e.g. 5m, 12h, 1d).")
    amount, unit = int(match.group(1)), match.group(2)

    if unit == "s":
        raise ValueError(
            f"Cron granularity is 1 minute; period '{period}' is too small. Use a period >= 1m."
        )
    if unit == "m":
        if not 1 <= amount <= 59:
            raise ValueError("Minute periods for cron must be between 1m and 59m.")
        return f"*/{amount} * * * *"
    if unit == "h":
        if not 1 <= amount <= 23:
            raise ValueError("Hour periods for cron must be between 1h and 23h.")
        return f"0 */{amount} * * *"
    # unit == "d"
    if not 1 <= amount <= 31:
        raise ValueError("Day periods for cron must be between 1d and 31d.")
    return f"0 0 */{amount} * *"


class CronScheduler(Scheduler):
    """Schedules routines by managing the user's crontab.

    Each routine occupies two lines: a ``# sonitor:<uuid>`` marker followed by
    the cron entry that runs ``sonitor.py routine run <uuid>``.
    """

    name = "cron"

    @staticmethod
    def _marker(routine_uuid: str) -> str:
        return f"# sonitor:{routine_uuid}"

    @staticmethod
    def _command(routine_uuid: str) -> str:
        python = sys.executable
        entrypoint = settings.BASE_DIR / "sonitor.py"
        return (
            f"cd {settings.BASE_DIR} && {python} {entrypoint} "
            f"routine run {routine_uuid} >/dev/null 2>&1"
        )

    @staticmethod
    def _read_crontab() -> List[str]:
        result = run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            # No crontab installed yet -> treat as empty.
            return []
        return result.stdout.splitlines()

    @staticmethod
    def _write_crontab(lines: List[str]) -> None:
        payload = ("\n".join(lines) + "\n") if lines else ""
        run(["crontab", "-"], input=payload, text=True, check=True)

    @classmethod
    def _without(cls, lines: List[str], routine_uuid: str) -> List[str]:
        """Drop the marker line for ``routine_uuid`` and the entry that follows it."""
        marker = cls._marker(routine_uuid)
        kept: List[str] = []
        skip_next = False
        for line in lines:
            if skip_next:
                skip_next = False
                continue
            if line.strip() == marker:
                skip_next = True  # also drop the cron entry on the next line
                continue
            kept.append(line)
        return kept

    def enable(self, routine: Routine) -> None:
        schedule = period_to_cron(routine.period)
        lines = self._without(self._read_crontab(), routine.uuid)
        lines.append(self._marker(routine.uuid))
        lines.append(f"{schedule} {self._command(routine.uuid)}")
        self._write_crontab(lines)

    def disable(self, routine: Routine) -> None:
        self._write_crontab(self._without(self._read_crontab(), routine.uuid))

    def is_enabled(self, routine: Routine) -> bool:
        return routine.uuid in self.list_enabled()

    def list_enabled(self) -> List[str]:
        uuids: List[str] = []
        for line in self._read_crontab():
            match = _MARKER_RE.match(line.strip())
            if match:
                uuids.append(match.group(1))
        return uuids

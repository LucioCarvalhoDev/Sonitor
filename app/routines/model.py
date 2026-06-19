import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import tomli
import tomli_w

from app.execution.target import SshTarget

FILE_VERSION = "0.1"
DEFAULT_LOG_MAX_LINES = 1000

# Period suffixes -> seconds.
_PERIOD_UNITS: Dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PERIOD_RE = re.compile(r"^(\d+)([smhd])$")


def parse_period(text: str) -> int:
    """Convert a human period (``30s``, ``5m``, ``12h``, ``1d``) into seconds.

    Raises ``ValueError`` with a friendly message on an invalid format.
    """
    match = _PERIOD_RE.match(text.strip())
    if not match:
        raise ValueError(
            f"Invalid period '{text}'. Use an integer with a suffix s|m|h|d (e.g. 30s, 5m, 12h, 1d)."
        )
    amount, unit = match.groups()
    seconds = int(amount) * _PERIOD_UNITS[unit]
    if seconds <= 0:
        raise ValueError(f"Invalid period '{text}'. Must be greater than zero.")
    return seconds


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Routine:
    """An on-disk routine: a named set of metrics with a recurrence period."""

    uuid: str
    period: str
    metrics: List[Dict] = field(default_factory=list)
    name: str = ""
    annotation: str = ""
    spawn_command: str = ""
    version: str = FILE_VERSION
    log_max_lines: int = DEFAULT_LOG_MAX_LINES
    created_at: datetime = field(default_factory=_now)
    last_run_at: datetime = field(default_factory=_now)
    # Optional SSH target: when set, metrics run on that host (agentless).
    target: Optional[SshTarget] = None

    def period_seconds(self) -> int:
        return parse_period(self.period)

    def to_toml(self) -> str:
        """Serialize to the ``.sonitor`` TOML body (uuid stays in the filename)."""
        document: Dict = {
            "sonitor": {
                "version": self.version,
                "spawn_command": self.spawn_command,
                "name": self.name,
                "annotation": self.annotation,
            },
            "routine": {
                "created_at": self.created_at,
                "last_run_at": self.last_run_at,
                "period": self.period,
                "metrics": self.metrics,
            },
            "log": {
                "max_lines": self.log_max_lines,
            },
        }
        if self.target is not None:
            document["ssh"] = self.target.to_dict()
        return tomli_w.dumps(document)

    @classmethod
    def from_toml(cls, text: str, uuid: str) -> "Routine":
        document = tomli.loads(text)
        sonitor = document.get("sonitor", {})
        routine = document.get("routine", {})
        log = document.get("log", {})
        ssh = document.get("ssh", {})
        return cls(
            uuid=uuid,
            period=routine.get("period", ""),
            metrics=routine.get("metrics", []),
            name=sonitor.get("name", ""),
            annotation=sonitor.get("annotation", ""),
            spawn_command=sonitor.get("spawn_command", ""),
            version=sonitor.get("version", FILE_VERSION),
            log_max_lines=log.get("max_lines", DEFAULT_LOG_MAX_LINES),
            created_at=routine.get("created_at", _now()),
            last_run_at=routine.get("last_run_at", _now()),
            target=SshTarget.from_dict(ssh) if ssh else None,
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "Routine":
        path = Path(path)
        return cls.from_toml(path.read_text(), uuid=path.stem)

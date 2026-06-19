from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import tomli
import tomli_w

from app.execution.target import SshTarget


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Target:
    """A named, persisted SSH target the user can reference by name (``--target``)."""

    name: str
    target: SshTarget
    created_at: datetime = field(default_factory=_now)

    def to_toml(self) -> str:
        document = {
            "target": {
                "name": self.name,
                "created_at": self.created_at,
            },
            "ssh": self.target.to_dict(),
        }
        return tomli_w.dumps(document)

    @classmethod
    def from_toml(cls, text: str, name: str) -> "Target":
        document = tomli.loads(text)
        meta = document.get("target", {})
        ssh = document.get("ssh", {})
        return cls(
            name=meta.get("name", name),
            target=SshTarget.from_dict(ssh),
            created_at=meta.get("created_at", _now()),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "Target":
        path = Path(path)
        return cls.from_toml(path.read_text(), name=path.stem)

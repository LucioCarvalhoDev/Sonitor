from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from app import settings
from app.execution.target import SshTarget
from app.remote.model import Target

TARGET_SUFFIX = ".target"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_name(name: str) -> str:
    """Ensure a target name is a safe slug (it is used as a filename and reference)."""
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid target name '{name}'. Use only letters, digits, '.', '_' or '-'."
        )
    return name


def _targets_dir() -> Path:
    settings.TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    return settings.TARGETS_DIR


def path_for(name: str) -> Path:
    return _targets_dir() / f"{name}{TARGET_SUFFIX}"


def exists(name: str) -> bool:
    return path_for(name).exists()


def save(target: Target) -> Path:
    validate_name(target.name)
    path = path_for(target.name)
    path.write_text(target.to_toml())
    return path


def delete(name: str) -> Path:
    """Remove a target's ``.target`` file (the SSH key is handled by the caller)."""
    path = path_for(name)
    path.unlink(missing_ok=True)
    return path


def list_targets() -> List[Target]:
    targets = [Target.from_path(path) for path in _targets_dir().glob(f"*{TARGET_SUFFIX}")]
    return sorted(targets, key=lambda t: t.created_at)


def resolve(name: str) -> Target:
    path = path_for(name)
    if not path.exists():
        raise ValueError(f"No registered target named '{name}'. Run 'sonitor remote setup' first.")
    return Target.from_path(path)


def resolve_spec(
    value: str,
    identity: Optional[str] = None,
    options: Optional[List[str]] = None,
) -> SshTarget:
    """Resolve a ``--target`` value: a registered name, or a ``[user@]host[:port]`` spec.

    A registered name uses its stored SshTarget as-is; combining it with
    ``--identity``/``--ssh-option`` is a usage error.
    """
    if exists(value):
        if identity or options:
            raise ValueError(
                f"--identity/--ssh-option cannot be combined with the registered target '{value}'."
            )
        return resolve(value).target
    return SshTarget.parse(value, identity_file=identity, options=options or [])

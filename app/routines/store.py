import uuid as uuid_lib
from pathlib import Path
from typing import Dict, List

from app import settings
from app.execution.target import SshTarget
from app.routines.model import DEFAULT_LOG_MAX_LINES, Routine

ROUTINE_SUFFIX = ".sonitor"


def _routines_dir() -> Path:
    settings.ROUTINES_DIR.mkdir(parents=True, exist_ok=True)
    return settings.ROUTINES_DIR


def path_for(routine_uuid: str) -> Path:
    return _routines_dir() / f"{routine_uuid}{ROUTINE_SUFFIX}"


def save(routine: Routine) -> Path:
    path = path_for(routine.uuid)
    path.write_text(routine.to_toml())
    return path


def delete(routine: Routine) -> Path:
    """Remove the routine's ``.sonitor`` file. The log (if any) is left untouched."""
    path = path_for(routine.uuid)
    path.unlink(missing_ok=True)
    return path


def create(
    period: str,
    metrics: List[Dict],
    name: str = "",
    annotation: str = "",
    log_size: int | None = None,
    spawn_command: str = "",
    target: SshTarget | None = None,
) -> Routine:
    if name and _find_by_name(name):
        raise ValueError(f"A routine named '{name}' already exists. Names must be unique.")
    routine = Routine(
        uuid=uuid_lib.uuid4().hex,
        period=period,
        metrics=metrics,
        name=name,
        annotation=annotation,
        spawn_command=spawn_command,
        log_max_lines=log_size or DEFAULT_LOG_MAX_LINES,
        target=target,
    )
    save(routine)
    return routine


def list_routines() -> List[Routine]:
    routines = [Routine.from_path(path) for path in _routines_dir().glob(f"*{ROUTINE_SUFFIX}")]
    return sorted(routines, key=lambda r: r.created_at)


def _find_by_name(name: str) -> List[Routine]:
    return [routine for routine in list_routines() if routine.name and routine.name == name]


def resolve(uuid_or_name: str) -> Routine:
    """Resolve a routine by its uuid (filename) or by its unique name.

    Raises ``ValueError`` if nothing matches, or if more than one routine shares
    the given name (an ambiguity that should never happen, but is guarded here in
    case files were edited or copied by hand).
    """
    by_uuid = path_for(uuid_or_name)
    if by_uuid.exists():
        return Routine.from_path(by_uuid)

    matches = _find_by_name(uuid_or_name)
    if len(matches) > 1:
        uuids = ", ".join(routine.uuid for routine in matches)
        raise ValueError(
            f"Name '{uuid_or_name}' is ambiguous; it matches {len(matches)} routines ({uuids}). "
            f"Reference one by its uuid."
        )
    if matches:
        return matches[0]

    raise ValueError(f"No routine matches uuid or name '{uuid_or_name}'.")

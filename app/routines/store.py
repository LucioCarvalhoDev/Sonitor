import uuid as uuid_lib
from pathlib import Path
from typing import Dict, List

from app import settings
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


def create(
    period: str,
    metrics: List[Dict],
    alias: str = "",
    log_size: int | None = None,
    spawn_command: str = "",
) -> Routine:
    routine = Routine(
        uuid=uuid_lib.uuid4().hex,
        period=period,
        metrics=metrics,
        alias=alias,
        spawn_command=spawn_command,
        log_max_lines=log_size or DEFAULT_LOG_MAX_LINES,
    )
    save(routine)
    return routine


def list_routines() -> List[Routine]:
    routines = [Routine.from_path(path) for path in _routines_dir().glob(f"*{ROUTINE_SUFFIX}")]
    return sorted(routines, key=lambda r: r.created_at)


def resolve(uuid_or_alias: str) -> Routine:
    """Resolve a routine by its uuid (filename) or by its alias."""
    by_uuid = path_for(uuid_or_alias)
    if by_uuid.exists():
        return Routine.from_path(by_uuid)

    for routine in list_routines():
        if routine.alias and routine.alias == uuid_or_alias:
            return routine

    raise ValueError(f"No routine matches uuid or alias '{uuid_or_alias}'.")

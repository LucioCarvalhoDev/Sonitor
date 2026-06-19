import os
from pathlib import Path
from typing import Dict

from app.enums.env_variables import EnvVariable

BASE_DIR = Path(__file__).resolve().parent.parent


def parse_env_file(path: str | Path = ".env") -> Dict[str, str]:
    """Minimal .env parser (no python-dotenv dependency).

    Reads ``KEY=value`` lines, ignoring blanks and ``#`` comments. Returns an
    empty dict when the file is absent so defaults can take over.
    """
    env: Dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return env

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

    return env


_ENV = parse_env_file(BASE_DIR / ".env")


def _get(name: EnvVariable, default: str) -> str:
    return os.environ.get(name.value) or _ENV.get(name.value) or default


STORAGE_DIR = (BASE_DIR / _get(EnvVariable.STORAGE_FOLDER, "./storage")).resolve()
ROUTINES_DIR = STORAGE_DIR / "routines"
LOGS_DIR = STORAGE_DIR / "logs"
TARGETS_DIR = STORAGE_DIR / "targets"
SSH_DIR = STORAGE_DIR / "ssh"

DEFAULT_SCHEDULER = _get(EnvVariable.DEFAULT_SCHEDULER, "cron")

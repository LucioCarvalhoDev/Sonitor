from enum import Enum


class EnvVariable(str, Enum):
    STORAGE_FOLDER = "STORAGE_FOLDER"
    DEFAULT_SCHEDULER = "DEFAULT_SCHEDULER"

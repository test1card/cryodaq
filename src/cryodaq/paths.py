"""Централизованные пути проекта CryoDAQ."""
import os
from pathlib import Path


def get_project_root() -> Path:
    if "CRYODAQ_ROOT" in os.environ:
        return Path(os.environ["CRYODAQ_ROOT"])
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    return get_project_root() / "data"


def get_config_dir() -> Path:
    return get_project_root() / "config"

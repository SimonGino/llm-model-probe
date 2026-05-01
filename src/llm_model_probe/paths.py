"""Filesystem path resolution for the probe tool."""
from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "LLM_MODEL_PROBE_HOME"
DEFAULT_DIR_NAME = ".llm-model-probe"
DB_FILENAME = "probes.db"
CONFIG_FILENAME = "config.toml"


def resolve_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIR_NAME


def ensure_home() -> Path:
    home = resolve_home()
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    return home


def db_path() -> Path:
    return resolve_home() / DB_FILENAME


def config_path() -> Path:
    return resolve_home() / CONFIG_FILENAME

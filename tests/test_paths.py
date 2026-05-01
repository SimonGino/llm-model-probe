"""Tests for paths module."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from llm_model_probe.paths import (
    config_path,
    db_path,
    ensure_home,
    resolve_home,
)


def test_resolve_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL_PROBE_HOME", raising=False)
    assert resolve_home() == Path.home() / ".llm-model-probe"


def test_resolve_home_env_override(isolated_home: Path) -> None:
    assert resolve_home() == isolated_home


def test_ensure_home_creates_dir_with_0700(isolated_home: Path) -> None:
    ensure_home()
    assert isolated_home.exists()
    mode = stat.S_IMODE(isolated_home.stat().st_mode)
    assert mode == 0o700


def test_db_and_config_paths(isolated_home: Path) -> None:
    assert db_path() == isolated_home / "probes.db"
    assert config_path() == isolated_home / "config.toml"

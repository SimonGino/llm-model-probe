"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ~/.llm-model-probe to a tmp dir for the test."""
    home = tmp_path / "probe-home"
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(home))
    return home

"""Tests for settings loader."""
from __future__ import annotations

from pathlib import Path

from llm_model_probe.settings import Settings, load_settings


def test_load_creates_default_when_missing(isolated_home: Path) -> None:
    cfg_path = isolated_home / "config.toml"
    assert not cfg_path.exists()
    settings = load_settings()
    assert cfg_path.exists()
    assert settings.concurrency == 5
    assert settings.timeout_seconds == 30
    assert settings.prompt == "Hi"
    assert "*embedding*" in settings.exclude_patterns


def test_load_respects_overrides(isolated_home: Path) -> None:
    isolated_home.mkdir(parents=True, exist_ok=True)
    (isolated_home / "config.toml").write_text(
        '[probe]\nconcurrency = 12\nprompt = "ping"\n'
        '[filters]\nexclude = ["*foo*"]\n',
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.concurrency == 12
    assert settings.prompt == "ping"
    assert settings.exclude_patterns == ["*foo*"]
    # Other defaults still apply
    assert settings.timeout_seconds == 30


def test_settings_dataclass_defaults() -> None:
    s = Settings()
    assert s.max_tokens == 8
    assert s.retest_cooldown_hours == 24

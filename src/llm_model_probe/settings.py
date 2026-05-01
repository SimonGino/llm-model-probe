"""Loader for ~/.llm-model-probe/config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import config_path, ensure_home

DEFAULT_EXCLUDE = [
    "*embedding*",
    "*embed*",
    "*whisper*",
    "*tts*",
    "*audio*",
    "*dall-e*",
    "*image*",
    "*moderation*",
    "*rerank*",
]

DEFAULT_TOML = """\
# llm-model-probe configuration
[probe]
concurrency = 5
timeout_seconds = 30
max_tokens = 8
prompt = "Hi"
retest_cooldown_hours = 24

[filters]
exclude = [
    "*embedding*", "*embed*",
    "*whisper*", "*tts*", "*audio*",
    "*dall-e*", "*image*",
    "*moderation*", "*rerank*",
]
"""


@dataclass
class Settings:
    concurrency: int = 5
    timeout_seconds: int = 30
    max_tokens: int = 8
    prompt: str = "Hi"
    retest_cooldown_hours: int = 24
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))


def _write_default(path: Path) -> None:
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    path.chmod(0o600)


def load_settings() -> Settings:
    ensure_home()
    path = config_path()
    if not path.exists():
        _write_default(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    probe = data.get("probe") or {}
    filters = data.get("filters") or {}
    return Settings(
        concurrency=int(probe.get("concurrency", 5)),
        timeout_seconds=int(probe.get("timeout_seconds", 30)),
        max_tokens=int(probe.get("max_tokens", 8)),
        prompt=str(probe.get("prompt", "Hi")),
        retest_cooldown_hours=int(probe.get("retest_cooldown_hours", 24)),
        exclude_patterns=list(filters.get("exclude") or DEFAULT_EXCLUDE),
    )

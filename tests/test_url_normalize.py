"""Unit tests for normalize_base_url."""
from __future__ import annotations

import pytest

from llm_model_probe.api import normalize_base_url


@pytest.mark.parametrize(
    "input_url,expected",
    [
        # Standard OpenAI - longest suffix wins
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1",
        ),
        # ZhipuAI (non-/v1) - the bug we are fixing
        (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "https://open.bigmodel.cn/api/paas/v4",
        ),
        # Anthropic
        (
            "https://api.anthropic.com/v1/messages",
            "https://api.anthropic.com",
        ),
        ("https://proxy.example/messages", "https://proxy.example"),
        # Legacy /completions
        (
            "https://api.openai.com/v1/completions",
            "https://api.openai.com/v1",
        ),
        # No suffix — base URL pass-through, only trailing / trimmed
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        # Case-insensitive matching, original case preserved on the kept prefix
        (
            "https://api.openai.com/V1/Chat/Completions",
            "https://api.openai.com/V1",
        ),
        # Trailing slash + suffix combo
        (
            "https://api.openai.com/v1/chat/completions/",
            "https://api.openai.com/v1",
        ),
    ],
)
def test_normalize_base_url(input_url: str, expected: str) -> None:
    assert normalize_base_url(input_url) == expected

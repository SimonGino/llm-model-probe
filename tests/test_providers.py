"""Unit tests for OpenAIProvider.probe behavior on reasoning models."""
from __future__ import annotations

import pytest

from llm_model_probe.providers import OpenAIProvider


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


async def test_openai_probe_first_call_uses_max_tokens_no_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        return _Resp("hi.")

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.probe("gpt-4o-mini", "Hi", 8)

    assert result.available is True
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 8
    assert "max_completion_tokens" not in calls[0]
    assert "reasoning_effort" not in calls[0]


async def test_openai_probe_reasoning_retry_sets_minimal_effort_and_bumps_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError(
                "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."
            )
        return _Resp("ok")

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.probe("o1-mini", "Hi", 8)

    assert result.available is True
    assert len(calls) == 2
    second = calls[1]
    assert "max_tokens" not in second
    assert second["max_completion_tokens"] >= 32
    assert second["reasoning_effort"] == "minimal"


async def test_openai_probe_non_reasoning_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        raise RuntimeError("invalid api key")

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.probe("gpt-4o-mini", "Hi", 8)

    assert result.available is False
    assert result.error_type == "RuntimeError"
    assert "invalid api key" in (result.error_message or "")
    assert len(calls) == 1

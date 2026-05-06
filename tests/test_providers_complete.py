"""Tests for the new complete() method on OpenAI/Anthropic providers."""
from __future__ import annotations

import pytest

from llm_model_probe.providers import (
    AnthropicProvider,
    CompleteResult,
    OpenAIProvider,
)


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _ChatResp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


async def test_openai_complete_uses_response_format_and_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        return _ChatResp('{"hello": "world"}')

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    out = await provider.complete("gpt-4o-mini", "hello", max_tokens=400)
    assert isinstance(out, CompleteResult)
    assert out.text == '{"hello": "world"}'
    assert out.latency_ms >= 0
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["max_tokens"] == 400
    assert calls[0]["response_format"] == {"type": "json_object"}


async def test_openai_complete_retries_without_response_format_on_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some OpenAI-compatible proxies reject response_format. Retry without."""
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        if "response_format" in kwargs:
            raise RuntimeError("response_format not supported by this proxy")
        return _ChatResp('{"ok": true}')

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    out = await provider.complete("m", "hi", max_tokens=200)
    assert out.text == '{"ok": true}'
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


async def test_anthropic_complete_returns_first_text_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AnthropicProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text

    class _MsgResp:
        def __init__(self, text: str) -> None:
            self.content = [_Block(text)]

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        return _MsgResp('{"a": 1}')

    monkeypatch.setattr(provider._client.messages, "create", fake_create)

    out = await provider.complete("claude-3-5-haiku", "hi", max_tokens=300)
    assert out.text == '{"a": 1}'
    assert calls[0]["model"] == "claude-3-5-haiku"
    assert calls[0]["max_tokens"] == 300


async def test_openai_complete_sends_extra_body_to_disable_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qwen vLLM proxies need chat_template_kwargs.enable_thinking=False to
    skip the reasoning step that would otherwise eat the whole token budget."""
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        return _ChatResp('{"ok": 1}')

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    await provider.complete("qwen3", "x", max_tokens=200)
    assert calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


async def test_openai_complete_retries_when_first_call_returns_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some proxies accept the request but silently return empty content.
    Retry stripped of response_format + extra_body."""
    provider = OpenAIProvider(
        name="t", base_url="https://example.com", api_key="sk-x", timeout=5
    )
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return _ChatResp("")  # silent empty
        return _ChatResp('{"recovered": true}')

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    out = await provider.complete("m", "hi", max_tokens=200)
    assert out.text == '{"recovered": true}'
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "extra_body" in calls[0]
    assert "response_format" not in calls[1]
    assert "extra_body" not in calls[1]

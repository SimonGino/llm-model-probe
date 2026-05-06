"""Provider abstractions for OpenAI-compatible and Anthropic SDKs."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .models import Endpoint


@dataclass
class ProbeResult:
    endpoint: str
    sdk: str
    model: str
    available: bool
    latency_ms: int
    error_type: str | None = None
    error_message: str | None = None
    response_preview: str | None = None


@dataclass
class CompleteResult:
    text: str
    latency_ms: int


class Provider(Protocol):
    name: str
    sdk: str

    async def list_models(self) -> list[str]: ...

    async def probe(
        self, model: str, prompt: str, max_tokens: int
    ) -> ProbeResult: ...

    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult: ...

    async def aclose(self) -> None: ...


def _truncate(text: str, limit: int = 300) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class OpenAIProvider:
    sdk = "openai"

    def __init__(self, name: str, base_url: str, api_key: str, timeout: int) -> None:
        self.name = name
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )

    async def list_models(self) -> list[str]:
        page = await self._client.models.list()
        return [m.id for m in page.data]

    async def probe(
        self, model: str, prompt: str, max_tokens: int
    ) -> ProbeResult:
        start = time.perf_counter()
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        try:
            try:
                resp = await self._client.chat.completions.create(**kwargs)
            except Exception as e:
                # Reasoning models (o1/o3/gpt-5 family) need max_completion_tokens
                # AND reasoning_effort=minimal — without the latter, the reasoning
                # budget eats the small probe budget and content comes back empty.
                if "max_completion_tokens" in str(e).lower():
                    kwargs.pop("max_tokens", None)
                    kwargs["max_completion_tokens"] = max(32, max_tokens)
                    kwargs["reasoning_effort"] = "minimal"
                    resp = await self._client.chat.completions.create(**kwargs)
                else:
                    raise
            elapsed = int((time.perf_counter() - start) * 1000)
            content = ""
            if resp.choices:
                msg = resp.choices[0].message
                content = (msg.content if msg else "") or ""
            return ProbeResult(
                endpoint=self.name,
                sdk=self.sdk,
                model=model,
                available=True,
                latency_ms=elapsed,
                response_preview=_truncate(content, 80),
            )
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ProbeResult(
                endpoint=self.name,
                sdk=self.sdk,
                model=model,
                available=False,
                latency_ms=elapsed,
                error_type=type(e).__name__,
                error_message=_truncate(str(e), 300),
            )

    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult:
        start = time.perf_counter()
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            # Disable thinking for Qwen-style vLLM proxies; ignored elsewhere.
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": False}
            },
        }

        def _extract_text(resp) -> str:
            if not resp.choices:
                return ""
            msg = resp.choices[0].message
            return (msg.content if msg else "") or ""

        try:
            resp = await self._client.chat.completions.create(**kwargs)
            text = _extract_text(resp)
        except Exception:
            text = ""
        # Some proxies accept response_format but silently return empty content,
        # or reject extra_body. Retry stripped down if the first call yielded
        # nothing usable.
        if not text:
            kwargs.pop("response_format", None)
            kwargs.pop("extra_body", None)
            resp = await self._client.chat.completions.create(**kwargs)
            text = _extract_text(resp)
        elapsed = int((time.perf_counter() - start) * 1000)
        return CompleteResult(text=text, latency_ms=elapsed)

    async def aclose(self) -> None:
        # Best-effort. httpx + asyncio.run across short-lived per-request
        # clients can race on transport teardown ("Event loop is closed").
        # The actual probe result has already been obtained; connection
        # cleanup happens via GC anyway. Don't let cleanup mask success.
        try:
            await self._client.close()
        except Exception:
            pass


class AnthropicProvider:
    sdk = "anthropic"

    def __init__(self, name: str, base_url: str, api_key: str, timeout: int) -> None:
        self.name = name
        self._client = AsyncAnthropic(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )

    async def list_models(self) -> list[str]:
        page = await self._client.models.list()
        return [m.id for m in page.data]

    async def probe(
        self, model: str, prompt: str, max_tokens: int
    ) -> ProbeResult:
        start = time.perf_counter()
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed = int((time.perf_counter() - start) * 1000)
            content = ""
            if resp.content:
                content = getattr(resp.content[0], "text", "") or ""
            return ProbeResult(
                endpoint=self.name,
                sdk=self.sdk,
                model=model,
                available=True,
                latency_ms=elapsed,
                response_preview=_truncate(content, 80),
            )
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ProbeResult(
                endpoint=self.name,
                sdk=self.sdk,
                model=model,
                available=False,
                latency_ms=elapsed,
                error_type=type(e).__name__,
                error_message=_truncate(str(e), 300),
            )

    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult:
        start = time.perf_counter()
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        text = ""
        if resp.content:
            text = getattr(resp.content[0], "text", "") or ""
        return CompleteResult(text=text, latency_ms=elapsed)

    async def aclose(self) -> None:
        # Best-effort. httpx + asyncio.run across short-lived per-request
        # clients can race on transport teardown ("Event loop is closed").
        # The actual probe result has already been obtained; connection
        # cleanup happens via GC anyway. Don't let cleanup mask success.
        try:
            await self._client.close()
        except Exception:
            pass


def make_provider(endpoint: Endpoint, timeout: int) -> Provider:
    if endpoint.sdk == "openai":
        return OpenAIProvider(
            endpoint.name, endpoint.base_url, endpoint.api_key, timeout
        )
    if endpoint.sdk == "anthropic":
        return AnthropicProvider(
            endpoint.name, endpoint.base_url, endpoint.api_key, timeout
        )
    raise ValueError(f"Unknown sdk: {endpoint.sdk}")

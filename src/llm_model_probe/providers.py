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


class Provider(Protocol):
    name: str
    sdk: str

    async def list_models(self) -> list[str]: ...

    async def probe(
        self, model: str, prompt: str, max_tokens: int
    ) -> ProbeResult: ...

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
                # Reasoning models (o1/o3/gpt-5 family) may require
                # max_completion_tokens instead of max_tokens.
                if "max_completion_tokens" in str(e).lower():
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
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

    async def aclose(self) -> None:
        await self._client.close()


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

    async def aclose(self) -> None:
        await self._client.close()


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

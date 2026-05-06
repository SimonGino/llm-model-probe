# AI Paste Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `✨ AI Parse` button in `AddEndpointDialog` that sends the pasted blob to a user-chosen LLM endpoint (configured once via a Settings modal) and fills in `base_url` / `api_key` / `sdk` / `name`.

**Architecture:** Server-side LLM call. New `app_settings` SQLite table stores the chosen parser endpoint+model. Backend reuses `OpenAIProvider`/`AnthropicProvider` with a new `complete()` method, parses the JSON, and returns structured fields. Frontend gets a Settings modal (gear icon in top bar) and a Parse button on the existing paste textarea.

**Tech Stack:** Python 3.11 / FastAPI / SQLite / Pydantic / pytest. TypeScript / React 18 / TanStack Query / Vite.

**Spec:** `docs/specs/2026-05-06-ai-paste-parser-design.md`

---

## Task 1: `app_settings` table + store methods

**Files:**
- Modify: `src/llm_model_probe/store.py` (SCHEMA constant + new methods on `EndpointStore`)
- Create: `tests/test_app_settings_store.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_app_settings_store.py`:

```python
"""Unit tests for app_settings K/V store methods."""
from __future__ import annotations

from pathlib import Path

from llm_model_probe.store import EndpointStore


def test_get_setting_returns_none_when_unset(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    assert store.get_setting("parser.endpoint_id") is None


def test_set_then_get_setting(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.endpoint_id", "ep_abc123")
    assert store.get_setting("parser.endpoint_id") == "ep_abc123"


def test_set_setting_upserts(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.model_id", "gpt-4o-mini")
    store.set_setting("parser.model_id", "gpt-4o")
    assert store.get_setting("parser.model_id") == "gpt-4o"


def test_delete_setting_removes_row(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.endpoint_id", "ep_abc")
    store.delete_setting("parser.endpoint_id")
    assert store.get_setting("parser.endpoint_id") is None


def test_init_schema_idempotent_with_app_settings(isolated_home: Path) -> None:
    """Calling init_schema twice on an existing DB must not error."""
    store = EndpointStore()
    store.init_schema()
    store.set_setting("k", "v")
    store.init_schema()  # second call
    assert store.get_setting("k") == "v"
```

- [ ] **Step 1.2: Run tests — verify they fail**

Run: `uv run pytest tests/test_app_settings_store.py -v`
Expected: 5 errors / failures, e.g. `AttributeError: 'EndpointStore' object has no attribute 'get_setting'`

- [ ] **Step 1.3: Add table to SCHEMA + new methods**

Modify `src/llm_model_probe/store.py`. In the `SCHEMA` constant, append before the closing `"""`:

```python
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Add these methods to `EndpointStore` (place them right after `delete_orphan_results`):

```python
    # --- app_settings (single-row K/V) -----------------------------

    def get_setting(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        now = _iso(datetime.now())
        with self._conn() as c:
            c.execute(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at""",
                (key, value, now),
            )

    def delete_setting(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM app_settings WHERE key = ?", (key,))
```

- [ ] **Step 1.4: Run tests — verify they pass**

Run: `uv run pytest tests/test_app_settings_store.py -v`
Expected: 5 passed

- [ ] **Step 1.5: Run full backend suite for regression**

Run: `uv run pytest`
Expected: all previously passing tests still pass.

- [ ] **Step 1.6: Commit**

```bash
git add src/llm_model_probe/store.py tests/test_app_settings_store.py
git commit -m "feat(store): app_settings K/V table with get/set/delete"
```

---

## Task 2: `Provider.complete()` for OpenAI + Anthropic

**Files:**
- Modify: `src/llm_model_probe/providers.py`
- Create: `tests/test_providers_complete.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_providers_complete.py`:

```python
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
```

- [ ] **Step 2.2: Run tests — verify they fail**

Run: `uv run pytest tests/test_providers_complete.py -v`
Expected: failures with `ImportError: cannot import name 'CompleteResult'` (or similar).

- [ ] **Step 2.3: Add `CompleteResult` dataclass + Provider protocol method**

Modify `src/llm_model_probe/providers.py`. Add a `CompleteResult` dataclass next to `ProbeResult`:

```python
@dataclass
class CompleteResult:
    text: str
    latency_ms: int
```

Extend the `Provider` protocol with a new method declaration:

```python
    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult: ...
```

- [ ] **Step 2.4: Implement `OpenAIProvider.complete`**

Inside `OpenAIProvider`, add this method (after `probe`):

```python
    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult:
        start = time.perf_counter()
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception:
            # Some OpenAI-compatible proxies reject response_format. Retry plain.
            kwargs.pop("response_format", None)
            resp = await self._client.chat.completions.create(**kwargs)
        elapsed = int((time.perf_counter() - start) * 1000)
        text = ""
        if resp.choices:
            msg = resp.choices[0].message
            text = (msg.content if msg else "") or ""
        return CompleteResult(text=text, latency_ms=elapsed)
```

- [ ] **Step 2.5: Implement `AnthropicProvider.complete`**

Inside `AnthropicProvider`, add this method (after `probe`):

```python
    async def complete(
        self, model: str, prompt: str, max_tokens: int
    ) -> CompleteResult:
        start = time.perf_counter()
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        text = ""
        if resp.content:
            text = getattr(resp.content[0], "text", "") or ""
        return CompleteResult(text=text, latency_ms=elapsed)
```

- [ ] **Step 2.6: Run tests — verify they pass**

Run: `uv run pytest tests/test_providers_complete.py -v`
Expected: 3 passed.

- [ ] **Step 2.7: Run full suite**

Run: `uv run pytest`
Expected: all tests pass.

- [ ] **Step 2.8: Commit**

```bash
git add src/llm_model_probe/providers.py tests/test_providers_complete.py
git commit -m "feat(providers): add complete() method for AI parse usage"
```

---

## Task 3: Prompt builder module

**Files:**
- Create: `src/llm_model_probe/parser_prompt.py`
- Create: `tests/test_parser_prompt.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/test_parser_prompt.py`:

```python
"""Tests for AI-parse prompt builder."""
from __future__ import annotations

from llm_model_probe.parser_prompt import MAX_BLOB_CHARS, build_parse_prompt


def test_short_blob_embedded_verbatim() -> None:
    blob = "BASE_URL=https://x.example.com/v1\nKEY=sk-foo"
    prompt = build_parse_prompt(blob)
    assert blob in prompt
    assert "[truncated]" not in prompt
    # Schema must be in the prompt so the LLM knows the shape
    assert "base_url" in prompt
    assert "api_key" in prompt
    assert "sdk" in prompt
    assert "name" in prompt


def test_long_blob_truncated() -> None:
    blob = "X" * (MAX_BLOB_CHARS + 500)
    prompt = build_parse_prompt(blob)
    assert "[truncated]" in prompt
    assert prompt.count("X") == MAX_BLOB_CHARS


def test_max_blob_chars_is_4000() -> None:
    """Spec pins this at 4000."""
    assert MAX_BLOB_CHARS == 4000
```

- [ ] **Step 3.2: Run tests — verify they fail**

Run: `uv run pytest tests/test_parser_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'llm_model_probe.parser_prompt'`.

- [ ] **Step 3.3: Implement the module**

Create `src/llm_model_probe/parser_prompt.py`:

```python
"""Prompt template + truncation for the AI paste parser."""
from __future__ import annotations

MAX_BLOB_CHARS = 4000

_TEMPLATE = """\
Extract OpenAI/Anthropic-compatible endpoint config from the text below.
Output strict JSON only — no commentary, no markdown fences.

Schema:
{{
  "base_url": string|null,
  "api_key":  string|null,
  "sdk":      "openai"|"anthropic"|null,
  "name":     string|null
}}

Text:
---
{body}
---
"""


def build_parse_prompt(blob: str) -> str:
    if len(blob) > MAX_BLOB_CHARS:
        body = blob[:MAX_BLOB_CHARS] + "\n[truncated]"
    else:
        body = blob
    return _TEMPLATE.format(body=body)
```

- [ ] **Step 3.4: Run tests — verify they pass**

Run: `uv run pytest tests/test_parser_prompt.py -v`
Expected: 3 passed.

- [ ] **Step 3.5: Commit**

```bash
git add src/llm_model_probe/parser_prompt.py tests/test_parser_prompt.py
git commit -m "feat(parser_prompt): JSON-output prompt builder + truncation"
```

---

## Task 4: GET/PUT `/api/settings/parser`

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Create: `tests/test_api_settings_parser.py`

- [ ] **Step 4.1: Write the failing tests**

Create `tests/test_api_settings_parser.py`:

```python
"""Tests for /api/settings/parser GET + PUT."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _seed_ep(store: EndpointStore, models: list[str]) -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name="parser-host",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test1234567890",
        mode="discover",
        models=models,
    )
    store.insert_endpoint(ep)
    return ep


def test_get_returns_nulls_when_unset(client: TestClient) -> None:
    r = client.get("/api/settings/parser")
    assert r.status_code == 200
    assert r.json() == {"endpoint_id": None, "model_id": None}


def test_put_then_get_roundtrip(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["gpt-4o-mini", "gpt-4o"])
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "gpt-4o-mini"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"endpoint_id": ep.id, "model_id": "gpt-4o-mini"}

    g = client.get("/api/settings/parser").json()
    assert g == {"endpoint_id": ep.id, "model_id": "gpt-4o-mini"}


def test_put_endpoint_not_found_400(client: TestClient) -> None:
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": "ep_zzzzzz", "model_id": "x"},
    )
    assert r.status_code == 400


def test_put_model_not_in_endpoint_400(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["gpt-4o-mini"])
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "not-listed"},
    )
    assert r.status_code == 400


def test_get_auto_recovers_when_endpoint_deleted(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["m"])
    client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "m"},
    )
    seed_store.delete_endpoint(ep.id)
    r = client.get("/api/settings/parser")
    assert r.status_code == 200
    assert r.json() == {"endpoint_id": None, "model_id": None}


def test_get_auto_recovers_when_model_dropped(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """If rediscover removed the model, GET must report null/null."""
    from llm_model_probe.api import _persist_models

    ep = _seed_ep(seed_store, ["m1", "m2"])
    client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "m2"},
    )
    _persist_models(seed_store, ep.id, ["m1"])  # m2 is now gone
    r = client.get("/api/settings/parser")
    assert r.json() == {"endpoint_id": None, "model_id": None}
```

- [ ] **Step 4.2: Run tests — verify they fail**

Run: `uv run pytest tests/test_api_settings_parser.py -v`
Expected: 6 failures (404 on the routes since they don't exist yet).

- [ ] **Step 4.3: Implement the route + Pydantic schema**

Modify `src/llm_model_probe/api.py`. Add this near the other Pydantic schemas (around line 145, alongside `PasteParseRequest`):

```python
class ParserSettings(BaseModel):
    endpoint_id: str | None
    model_id: str | None
```

Add the routes (place near the end of the file, before the `parse-paste` block):

```python
def _read_parser_settings(store: EndpointStore) -> ParserSettings:
    """Read parser.endpoint_id + parser.model_id, auto-nulling on staleness."""
    ep_id = store.get_setting("parser.endpoint_id")
    m_id = store.get_setting("parser.model_id")
    if not ep_id or not m_id:
        return ParserSettings(endpoint_id=None, model_id=None)
    ep = store.get_endpoint(ep_id)
    if ep is None or m_id not in ep.models:
        return ParserSettings(endpoint_id=None, model_id=None)
    return ParserSettings(endpoint_id=ep_id, model_id=m_id)


@app.get("/api/settings/parser", response_model=ParserSettings)
def get_parser_settings() -> ParserSettings:
    return _read_parser_settings(_store())


@app.put("/api/settings/parser", response_model=ParserSettings)
def put_parser_settings(payload: ParserSettings) -> ParserSettings:
    store = _store()
    if not payload.endpoint_id or not payload.model_id:
        raise HTTPException(
            status_code=400, detail="endpoint_id and model_id are required"
        )
    ep = store.get_endpoint(payload.endpoint_id)
    if ep is None:
        raise HTTPException(status_code=400, detail="endpoint not found")
    if payload.model_id not in ep.models:
        raise HTTPException(
            status_code=400, detail="model_id not in endpoint.models"
        )
    store.set_setting("parser.endpoint_id", payload.endpoint_id)
    store.set_setting("parser.model_id", payload.model_id)
    return ParserSettings(
        endpoint_id=payload.endpoint_id, model_id=payload.model_id
    )
```

- [ ] **Step 4.4: Run tests — verify they pass**

Run: `uv run pytest tests/test_api_settings_parser.py -v`
Expected: 6 passed.

- [ ] **Step 4.5: Run full suite**

Run: `uv run pytest`
Expected: all green.

- [ ] **Step 4.6: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_settings_parser.py
git commit -m "feat(api): GET/PUT /api/settings/parser with stale-recovery"
```

---

## Task 5: POST `/api/ai-parse`

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Create: `tests/test_api_ai_parse.py`

- [ ] **Step 5.1: Write the failing tests**

Create `tests/test_api_ai_parse.py`:

```python
"""Tests for POST /api/ai-parse."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.providers import CompleteResult
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _setup_parser(store: EndpointStore, model: str = "gpt-4o-mini") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name="parser-host",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test1234567890",
        mode="discover",
        models=[model],
    )
    store.insert_endpoint(ep)
    store.set_setting("parser.endpoint_id", ep.id)
    store.set_setting("parser.model_id", model)
    return ep


def test_412_when_no_default_parser(client: TestClient) -> None:
    r = client.post("/api/ai-parse", json={"blob": "anything"})
    assert r.status_code == 412


def test_success_full_extraction(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text=(
                '{"base_url":"https://x.example.com/v1",'
                '"api_key":"sk-extracted","sdk":"openai","name":"Bob GLM"}'
            ),
            latency_ms=120,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post(
        "/api/ai-parse",
        json={"blob": "Bob said use https://x.example.com/v1 with sk-extracted"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_url"] == "https://x.example.com/v1"
    assert body["api_key"] == "sk-extracted"
    assert body["sdk"] == "openai"
    assert body["name"] == "Bob GLM"
    assert body["confidence"] == 1.0
    assert body["latency_ms"] == 120


def test_partial_extraction_confidence_half(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text='{"base_url":"https://x/v1","api_key":null,"sdk":null,"name":null}',
            latency_ms=88,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://x/v1"
    assert body["api_key"] is None
    assert body["confidence"] == 0.5


def test_unparseable_response_confidence_zero(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(text="I don't know what you mean.", latency_ms=12)

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == 0.0
    assert body["base_url"] is None
    assert body["api_key"] is None


def test_extracts_first_json_block_when_wrapped_in_prose(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some models return ```json\\n{...}\\n``` instead of bare JSON."""
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text=(
                "Sure! Here you go:\n```json\n"
                '{"base_url":"https://y/v1","api_key":"sk-y",'
                '"sdk":"openai","name":"y"}\n```\nDone."
            ),
            latency_ms=200,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://y/v1"
    assert body["api_key"] == "sk-y"
    assert body["confidence"] == 1.0


def test_provider_error_502(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        raise TimeoutError("timed out talking to upstream")

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 502
    body = r.json()
    assert "TimeoutError" in body["detail"]


def test_blob_truncated_before_prompt(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.parser_prompt import MAX_BLOB_CHARS
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)
    seen_prompt: dict[str, str] = {}

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        seen_prompt["p"] = prompt
        return CompleteResult(
            text='{"base_url":null,"api_key":null,"sdk":null,"name":null}',
            latency_ms=10,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    big = "X" * (MAX_BLOB_CHARS + 1000)
    r = client.post("/api/ai-parse", json={"blob": big})
    assert r.status_code == 200
    assert "[truncated]" in seen_prompt["p"]
    assert seen_prompt["p"].count("X") == MAX_BLOB_CHARS
```

- [ ] **Step 5.2: Run tests — verify they fail**

Run: `uv run pytest tests/test_api_ai_parse.py -v`
Expected: 7 failures (route doesn't exist).

- [ ] **Step 5.3: Implement the route**

Modify `src/llm_model_probe/api.py`. Near the other Pydantic schemas, add:

```python
class AiParseRequest(BaseModel):
    blob: str = Field(..., min_length=1)


class AiParseResponse(BaseModel):
    base_url: str | None
    api_key: str | None
    sdk: SdkType | None
    name: str | None
    confidence: float
    latency_ms: int
```

Add this helper next to `_read_parser_settings`:

```python
def _extract_json_object(text: str) -> dict | None:
    """Try strict json.loads first, then fall back to the first {...} block."""
    import json as _j
    import re as _re

    text = text.strip()
    try:
        v = _j.loads(text)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    m = _re.search(r"\{.*?\}", text, flags=_re.DOTALL)
    if not m:
        return None
    try:
        v = _j.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except Exception:
        return None
```

Add the route (place just below the parser settings routes):

```python
@app.post("/api/ai-parse", response_model=AiParseResponse)
def ai_parse(req: AiParseRequest) -> AiParseResponse:
    from .parser_prompt import build_parse_prompt
    from .providers import make_provider

    store = _store()
    settings = _read_parser_settings(store)
    if settings.endpoint_id is None or settings.model_id is None:
        raise HTTPException(
            status_code=412,
            detail="default parser not configured; set one in Settings",
        )
    ep = store.get_endpoint(settings.endpoint_id)
    assert ep is not None  # _read_parser_settings already nulled stale rows

    prompt = build_parse_prompt(req.blob)
    runtime = load_settings()
    provider = make_provider(ep, runtime.timeout_seconds)
    try:
        try:
            result = asyncio.run(
                provider.complete(settings.model_id, prompt, max_tokens=400)
            )
        finally:
            asyncio.run(provider.aclose())
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"{type(e).__name__}: {str(e)[:200]}",
        )

    obj = _extract_json_object(result.text) or {}

    def _get(key: str) -> str | None:
        v = obj.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    base_url = _get("base_url")
    api_key = _get("api_key")
    sdk = _get("sdk")
    if sdk not in ("openai", "anthropic"):
        sdk = None
    name = _get("name")

    if base_url and api_key:
        confidence = 1.0
    elif base_url or api_key:
        confidence = 0.5
    else:
        confidence = 0.0

    return AiParseResponse(
        base_url=base_url,
        api_key=api_key,
        sdk=sdk,  # type: ignore[arg-type]
        name=name,
        confidence=confidence,
        latency_ms=result.latency_ms,
    )
```

- [ ] **Step 5.4: Run tests — verify they pass**

Run: `uv run pytest tests/test_api_ai_parse.py -v`
Expected: 7 passed.

- [ ] **Step 5.5: Run full suite**

Run: `uv run pytest`
Expected: all green.

- [ ] **Step 5.6: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_ai_parse.py
git commit -m "feat(api): POST /api/ai-parse — server-side LLM extraction"
```

---

## Task 6: Frontend types + API client

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 6.1: Add types**

Append to `frontend/src/lib/types.ts`:

```ts
export interface ParserSettings {
  endpoint_id: string | null;
  model_id: string | null;
}

export interface AiParseResult {
  base_url: string | null;
  api_key: string | null;
  sdk: "openai" | "anthropic" | null;
  name: string | null;
  confidence: number;
  latency_ms: number;
}
```

- [ ] **Step 6.2: Add API methods**

Modify `frontend/src/lib/api.ts`. Update the import block to include the new types:

```ts
import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  EndpointUpdate,
  PasteSuggestion,
  ModelResultPublic,
  ParserSettings,
  AiParseResult,
} from "./types";
```

Add three methods inside the `api` export:

```ts
  getParserSettings: () =>
    req<ParserSettings>("GET", "/api/settings/parser"),
  setParserSettings: (s: ParserSettings) =>
    req<ParserSettings>("PUT", "/api/settings/parser", s),
  aiParse: (blob: string) =>
    req<AiParseResult>("POST", "/api/ai-parse", { blob }),
```

- [ ] **Step 6.3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 6.4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): types + API client for parser settings & AI parse"
```

---

## Task 7: SettingsModal component

**Files:**
- Create: `frontend/src/components/SettingsModal.tsx`

- [ ] **Step 7.1: Create the component**

Create `frontend/src/components/SettingsModal.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { endpointHealth } from "@/components/atoms";

export default function SettingsModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["parser-settings"],
    queryFn: () => api.getParserSettings(),
    enabled: open,
  });
  const endpoints = useQuery({
    queryKey: ["endpoints"],
    queryFn: () => api.listEndpoints(),
    enabled: open,
  });

  const [endpointId, setEndpointId] = useState<string>("");
  const [modelId, setModelId] = useState<string>("");
  const [endpointModels, setEndpointModels] = useState<string[]>([]);

  useEffect(() => {
    if (settings.data) {
      setEndpointId(settings.data.endpoint_id ?? "");
      setModelId(settings.data.model_id ?? "");
    }
  }, [settings.data]);

  // When the chosen endpoint changes, fetch its detail to populate model list.
  const detail = useQuery({
    queryKey: ["endpoint", endpointId],
    queryFn: () => api.getEndpoint(endpointId),
    enabled: !!endpointId && open,
  });

  useEffect(() => {
    if (detail.data) {
      const availableModels = detail.data.results
        .filter((r) => r.status === "available")
        .map((r) => r.model_id);
      setEndpointModels(
        availableModels.length > 0 ? availableModels : detail.data.models,
      );
    }
  }, [detail.data]);

  const usableEndpoints = useMemo(
    () =>
      (endpoints.data ?? []).filter(
        (e: EndpointSummary) => endpointHealth(e).tone !== "bad",
      ),
    [endpoints.data],
  );

  const save = useMutation({
    mutationFn: () =>
      api.setParserSettings({
        endpoint_id: endpointId || null,
        model_id: modelId || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parser-settings"] });
      onClose();
    },
  });

  if (!open) return null;
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.45)",
        display: "grid",
        placeItems: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          color: "var(--text)",
          padding: 24,
          borderRadius: 10,
          minWidth: 420,
          maxWidth: 540,
          border: "1px solid var(--border)",
        }}
      >
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Settings</h3>
        <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
          Default AI Parser
        </h4>

        <label style={{ display: "block", fontSize: 11, marginBottom: 4 }}>
          Endpoint
        </label>
        <select
          value={endpointId}
          onChange={(e) => {
            setEndpointId(e.target.value);
            setModelId("");
          }}
          style={{ width: "100%", marginBottom: 12, height: 32 }}
        >
          <option value="">— select —</option>
          {usableEndpoints.map((e: EndpointSummary) => (
            <option key={e.id} value={e.id}>
              {e.name} ({e.sdk})
            </option>
          ))}
        </select>

        <label style={{ display: "block", fontSize: 11, marginBottom: 4 }}>
          Model
        </label>
        <select
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          disabled={!endpointId}
          style={{ width: "100%", marginBottom: 12, height: 32 }}
        >
          <option value="">— select —</option>
          {endpointModels.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        <p style={{ fontSize: 11, color: "var(--text-muted)" }}>
          AI Parse 会把粘贴文本发给这里选中的 endpoint；该 endpoint 的服务方
          会看到内容（可能含其他 endpoint 的 api_key）。
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 14,
          }}
        >
          <button className="btn btn-sm btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-sm btn-primary"
            disabled={!endpointId || !modelId || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7.2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 7.3: Commit**

```bash
git add frontend/src/components/SettingsModal.tsx
git commit -m "feat(frontend): SettingsModal — pick default AI parser endpoint+model"
```

---

## Task 8: Wire Settings gear icon into top bar

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/atoms.tsx` (Icon name list — `settings` already exists, verify)

- [ ] **Step 8.1: Verify the `settings` icon exists**

Run: `grep -n "case \"settings\"" frontend/src/components/atoms.tsx`
Expected: a hit (line ~127).

If missing, no action needed — it's there per current code.

**Existing top-bar structure** (from `App.tsx`):
- The header is rendered by a `Header` component (~line 212–298) with prop callbacks `onAdd`, `onRetestAll`, `onLogout`.
- Inside the header the action cluster is: `<ThemeToggle/>`, then the Retest-all `<button>`, then the Add `<button>`, then the Logout `<button>`.
- `<SplitApp>` (~line 67) is the parent that holds dialog/modal open state (e.g. `showAdd`).

We add a **`Settings` gear button immediately to the left of `<ThemeToggle/>`** and lift the modal-open state into `SplitApp`.

- [ ] **Step 8.2: Lift `settingsOpen` into SplitApp + import the modal**

In `frontend/src/App.tsx`, add to the imports near the other components:

```tsx
import SettingsModal from "@/components/SettingsModal";
```

Inside `SplitApp` (alongside the existing `setShowAdd`-style state), add:

```tsx
const [settingsOpen, setSettingsOpen] = useState(false);
```

- [ ] **Step 8.3: Pass `onOpenSettings` into Header**

Update Header's prop type (line ~218):

```tsx
  onAdd: () => void;
  onRetestAll: () => void;
  onLogout: () => void;
  onOpenSettings: () => void;
```

Pass it from `SplitApp`'s render of `<Header ... />` (~line 152):

```tsx
onOpenSettings={() => setSettingsOpen(true)}
```

Inside `Header`, just before the existing `<ThemeToggle />` (line ~277), insert:

```tsx
<button
  className="btn btn-ghost btn-icon"
  title="Settings"
  aria-label="Settings"
  onClick={onOpenSettings}
>
  <Icon name="settings" size={13} />
</button>
```

- [ ] **Step 8.4: Render `<SettingsModal>` from SplitApp**

At the end of `SplitApp`'s return (alongside the existing `<AddEndpointDialog>` modal mount, if any), add:

```tsx
<SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
```

- [ ] **Step 8.5: Type-check + build**

Run:
```bash
cd frontend
npx tsc --noEmit
npm run build
```
Expected: both exit 0.

- [ ] **Step 8.6: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): top-bar gear icon opens SettingsModal"
```

---

## Task 9: ✨ AI Parse button in AddEndpointDialog

**Files:**
- Modify: `frontend/src/components/AddEndpointDialog.tsx`

**Existing state names** (confirmed by reading the file):
- The form is a single object: `const [form, setForm] = useState<FormState>(...)`.
- An `update(k, v)` helper exists: `function update<K extends keyof FormState>(k: K, v: FormState[K])`.
- The paste textarea state is `const [paste, setPaste] = useState("")`.
- `FormState` has `{ name, sdk, base_url, api_key, note }`.

- [ ] **Step 9.1: Add AI Parse state + mutation**

Modify `frontend/src/components/AddEndpointDialog.tsx`. Just below the existing `const [parsing, setParsing] = useState(false);` line, add:

```tsx
const [aiError, setAiError] = useState<string | null>(null);
const aiParse = useMutation({
  mutationFn: (blob: string) => api.aiParse(blob),
  onSuccess: (out) => {
    setAiError(null);
    if (out.base_url) update("base_url", out.base_url);
    if (out.api_key) update("api_key", out.api_key);
    if (out.sdk) update("sdk", out.sdk);
    if (out.name) update("name", out.name);
  },
  onError: (err: Error) => {
    const msg = err.message || "parse failed";
    if (msg.startsWith("412")) {
      setAiError("Set a default parser in Settings first.");
    } else {
      setAiError(msg.slice(0, 160));
    }
  },
});
```

- [ ] **Step 9.2: Add the button**

Locate the textarea where `setPaste` is wired (line ~278: `onChange={(e) => setPaste(e.target.value)}`). Just below that textarea's container, in the same row as the Smart-paste helper text, add:

```tsx
<button
  type="button"
  className="btn btn-sm"
  onClick={() => aiParse.mutate(paste)}
  disabled={!paste.trim() || aiParse.isPending}
  title="Use the configured AI parser to extract fields"
  style={{ marginLeft: 8 }}
>
  {aiParse.isPending ? "Parsing…" : "✨ AI Parse"}
</button>
```

- [ ] **Step 9.3: Render the error helper**

Directly under the textarea row (after the button), add:

```tsx
{aiError && (
  <div
    style={{
      fontSize: 11,
      color: "var(--bad)",
      marginTop: 6,
    }}
  >
    {aiError}
  </div>
)}
```

- [ ] **Step 9.4: Type-check + build**

Run:
```bash
cd frontend
npx tsc --noEmit
npm run build
```
Expected: exit 0 on both.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/components/AddEndpointDialog.tsx
git commit -m "feat(frontend): ✨ AI Parse button in AddEndpointDialog"
```

---

## Task 10: Manual smoke test

- [ ] **Step 10.1: Start dev servers**

Terminal 1:
```bash
uv run probe ui --dev --no-browser
```

Terminal 2:
```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`.

- [ ] **Step 10.2: Verify Settings flow**

1. Click the gear icon in the top bar → modal opens.
2. Endpoint dropdown shows endpoints whose health is not "all down".
3. Pick an endpoint → Model dropdown populates with its available models.
4. Save → modal closes; reopening shows the saved values pre-filled.

- [ ] **Step 10.3: Verify AI Parse — success path**

1. Click `+ Add` → AddEndpointDialog opens.
2. Paste a messy natural-language blob containing a base URL and API key
   (e.g., "Hey here's the new endpoint: api at <https://x/v1>, key sk-AAA").
3. Click `✨ AI Parse`. Button shows `Parsing…`.
4. On return: base_url / api_key / sdk / name fields fill in.
5. Verify you can save the endpoint and probe it normally.

- [ ] **Step 10.4: Verify AI Parse — 412 path**

1. Use sqlite directly (or via a fresh DB) to clear `app_settings`:
   ```bash
   sqlite3 ~/.llm-model-probe/probes.db "DELETE FROM app_settings;"
   ```
2. Reload UI, paste a blob, click `✨ AI Parse`.
3. Expect the red helper text "Set a default parser in Settings first."

- [ ] **Step 10.5: Verify AI Parse — provider error**

1. In Settings, select an endpoint whose key is intentionally broken (or
   block its host with a fake `/etc/hosts` entry).
2. Click `✨ AI Parse`.
3. Expect a 502-style error message under the textarea (e.g.,
   `AuthenticationError: ...`).

- [ ] **Step 10.6: Final build check**

Run:
```bash
cd frontend && npm run build
uv run pytest
```
Both must exit 0 with no failures.

---

## Self-Review Notes

- Spec coverage:
  - Data model (Spec §Data Model) → Task 1.
  - Provider.complete (Spec §LLM Call) → Task 2.
  - Prompt template + truncation (Spec §LLM Call) → Task 3.
  - Settings GET/PUT routes (Spec §API) → Task 4.
  - AI Parse route + JSON extraction (Spec §API + §LLM Call) → Task 5.
  - Frontend types/api (implicit) → Task 6.
  - Settings modal (Spec §Frontend) → Task 7.
  - Gear icon wiring (Spec §Frontend) → Task 8.
  - AddEndpointDialog button + behavior (Spec §Frontend) → Task 9.
  - Manual smoke (Spec §Testing — UI portion) → Task 10.
- Error handling matrix from spec is enforced by the backend tests in Tasks
  4–5; frontend error display covered in Task 9.
- No placeholder/TODO steps; every code block is concrete.

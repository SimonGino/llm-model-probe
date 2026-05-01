# LLM Model Probe UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local web UI described in `docs/specs/2026-05-01-ui-design.md`: FastAPI REST API on top of the existing CLI/store, plus a React (Vite + TS + Tailwind + shadcn/ui) SPA, plus a `probe ui` launcher command and Docker packaging.

**Architecture:** New module `src/llm_model_probe/api.py` exposes JSON over `/api/*`; reuses existing `EndpointStore` and `ProbeRunner` directly. New `frontend/` directory holds the SPA. `probe ui` runs uvicorn; in production it serves `frontend/dist/` as static files.

**Tech Stack:** FastAPI, uvicorn, Pydantic v2, pytest + httpx (TestClient); Vite, TypeScript, Tailwind CSS, shadcn/ui, @tanstack/react-query.

---

## File Structure

```
src/llm_model_probe/
├── api.py                          # NEW: FastAPI app, routers, Pydantic models, parse logic
└── cli.py                          # MODIFY: add `ui` command

frontend/                            # NEW (npm-managed, gitignore node_modules + dist)
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── components.json                 # shadcn manifest
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── index.css
    ├── components/
    │   ├── EndpointTable.tsx
    │   ├── EndpointDetailDrawer.tsx
    │   ├── AddEndpointDialog.tsx
    │   ├── SmartPasteArea.tsx
    │   ├── ConfirmDialog.tsx
    │   └── ui/                     # shadcn-generated
    └── lib/
        ├── api.ts
        ├── parsePaste.ts
        ├── types.ts
        └── format.ts

tests/
├── test_api_endpoints.py           # NEW
├── test_api_parse.py               # NEW
└── test_api_meta.py                # NEW

Dockerfile                           # NEW
docker-compose.yml                   # NEW
.dockerignore                        # NEW
README.md                            # MODIFY
```

---

## Task 1: FastAPI scaffold + Pydantic schemas + /health

**Files:**
- Modify: `pyproject.toml`
- Create: `src/llm_model_probe/api.py`
- Create: `tests/test_api_meta.py`

- [ ] **Step 1: Add deps**

```bash
cd ~/Code/Tools/llm-model-probe
uv add fastapi uvicorn[standard]
uv add --dev httpx
```

(httpx is used by FastAPI's TestClient.)

- [ ] **Step 2: Write failing /health test**

Create `tests/test_api_meta.py`:

```python
"""Tests for /api/health and /api/settings."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llm_model_probe.api import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 3: Run test — expect failure**

Run: `uv run pytest tests/test_api_meta.py -q`
Expected: `ImportError: cannot import name 'app'`.

- [ ] **Step 4: Implement minimal api.py with schemas + /health**

Create `src/llm_model_probe/api.py`:

```python
"""FastAPI app exposing /api/* for the local management UI."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

DEV_MODE = os.environ.get("LLM_MODEL_PROBE_DEV") == "1"

app = FastAPI(title="llm-model-probe")

if DEV_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------- Pydantic schemas ----------

SdkType = Literal["openai", "anthropic"]
Mode = Literal["discover", "specified"]
Status = Literal["available", "failed"]
ResultSource = Literal["discovered", "specified"]


class EndpointSummary(BaseModel):
    id: str
    name: str
    sdk: SdkType
    base_url: str
    mode: Mode
    note: str
    list_error: str | None
    available: int
    failed: int
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelResultPublic(BaseModel):
    model_id: str
    source: ResultSource
    status: Status
    latency_ms: int | None
    error_type: str | None
    error_message: str | None
    response_preview: str | None
    last_tested_at: datetime | None


class EndpointDetail(EndpointSummary):
    api_key_masked: str
    models: list[str]
    results: list[ModelResultPublic]


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1)
    sdk: SdkType
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    models: list[str] = []
    note: str = ""
    no_probe: bool = False


class PasteParseRequest(BaseModel):
    blob: str


class PasteParseResponse(BaseModel):
    suggested: dict
    confidence: float
    parser: Literal["json", "dotenv", "curl", "none"]


# ---------- routes ----------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
```

- [ ] **Step 5: Run test — expect pass**

Run: `uv run pytest tests/test_api_meta.py -q`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/llm_model_probe/api.py tests/test_api_meta.py
git commit -m "feat(api): FastAPI scaffold + Pydantic schemas + /health"
```

---

## Task 2: GET /api/endpoints + GET /api/endpoints/{id}

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Create: `tests/test_api_endpoints.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_api_endpoints.py`:

```python
"""Tests for /api/endpoints CRUD."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, ModelResult, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _seed_endpoint(store: EndpointStore, name: str = "alpha") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-1234567890wxyz",
        mode="discover",
        models=[],
        note="seeded",
    )
    store.insert_endpoint(ep)
    store.replace_model_results(ep.id, [
        ModelResult(ep.id, "gpt-4", "discovered", "available", 100,
                    response_preview="hi", last_tested_at=datetime.now()),
        ModelResult(ep.id, "gpt-3.5", "discovered", "failed", 50,
                    error_type="AuthError", error_message="bad",
                    last_tested_at=datetime.now()),
    ])
    return ep


def test_list_endpoints_empty(client: TestClient) -> None:
    r = client.get("/api/endpoints")
    assert r.status_code == 200
    assert r.json() == []


def test_list_endpoints_with_summary(
    client: TestClient, seed_store: EndpointStore
) -> None:
    _seed_endpoint(seed_store, "alpha")
    r = client.get("/api/endpoints")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    item = body[0]
    assert item["name"] == "alpha"
    assert item["available"] == 1
    assert item["failed"] == 1
    assert "api_key" not in item


def test_get_endpoint_detail_by_name(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "beta")
    r = client.get(f"/api/endpoints/beta")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ep.id
    assert body["api_key_masked"] == "sk-1...wxyz"
    assert "api_key" not in body
    assert {res["model_id"] for res in body["results"]} == {"gpt-4", "gpt-3.5"}


def test_get_endpoint_detail_by_id(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "gamma")
    r = client.get(f"/api/endpoints/{ep.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "gamma"


def test_get_endpoint_detail_not_found(client: TestClient) -> None:
    r = client.get("/api/endpoints/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: `404` for the empty list (route not registered).

- [ ] **Step 3: Implement list + detail routes**

Append to `src/llm_model_probe/api.py` (after `health()`):

```python
from fastapi import HTTPException

from .models import Endpoint
from .report import mask_api_key
from .store import EndpointStore


def _store() -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _summary(store: EndpointStore, ep: Endpoint) -> EndpointSummary:
    ok, fail = store.summary(ep.id)
    return EndpointSummary(
        id=ep.id,
        name=ep.name,
        sdk=ep.sdk,
        base_url=ep.base_url,
        mode=ep.mode,
        note=ep.note,
        list_error=ep.list_error,
        available=ok,
        failed=fail,
        last_tested_at=store.last_tested_at(ep.id),
        created_at=ep.created_at or datetime.now(),
        updated_at=ep.updated_at or datetime.now(),
    )


def _detail(store: EndpointStore, ep: Endpoint) -> EndpointDetail:
    summary = _summary(store, ep)
    results = [
        ModelResultPublic(
            model_id=r.model_id,
            source=r.source,
            status=r.status,
            latency_ms=r.latency_ms,
            error_type=r.error_type,
            error_message=r.error_message,
            response_preview=r.response_preview,
            last_tested_at=r.last_tested_at,
        )
        for r in store.list_model_results(ep.id)
    ]
    return EndpointDetail(
        **summary.model_dump(),
        api_key_masked=mask_api_key(ep.api_key),
        models=ep.models,
        results=results,
    )


@app.get("/api/endpoints", response_model=list[EndpointSummary])
def list_endpoints() -> list[EndpointSummary]:
    store = _store()
    return [_summary(store, ep) for ep in store.list_endpoints()]


@app.get("/api/endpoints/{name_or_id}", response_model=EndpointDetail)
def get_endpoint(name_or_id: str) -> EndpointDetail:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return _detail(store, ep)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): GET /api/endpoints (list + detail)"
```

---

## Task 3: POST /api/endpoints (create + probe)

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Modify: `tests/test_api_endpoints.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_create_no_probe(client: TestClient, isolated_home: Path) -> None:
    payload = {
        "name": "delta",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-1111222233334444",
        "models": ["gpt-4o"],
        "note": "test",
        "no_probe": True,
    }
    r = client.post("/api/endpoints", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "delta"
    assert body["mode"] == "specified"
    assert "api_key" not in body
    assert body["api_key_masked"].endswith("4444")


def test_create_duplicate_name_409(
    client: TestClient, isolated_home: Path
) -> None:
    payload = {
        "name": "dup",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-1234567890aaaa",
        "no_probe": True,
    }
    assert client.post("/api/endpoints", json=payload).status_code == 201
    r = client.post("/api/endpoints", json=payload)
    assert r.status_code == 409


def test_create_invalid_sdk_422(
    client: TestClient, isolated_home: Path
) -> None:
    r = client.post(
        "/api/endpoints",
        json={
            "name": "bad",
            "sdk": "cohere",
            "base_url": "https://x/v1",
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 422


def test_create_with_probe_uses_runner(
    client: TestClient, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke: when no_probe=False the API calls ProbeRunner.

    We don't exercise real network; we monkeypatch ProbeRunner.probe_endpoint.
    """
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "fake-model", "specified", "available", 42,
                            response_preview="hi", last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "probed",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa11112222bbbb",
            "models": ["fake-model"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["available"] == 1
    assert body["results"][0]["model_id"] == "fake-model"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: failures (POST not implemented).

- [ ] **Step 3: Implement create route**

Append to `src/llm_model_probe/api.py`:

```python
import asyncio
from fastapi import status

from .models import new_endpoint_id
from .probe import ProbeRunner
from .settings import load_settings


@app.post(
    "/api/endpoints",
    response_model=EndpointDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_endpoint(payload: EndpointCreate) -> EndpointDetail:
    store = _store()
    mode = "specified" if payload.models else "discover"
    ep = Endpoint(
        id=new_endpoint_id(),
        name=payload.name,
        sdk=payload.sdk,
        base_url=str(payload.base_url).rstrip("/"),
        api_key=payload.api_key,
        mode=mode,  # type: ignore[arg-type]
        models=list(payload.models),
        note=payload.note,
    )
    try:
        store.insert_endpoint(ep)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not payload.no_probe:
        runner = ProbeRunner(load_settings())
        outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=False))
        if outcome.list_error:
            store.set_list_error(ep.id, outcome.list_error)
        else:
            store.set_list_error(ep.id, None)
            if outcome.new_results is not None:
                store.replace_model_results(ep.id, outcome.new_results)

    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _detail(store, fresh)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: all green (the previous 5 + 4 new = 9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): POST /api/endpoints (create + immediate probe)"
```

---

## Task 4: DELETE + retest single + retest-all

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Modify: `tests/test_api_endpoints.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_delete_endpoint(client: TestClient, seed_store: EndpointStore) -> None:
    ep = _seed_endpoint(seed_store, "to-delete")
    r = client.delete(f"/api/endpoints/{ep.id}")
    assert r.status_code == 204
    assert client.get(f"/api/endpoints/{ep.id}").status_code == 404


def test_delete_not_found(client: TestClient) -> None:
    assert client.delete("/api/endpoints/nope").status_code == 404


def test_retest_single(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    ep = _seed_endpoint(seed_store, "epsilon")

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "new-model", "discovered", "available", 9,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post(f"/api/endpoints/{ep.id}/retest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(res["model_id"] == "new-model" for res in body["results"])


def test_retest_all(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    _seed_endpoint(seed_store, "ep-a")
    _seed_endpoint(seed_store, "ep-b")

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "m", "discovered", "available", 1,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post("/api/retest-all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retested"] == 2
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: 4 failures (routes not yet implemented).

- [ ] **Step 3: Implement DELETE + retest routes**

Append to `src/llm_model_probe/api.py`:

```python
@app.delete("/api/endpoints/{name_or_id}", status_code=204)
def delete_endpoint(name_or_id: str) -> None:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    store.delete_endpoint(ep.id)


def _apply_outcome(store: EndpointStore, ep: Endpoint, outcome) -> None:
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
    if outcome.new_results is not None:
        store.replace_model_results(ep.id, outcome.new_results)


@app.post("/api/endpoints/{name_or_id}/retest", response_model=EndpointDetail)
def retest_endpoint(name_or_id: str) -> EndpointDetail:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    runner = ProbeRunner(load_settings())
    outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=True))
    _apply_outcome(store, ep, outcome)
    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _detail(store, fresh)


@app.post("/api/retest-all")
def retest_all() -> dict:
    store = _store()
    runner = ProbeRunner(load_settings())
    eps = store.list_endpoints()

    async def run_all() -> None:
        for ep in eps:
            outcome = await runner.probe_endpoint(ep, allow_partial=True)
            _apply_outcome(store, ep, outcome)

    asyncio.run(run_all())
    return {"retested": len(eps)}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): DELETE + retest single + retest-all"
```

---

## Task 5: parse-paste + settings + key-leak regression

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Create: `tests/test_api_parse.py`
- Modify: `tests/test_api_meta.py`

- [ ] **Step 1: Write failing parse tests**

Create `tests/test_api_parse.py`:

```python
"""Tests for /api/parse-paste."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_model_probe.api import app


def _client(isolated_home: Path) -> TestClient:
    return TestClient(app)


def test_parse_json_blob(isolated_home: Path) -> None:
    blob = '{"base_url": "https://api.x/v1", "api_key": "sk-1", "models": ["a"]}'
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "json"
    assert body["suggested"]["base_url"] == "https://api.x/v1"
    assert body["suggested"]["api_key"] == "sk-1"
    assert body["suggested"]["models"] == ["a"]
    assert body["confidence"] >= 0.8


def test_parse_dotenv(isolated_home: Path) -> None:
    blob = "OPENAI_BASE_URL=https://api.y/v1\nOPENAI_API_KEY=sk-y"
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    body = r.json()
    assert body["parser"] == "dotenv"
    assert body["suggested"]["base_url"] == "https://api.y/v1"
    assert body["suggested"]["api_key"] == "sk-y"
    assert body["suggested"]["sdk"] == "openai"


def test_parse_curl(isolated_home: Path) -> None:
    blob = (
        "curl https://api.anthropic.com/v1/messages "
        "-H 'Authorization: Bearer sk-ant-xxx' "
        "-H 'content-type: application/json'"
    )
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    body = r.json()
    assert body["parser"] == "curl"
    assert body["suggested"]["api_key"] == "sk-ant-xxx"
    assert "anthropic.com" in body["suggested"]["base_url"]
    assert body["suggested"]["sdk"] == "anthropic"


def test_parse_unrecognized(isolated_home: Path) -> None:
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": "hello"})
    body = r.json()
    assert body["parser"] == "none"
    assert body["confidence"] == 0
    assert body["suggested"] == {}
```

- [ ] **Step 2: Add settings + key-leak tests**

Append to `tests/test_api_meta.py`:

```python
def test_settings_endpoint(isolated_home) -> None:
    client = TestClient(app)
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["concurrency"] >= 1
    assert "exclude_patterns" in body


def test_no_api_key_leak_in_any_response(
    isolated_home, monkeypatch
) -> None:
    """Regression: api_key plaintext must never appear in any response."""
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome
    from datetime import datetime

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "m", "specified", "available", 1,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    client = TestClient(app)
    raw_key = "sk-SECRET-9999-DO-NOT-LEAK"
    client.post(
        "/api/endpoints",
        json={
            "name": "leakcheck",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
        },
    )
    payloads = [
        client.get("/api/endpoints").text,
        client.get("/api/endpoints/leakcheck").text,
        client.post("/api/endpoints/leakcheck/retest").text,
    ]
    for p in payloads:
        assert raw_key not in p, "api_key plaintext leaked!"
```

- [ ] **Step 3: Run tests — expect failure**

Run: `uv run pytest tests/test_api_parse.py tests/test_api_meta.py -q`
Expected: failures (routes not implemented).

- [ ] **Step 4: Implement parse-paste + settings**

Append to `src/llm_model_probe/api.py`:

```python
import json as _json
import re

_DOTENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$")
_BEARER = re.compile(r"Authorization:\s*Bearer\s+(\S+)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s'\"]+")


def _guess_sdk(base_url: str) -> SdkType:
    return "anthropic" if "anthropic" in base_url.lower() else "openai"


def _parse_json(blob: str) -> dict | None:
    try:
        obj = _json.loads(blob)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    out: dict = {}
    bu = obj.get("base_url") or obj.get("baseUrl") or obj.get("BASE_URL")
    if bu:
        out["base_url"] = str(bu).rstrip("/")
    ak = obj.get("api_key") or obj.get("apiKey") or obj.get("API_KEY")
    if ak:
        out["api_key"] = str(ak)
    if isinstance(obj.get("models"), list):
        out["models"] = [str(m) for m in obj["models"]]
    if obj.get("name"):
        out["name"] = str(obj["name"])
    if obj.get("sdk") in ("openai", "anthropic"):
        out["sdk"] = obj["sdk"]
    elif "base_url" in out:
        out["sdk"] = _guess_sdk(out["base_url"])
    return out or None


def _parse_curl(blob: str) -> dict | None:
    if "curl" not in blob.lower():
        return None
    out: dict = {}
    bearer = _BEARER.search(blob)
    if bearer:
        out["api_key"] = bearer.group(1).strip("\"'")
    url_match = _URL.search(blob)
    if url_match:
        url = url_match.group(0).rstrip(",;")
        # normalise: keep through /v1 if present; else origin
        if "/v1" in url:
            url = url.split("/v1", 1)[0] + "/v1"
        else:
            from urllib.parse import urlsplit
            sp = urlsplit(url)
            url = f"{sp.scheme}://{sp.netloc}"
        out["base_url"] = url
        out["sdk"] = _guess_sdk(url)
    return out or None


def _parse_dotenv(blob: str) -> dict | None:
    out: dict = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _DOTENV_LINE.match(line)
        if not m:
            continue
        key, raw = m.group(1).upper(), m.group(2).strip().strip("\"'")
        if "BASE_URL" in key or key.endswith("_URL") or key == "URL":
            out["base_url"] = raw.rstrip("/")
        elif "API_KEY" in key or key.endswith("_KEY") or key == "KEY":
            out["api_key"] = raw
    if out and "base_url" in out:
        out["sdk"] = _guess_sdk(out["base_url"])
    return out or None


@app.post("/api/parse-paste", response_model=PasteParseResponse)
def parse_paste(req: PasteParseRequest) -> PasteParseResponse:
    blob = req.blob.strip()
    for name, fn in (("json", _parse_json), ("curl", _parse_curl),
                     ("dotenv", _parse_dotenv)):
        result = fn(blob)
        if result and ("base_url" in result or "api_key" in result):
            # confidence: 1.0 if both, 0.6 if one
            both = "base_url" in result and "api_key" in result
            return PasteParseResponse(
                suggested=result,
                confidence=1.0 if both else 0.6,
                parser=name,  # type: ignore[arg-type]
            )
    return PasteParseResponse(suggested={}, confidence=0.0, parser="none")


@app.get("/api/settings")
def get_settings() -> dict:
    s = load_settings()
    return {
        "concurrency": s.concurrency,
        "timeout_seconds": s.timeout_seconds,
        "max_tokens": s.max_tokens,
        "prompt": s.prompt,
        "retest_cooldown_hours": s.retest_cooldown_hours,
        "exclude_patterns": s.exclude_patterns,
    }
```

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_parse.py tests/test_api_meta.py
git commit -m "feat(api): parse-paste + settings + key-leak regression"
```

---

## Task 6: `probe ui` CLI command

**Files:**
- Modify: `src/llm_model_probe/cli.py`

- [ ] **Step 1: Add `ui` command**

Append to `src/llm_model_probe/cli.py`:

```python
@app.command()
def ui(
    port: int = typer.Option(8765, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser"),
    dev: bool = typer.Option(
        False, "--dev",
        help="Dev mode: assume vite dev server at :5173, skip static mount",
    ),
) -> None:
    """Start the local web UI."""
    import os
    import webbrowser
    from pathlib import Path

    import uvicorn

    if dev:
        os.environ["LLM_MODEL_PROBE_DEV"] = "1"
    else:
        # In production mode, frontend/dist must exist
        pkg_root = Path(__file__).resolve().parents[2]
        dist = pkg_root / "frontend" / "dist"
        if not dist.exists():
            console.print(
                "[red]✗[/red] frontend not built. Run:\n"
                "    cd frontend && npm install && npm run build\n"
                "Or use --dev with `npm run dev` running on :5173."
            )
            raise typer.Exit(1)
        os.environ["LLM_MODEL_PROBE_DIST"] = str(dist)

    url = f"http://localhost:{port}"
    console.print(f"[green]→[/green] {url}")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run("llm_model_probe.api:app", host="127.0.0.1", port=port)
```

- [ ] **Step 2: Add static mount in api.py**

Modify `src/llm_model_probe/api.py`. Append at the very end:

```python
# Static frontend (production / docker)
_DIST = os.environ.get("LLM_MODEL_PROBE_DIST")
if _DIST and not DEV_MODE:
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path as _Path

    _dist_path = _Path(_DIST)
    if _dist_path.exists():
        app.mount("/", StaticFiles(directory=_dist_path, html=True), name="static")
```

- [ ] **Step 3: Smoke test the CLI command**

Run: `uv run probe ui --help`
Expected: shows `--port`, `--no-browser`, `--dev` options.

Run: `uv run probe ui --no-browser --dev --port 8765 &`
Wait 1s, then: `curl -s http://localhost:8765/api/health`
Expected: `{"ok":true}`.
Kill the background process: `kill %1` (or `pkill -f "uvicorn.*8765"`).

- [ ] **Step 4: Commit**

```bash
git add src/llm_model_probe/cli.py src/llm_model_probe/api.py
git commit -m "feat(cli): probe ui 命令 + 静态前端挂载"
```

---

## Task 7: Frontend bootstrap (Vite + TS + Tailwind)

**Files:**
- Create: `frontend/` (whole tree)
- Modify: `.gitignore`, `.dockerignore` (will be created later)

- [ ] **Step 1: Init Vite project**

```bash
cd ~/Code/Tools/llm-model-probe
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Install Tailwind**

```bash
cd ~/Code/Tools/llm-model-probe/frontend
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
```

Edit `frontend/tailwind.config.js` (or `.ts` if generated as such) — replace with:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

Replace `frontend/src/index.css` with:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 3: Configure Vite proxy + path alias**

Replace `frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
    },
  },
});
```

Modify `frontend/tsconfig.app.json` — add to `compilerOptions`:

```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 4: Update .gitignore for frontend**

Append to `~/Code/Tools/llm-model-probe/.gitignore`:

```
# frontend
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 5: Smoke run**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run dev
```

Open http://localhost:5173 — Vite default React page should render.
`Ctrl+C` to stop.

- [ ] **Step 6: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add .gitignore frontend/
git commit -m "feat(frontend): Vite + TS + Tailwind 脚手架"
```

---

## Task 8: shadcn/ui + react-query + api lib

**Files:**
- Create: `frontend/components.json`, `frontend/src/lib/utils.ts`, `frontend/src/components/ui/*`
- Create: `frontend/src/lib/{types.ts,api.ts,format.ts,parsePaste.ts}`

- [ ] **Step 1: Install shadcn deps + react-query**

```bash
cd ~/Code/Tools/llm-model-probe/frontend
npm install class-variance-authority clsx tailwind-merge lucide-react
npm install @tanstack/react-query
npm install -D @types/node
```

- [ ] **Step 2: Init shadcn manually (no CLI scaffold to keep deps minimal)**

Create `frontend/src/lib/utils.ts`:

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

Create `frontend/components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "src/index.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils"
  }
}
```

Update `frontend/tailwind.config.js` to include shadcn theme tokens:

```js
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
    },
  },
  plugins: [],
};
```

Replace `frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 0 0% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 0 0% 3.9%;
    --primary: 0 0% 9%;
    --primary-foreground: 0 0% 98%;
    --muted: 0 0% 96.1%;
    --muted-foreground: 0 0% 45.1%;
    --accent: 0 0% 96.1%;
    --accent-foreground: 0 0% 9%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 0 0% 98%;
    --border: 0 0% 89.8%;
    --input: 0 0% 89.8%;
    --ring: 0 0% 3.9%;
  }
  .dark {
    --background: 0 0% 3.9%;
    --foreground: 0 0% 98%;
    --card: 0 0% 3.9%;
    --card-foreground: 0 0% 98%;
    --primary: 0 0% 98%;
    --primary-foreground: 0 0% 9%;
    --muted: 0 0% 14.9%;
    --muted-foreground: 0 0% 63.9%;
    --accent: 0 0% 14.9%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 0 0% 98%;
    --border: 0 0% 14.9%;
    --input: 0 0% 14.9%;
    --ring: 0 0% 83.1%;
  }
}

@layer base {
  * { @apply border-border; }
  body { @apply bg-background text-foreground; }
}
```

- [ ] **Step 3: Use shadcn CLI to add the actual components we need**

```bash
cd ~/Code/Tools/llm-model-probe/frontend
npx shadcn@latest add button table dialog input textarea label badge sheet alert
```

(If prompted for confirmations, accept defaults.)

This populates `frontend/src/components/ui/{button,table,dialog,input,textarea,label,badge,sheet,alert}.tsx`.

- [ ] **Step 4: Create types + api lib**

Create `frontend/src/lib/types.ts`:

```ts
export type Sdk = "openai" | "anthropic";
export type Mode = "discover" | "specified";
export type Status = "available" | "failed";

export interface EndpointSummary {
  id: string;
  name: string;
  sdk: Sdk;
  base_url: string;
  mode: Mode;
  note: string;
  list_error: string | null;
  available: number;
  failed: number;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModelResultPublic {
  model_id: string;
  source: "discovered" | "specified";
  status: Status;
  latency_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  response_preview: string | null;
  last_tested_at: string | null;
}

export interface EndpointDetail extends EndpointSummary {
  api_key_masked: string;
  models: string[];
  results: ModelResultPublic[];
}

export interface EndpointCreate {
  name: string;
  sdk: Sdk;
  base_url: string;
  api_key: string;
  models?: string[];
  note?: string;
  no_probe?: boolean;
}

export interface PasteSuggestion {
  suggested: Partial<EndpointCreate>;
  confidence: number;
  parser: "json" | "dotenv" | "curl" | "none";
}
```

Create `frontend/src/lib/api.ts`:

```ts
import type { EndpointSummary, EndpointDetail, EndpointCreate, PasteSuggestion } from "./types";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch {}
    throw new Error(`${r.status} ${detail}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  listEndpoints: () => req<EndpointSummary[]>("GET", "/api/endpoints"),
  getEndpoint: (idOrName: string) =>
    req<EndpointDetail>("GET", `/api/endpoints/${encodeURIComponent(idOrName)}`),
  createEndpoint: (payload: EndpointCreate) =>
    req<EndpointDetail>("POST", "/api/endpoints", payload),
  deleteEndpoint: (id: string) =>
    req<void>("DELETE", `/api/endpoints/${encodeURIComponent(id)}`),
  retestEndpoint: (id: string) =>
    req<EndpointDetail>("POST", `/api/endpoints/${encodeURIComponent(id)}/retest`),
  retestAll: () => req<{ retested: number }>("POST", "/api/retest-all"),
  parsePaste: (blob: string) =>
    req<PasteSuggestion>("POST", "/api/parse-paste", { blob }),
};
```

Create `frontend/src/lib/format.ts`:

```ts
export function relative(when: string | null): string {
  if (!when) return "never";
  const seconds = Math.floor((Date.now() - new Date(when).getTime()) / 1000);
  if (seconds < 30) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}
```

Create `frontend/src/lib/parsePaste.ts`:

```ts
import type { EndpointCreate } from "./types";

type Suggestion = Partial<EndpointCreate> & { confidence: number; parser: string };

const URL_RE = /https?:\/\/[^\s'"]+/i;
const BEARER_RE = /Authorization:\s*Bearer\s+(\S+)/i;
const KV_RE = /^([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$/;

function guessSdk(url: string): "openai" | "anthropic" {
  return url.toLowerCase().includes("anthropic") ? "anthropic" : "openai";
}

function tryJson(blob: string): Suggestion | null {
  try {
    const obj = JSON.parse(blob);
    if (typeof obj !== "object" || obj === null) return null;
    const out: Suggestion = { confidence: 0, parser: "json" };
    const bu = obj.base_url ?? obj.baseUrl ?? obj.BASE_URL;
    if (bu) out.base_url = String(bu).replace(/\/+$/, "");
    const ak = obj.api_key ?? obj.apiKey ?? obj.API_KEY;
    if (ak) out.api_key = String(ak);
    if (Array.isArray(obj.models)) out.models = obj.models.map(String);
    if (obj.name) out.name = String(obj.name);
    if (obj.sdk === "openai" || obj.sdk === "anthropic") out.sdk = obj.sdk;
    else if (out.base_url) out.sdk = guessSdk(out.base_url);
    if (!out.base_url && !out.api_key) return null;
    out.confidence = (out.base_url && out.api_key) ? 1 : 0.6;
    return out;
  } catch { return null; }
}

function tryCurl(blob: string): Suggestion | null {
  if (!blob.toLowerCase().includes("curl")) return null;
  const out: Suggestion = { confidence: 0, parser: "curl" };
  const b = blob.match(BEARER_RE);
  if (b) out.api_key = b[1].replace(/^['"]|['"]$/g, "");
  const u = blob.match(URL_RE);
  if (u) {
    let url = u[0].replace(/[,;]+$/, "");
    if (url.includes("/v1")) {
      url = url.split("/v1")[0] + "/v1";
    } else {
      try {
        const parsed = new URL(url);
        url = `${parsed.protocol}//${parsed.host}`;
      } catch {}
    }
    out.base_url = url;
    out.sdk = guessSdk(url);
  }
  if (!out.base_url && !out.api_key) return null;
  out.confidence = (out.base_url && out.api_key) ? 1 : 0.6;
  return out;
}

function tryDotenv(blob: string): Suggestion | null {
  const out: Suggestion = { confidence: 0, parser: "dotenv" };
  for (const raw of blob.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(KV_RE);
    if (!m) continue;
    const key = m[1].toUpperCase();
    const val = m[2].trim().replace(/^['"]|['"]$/g, "");
    if (key.includes("BASE_URL") || key === "URL" || key.endsWith("_URL"))
      out.base_url = val.replace(/\/+$/, "");
    else if (key.includes("API_KEY") || key === "KEY" || key.endsWith("_KEY"))
      out.api_key = val;
  }
  if (!out.base_url && !out.api_key) return null;
  if (out.base_url) out.sdk = guessSdk(out.base_url);
  out.confidence = (out.base_url && out.api_key) ? 1 : 0.6;
  return out;
}

export function parseLocally(blob: string): Suggestion {
  const trimmed = blob.trim();
  return tryJson(trimmed) ?? tryCurl(trimmed) ?? tryDotenv(trimmed)
    ?? { confidence: 0, parser: "none" };
}
```

- [ ] **Step 5: Set up react-query provider in main.tsx**

Replace `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Smoke verify build still works**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Expected: build succeeds without TS errors. (The default App.tsx still imports the original Vite logo etc. — that's fine, we'll replace next task.)

- [ ] **Step 7: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/
git commit -m "feat(frontend): shadcn/ui + react-query + api/types/parse libs"
```

---

## Task 9: EndpointTable + App layout

**Files:**
- Replace: `frontend/src/App.tsx`
- Create: `frontend/src/components/EndpointTable.tsx`

- [ ] **Step 1: Replace App.tsx**

Overwrite `frontend/src/App.tsx`:

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";

export default function App() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const retestAll = useMutation({
    mutationFn: api.retestAll,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">llm-model-probe</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={retestAll.isPending}
            onClick={() => retestAll.mutate()}
          >
            {retestAll.isPending ? "Retesting…" : "↻ Retest all"}
          </Button>
          <Button onClick={() => setShowAdd(true)}>+ Add endpoint</Button>
        </div>
      </div>

      {list.isLoading && <div className="text-muted-foreground">Loading…</div>}
      {list.error && (
        <div className="text-destructive">Error: {String(list.error)}</div>
      )}
      {list.data && <EndpointTable endpoints={list.data} />}

      {/* AddEndpointDialog wired in next task */}
      {showAdd && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center"
          onClick={() => setShowAdd(false)}
        >
          <div className="bg-card p-4 rounded-md" onClick={(e) => e.stopPropagation()}>
            <p>Add dialog placeholder — implemented in Task 10.</p>
            <Button onClick={() => setShowAdd(false)}>Close</Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create EndpointTable**

Create `frontend/src/components/EndpointTable.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { relative } from "@/lib/format";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function EndpointTable({ endpoints }: { endpoints: EndpointSummary[] }) {
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const retest = useMutation({
    mutationFn: (id: string) => api.retestEndpoint(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => {
      setBusyId(null);
      qc.invalidateQueries({ queryKey: ["endpoints"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteEndpoint(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });

  if (endpoints.length === 0) {
    return (
      <div className="text-muted-foreground p-8 text-center border rounded-md">
        No endpoints yet. Click <strong>+ Add endpoint</strong>.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-28">ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>SDK</TableHead>
          <TableHead>Mode</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Tested</TableHead>
          <TableHead>Note</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {endpoints.map((ep) => (
          <TableRow key={ep.id}>
            <TableCell className="font-mono text-xs text-muted-foreground">{ep.id}</TableCell>
            <TableCell className="font-medium">{ep.name}</TableCell>
            <TableCell>{ep.sdk}</TableCell>
            <TableCell>{ep.mode}</TableCell>
            <TableCell>
              {ep.list_error ? (
                <Badge variant="destructive">list-error</Badge>
              ) : ep.available + ep.failed === 0 ? (
                <span className="text-muted-foreground">not probed</span>
              ) : (
                <span>
                  <span className="text-green-600">{ep.available}</span>
                  /<span className="text-destructive">{ep.failed}</span>
                </span>
              )}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {relative(ep.last_tested_at)}
            </TableCell>
            <TableCell className="text-muted-foreground max-w-[200px] truncate">
              {ep.note}
            </TableCell>
            <TableCell className="text-right space-x-1">
              <Button
                size="sm"
                variant="outline"
                disabled={busyId === ep.id || retest.isPending}
                onClick={() => retest.mutate(ep.id)}
              >
                {busyId === ep.id ? "…" : "↻"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (confirm(`Delete '${ep.name}'?`)) remove.mutate(ep.id);
                }}
              >
                ✕
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 3: Smoke test**

In one terminal:

```bash
cd ~/Code/Tools/llm-model-probe
export LLM_MODEL_PROBE_HOME=$(mktemp -d)/probe-home
uv run probe ui --dev --no-browser --port 8765
```

In another terminal:

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run dev
```

Open http://localhost:5173. Expected: empty state ("No endpoints yet").

Stop both processes, clean up: `rm -rf "$LLM_MODEL_PROBE_HOME"`.

- [ ] **Step 4: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/App.tsx frontend/src/components/EndpointTable.tsx
git commit -m "feat(frontend): EndpointTable + 主页面骨架"
```

---

## Task 10: AddEndpointDialog with form

**Files:**
- Create: `frontend/src/components/AddEndpointDialog.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create AddEndpointDialog (form, no smart paste yet)**

Create `frontend/src/components/AddEndpointDialog.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointCreate } from "@/lib/types";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const empty: EndpointCreate = {
  name: "",
  sdk: "openai",
  base_url: "",
  api_key: "",
  models: [],
  note: "",
};

export default function AddEndpointDialog({
  open, onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<EndpointCreate>(empty);
  const [modelsText, setModelsText] = useState("");

  const create = useMutation({
    mutationFn: (payload: EndpointCreate) => api.createEndpoint(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      setForm(empty);
      setModelsText("");
      onClose();
    },
  });

  function submit() {
    const models = modelsText
      .split(",").map((s) => s.trim()).filter(Boolean);
    create.mutate({ ...form, models });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Add endpoint</DialogTitle></DialogHeader>

        <div className="space-y-3 py-2">
          <Field label="Name">
            <Input value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="SDK">
            <select className="w-full border rounded-md px-2 h-9 bg-background"
              value={form.sdk}
              onChange={(e) => setForm({ ...form, sdk: e.target.value as "openai" | "anthropic" })}>
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
            </select>
          </Field>
          <Field label="Base URL">
            <Input placeholder="https://api.example.com/v1" value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          </Field>
          <Field label="API key">
            <Input type="password" value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </Field>
          <Field label="Models (comma-separated, leave empty for auto-discover)">
            <Input value={modelsText} placeholder="gpt-4, gpt-3.5-turbo"
              onChange={(e) => setModelsText(e.target.value)} />
          </Field>
          <Field label="Note">
            <Input value={form.note ?? ""}
              onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Field>

          {create.error && (
            <div className="text-sm text-destructive">
              {String(create.error)}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={create.isPending || !form.name || !form.base_url || !form.api_key}>
            {create.isPending ? "Adding…" : "Add & Probe"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Wire dialog into App.tsx**

Replace the placeholder block in `frontend/src/App.tsx`. Change:

```tsx
{/* AddEndpointDialog wired in next task */}
{showAdd && (
  <div ...>...</div>
)}
```

to:

```tsx
<AddEndpointDialog open={showAdd} onClose={() => setShowAdd(false)} />
```

And add the import at the top of `App.tsx`:

```tsx
import AddEndpointDialog from "@/components/AddEndpointDialog";
```

- [ ] **Step 3: Smoke test (manual)**

Start backend (with isolated home) + frontend dev server (as in Task 9 Step 3).
Click "+ Add endpoint", fill the form (use a fake `--no-probe`-ish workflow by
ticking models to skip real probing... actually we can't here — for smoke it's
OK if probe fails, we just want to see UI behavior).

To avoid network: temporarily set Models = `m1, m2` (specified mode) and the
backend will try to probe `m1` and `m2`. Both will fail with connection error;
that's OK — we just want to see endpoint added. After ~30s the dialog closes and
the row appears with `0/2`.

Stop processes.

- [ ] **Step 4: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/components/AddEndpointDialog.tsx frontend/src/App.tsx
git commit -m "feat(frontend): AddEndpointDialog 表单"
```

---

## Task 11: SmartPasteArea (client-side parser + server fallback)

**Files:**
- Create: `frontend/src/components/SmartPasteArea.tsx`
- Modify: `frontend/src/components/AddEndpointDialog.tsx`

- [ ] **Step 1: Create SmartPasteArea**

Create `frontend/src/components/SmartPasteArea.tsx`:

```tsx
import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { parseLocally } from "@/lib/parsePaste";
import type { EndpointCreate } from "@/lib/types";

export default function SmartPasteArea({
  onApply,
}: {
  onApply: (suggestion: Partial<EndpointCreate>) => void;
}) {
  const [text, setText] = useState("");
  const [parser, setParser] = useState<string>("");
  const [confidence, setConfidence] = useState<number>(0);
  const [suggested, setSuggested] = useState<Partial<EndpointCreate>>({});
  const [busy, setBusy] = useState(false);

  async function reparse(value: string) {
    if (!value.trim()) {
      setParser(""); setConfidence(0); setSuggested({}); return;
    }
    const local = parseLocally(value);
    if (local.confidence >= 0.5) {
      const { confidence, parser, ...rest } = local;
      setParser(parser); setConfidence(confidence); setSuggested(rest);
      return;
    }
    setBusy(true);
    try {
      const remote = await api.parsePaste(value);
      setParser(remote.parser);
      setConfidence(remote.confidence);
      setSuggested(remote.suggested);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-2 border rounded-md p-3 bg-muted/30">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Smart paste</span>
        {parser && (
          <Badge variant={confidence >= 0.9 ? "default" : "secondary"}>
            {parser}{busy && "…"}
          </Badge>
        )}
      </div>
      <Textarea
        rows={5}
        placeholder={
          'Paste a JSON like {"base_url":"...","api_key":"..."}\n' +
          "or dotenv: OPENAI_BASE_URL=...\\nOPENAI_API_KEY=...\n" +
          "or a curl command with Authorization: Bearer ..."
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => reparse(text)}
      />
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={!parser || parser === "none"}
          onClick={() => onApply(suggested)}
        >
          Apply to form
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire SmartPasteArea into AddEndpointDialog**

Modify `frontend/src/components/AddEndpointDialog.tsx`. After the `<DialogHeader>` block, **before** the `<div className="space-y-3 py-2">` form fields, insert:

```tsx
<SmartPasteArea onApply={(s) => {
  setForm((f) => ({
    ...f,
    name: s.name ?? f.name,
    sdk: s.sdk ?? f.sdk,
    base_url: s.base_url ?? f.base_url,
    api_key: s.api_key ?? f.api_key,
    note: s.note ?? f.note,
  }));
  if (s.models && s.models.length) setModelsText(s.models.join(", "));
}} />
```

Add the import at the top:

```tsx
import SmartPasteArea from "./SmartPasteArea";
```

- [ ] **Step 3: Smoke test the paste flow**

Start backend + frontend (as before). Open Add dialog. In the smart paste textarea, paste:

```
{"base_url": "https://api.openai.com/v1", "api_key": "sk-test"}
```

Tab out of the textarea (triggers blur). The badge should show `json` and "Apply to form" should populate the fields above.

Try also:
```
OPENAI_BASE_URL=https://api.example.com/v1
OPENAI_API_KEY=sk-abc123
```
Badge should show `dotenv`.

- [ ] **Step 4: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/components/SmartPasteArea.tsx frontend/src/components/AddEndpointDialog.tsx
git commit -m "feat(frontend): SmartPasteArea 智能粘贴 + 自动填表"
```

---

## Task 12: EndpointDetailDrawer (row click → side drawer)

**Files:**
- Create: `frontend/src/components/EndpointDetailDrawer.tsx`
- Modify: `frontend/src/components/EndpointTable.tsx`, `frontend/src/App.tsx`

- [ ] **Step 1: Create drawer**

Create `frontend/src/components/EndpointDetailDrawer.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { relative } from "@/lib/format";

export default function EndpointDetailDrawer({
  idOrName, onClose,
}: {
  idOrName: string | null;
  onClose: () => void;
}) {
  const open = idOrName !== null;
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName!),
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{detail.data?.name ?? "…"}</SheetTitle>
        </SheetHeader>

        {detail.isLoading && <div className="py-4 text-muted-foreground">Loading…</div>}
        {detail.data && (() => {
          const d = detail.data;
          const ok = d.results.filter(r => r.status === "available");
          const fail = d.results.filter(r => r.status === "failed");
          return (
            <div className="space-y-4 py-4 text-sm">
              <div className="space-y-1">
                <Row label="ID">{d.id}</Row>
                <Row label="SDK">{d.sdk}</Row>
                <Row label="URL"><code>{d.base_url}</code></Row>
                <Row label="API key"><code>{d.api_key_masked}</code></Row>
                <Row label="Mode">{d.mode}</Row>
                {d.note && <Row label="Note">{d.note}</Row>}
                <Row label="Last tested">{relative(d.last_tested_at)}</Row>
                {d.list_error && (
                  <Row label="List error">
                    <Badge variant="destructive">{d.list_error}</Badge>
                  </Row>
                )}
              </div>

              {ok.length > 0 && (
                <div>
                  <h3 className="font-semibold mb-2 text-green-700">
                    Available ({ok.length})
                  </h3>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="py-1">Model</th>
                        <th className="py-1">Latency</th>
                        <th className="py-1">Preview</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ok.map((r) => (
                        <tr key={r.model_id} className="border-t">
                          <td className="py-1 font-mono">{r.model_id}</td>
                          <td className="py-1">{r.latency_ms} ms</td>
                          <td className="py-1 text-muted-foreground">{r.response_preview}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {fail.length > 0 && (
                <div>
                  <h3 className="font-semibold mb-2 text-destructive">
                    Failed ({fail.length})
                  </h3>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="py-1">Model</th>
                        <th className="py-1">Error</th>
                        <th className="py-1">Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fail.map((r) => (
                        <tr key={r.model_id} className="border-t">
                          <td className="py-1 font-mono">{r.model_id}</td>
                          <td className="py-1">{r.error_type}</td>
                          <td className="py-1 text-muted-foreground truncate max-w-xs">
                            {r.error_message}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })()}
      </SheetContent>
    </Sheet>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
```

- [ ] **Step 2: Make rows clickable in EndpointTable**

Modify `frontend/src/components/EndpointTable.tsx`:

Change the prop signature:

```tsx
export default function EndpointTable({
  endpoints, onSelect,
}: {
  endpoints: EndpointSummary[];
  onSelect: (idOrName: string) => void;
}) {
```

Change the `<TableRow key={ep.id}>` to:

```tsx
<TableRow
  key={ep.id}
  className="cursor-pointer hover:bg-muted/50"
  onClick={() => onSelect(ep.id)}
>
```

Wrap each interactive cell action so row click doesn't trigger when clicking the action buttons. Replace the actions cell with:

```tsx
<TableCell className="text-right space-x-1" onClick={(e) => e.stopPropagation()}>
  <Button
    size="sm"
    variant="outline"
    disabled={busyId === ep.id || retest.isPending}
    onClick={() => retest.mutate(ep.id)}
  >
    {busyId === ep.id ? "…" : "↻"}
  </Button>
  <Button
    size="sm"
    variant="ghost"
    onClick={() => {
      if (confirm(`Delete '${ep.name}'?`)) remove.mutate(ep.id);
    }}
  >
    ✕
  </Button>
</TableCell>
```

- [ ] **Step 3: Wire drawer into App.tsx**

Modify `frontend/src/App.tsx`:

Add state:

```tsx
const [selected, setSelected] = useState<string | null>(null);
```

Pass to table:

```tsx
{list.data && <EndpointTable endpoints={list.data} onSelect={setSelected} />}
```

Add drawer at the bottom (before the closing `</div>`):

```tsx
<EndpointDetailDrawer idOrName={selected} onClose={() => setSelected(null)} />
```

Add import:

```tsx
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";
```

- [ ] **Step 4: Smoke test**

Start backend + frontend. Add an endpoint (any real or specified-fake one). Click its row — drawer opens with details. Close drawer. Click retest button — should not open drawer. Click delete button — should confirm + remove.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/components/EndpointDetailDrawer.tsx frontend/src/components/EndpointTable.tsx frontend/src/App.tsx
git commit -m "feat(frontend): 行点击展开详情 drawer"
```

---

## Task 13: Production build wiring + final smoke

**Files:**
- (No new files; verify the existing pieces work end-to-end in production mode)

- [ ] **Step 1: Build the frontend**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Expected: outputs `frontend/dist/` with `index.html`, `assets/...`.

- [ ] **Step 2: Run production mode end-to-end**

```bash
cd ~/Code/Tools/llm-model-probe
export LLM_MODEL_PROBE_HOME="$(mktemp -d)/probe-home"
uv run probe ui --no-browser --port 8765 &
sleep 1
curl -s http://localhost:8765/api/health
curl -sI http://localhost:8765/ | head -1   # expect 200 with text/html
```

Expected: `{"ok":true}` from /api/health and `200 OK` from `/` (serving index.html).

Open http://localhost:8765 in a browser → fully working SPA, identical to dev mode.

Kill: `pkill -f "uvicorn.*8765"; rm -rf "$LLM_MODEL_PROBE_HOME"`.

- [ ] **Step 3: Run the full backend test suite**

```bash
cd ~/Code/Tools/llm-model-probe && uv run pytest -q
```

Expected: all green.

- [ ] **Step 4: Commit (if anything changed)**

If `npm run build` modified `package-lock.json` etc. and that wasn't already
committed, commit the lockfile:

```bash
git add frontend/package-lock.json
git commit -m "chore(frontend): 锁定 package-lock 验证生产构建" || true
```

(`|| true` because there might be nothing to commit.)

---

## Task 14: Dockerfile + docker-compose

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`

- [ ] **Step 1: Create .dockerignore**

Create `~/Code/Tools/llm-model-probe/.dockerignore`:

```
.git
.venv
__pycache__
*.pyc
frontend/node_modules
frontend/dist
docs/
.claude/
tests/
*.md
```

- [ ] **Step 2: Create Dockerfile**

Create `~/Code/Tools/llm-model-probe/Dockerfile`:

```dockerfile
# Stage 1: build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: backend + static files
FROM python:3.11-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV LLM_MODEL_PROBE_HOME=/data
ENV LLM_MODEL_PROBE_DIST=/app/frontend/dist
EXPOSE 8765
CMD ["uv", "run", "uvicorn", "llm_model_probe.api:app", "--host", "0.0.0.0", "--port", "8765"]
```

- [ ] **Step 3: Create docker-compose.yml**

Create `~/Code/Tools/llm-model-probe/docker-compose.yml`:

```yaml
services:
  probe:
    build: .
    image: llm-model-probe:latest
    container_name: llm-model-probe
    ports:
      - "8765:8765"
    volumes:
      - ${HOME}/.llm-model-probe:/data
    restart: unless-stopped
```

- [ ] **Step 4: Build + smoke test docker (skip if no Docker on machine)**

```bash
cd ~/Code/Tools/llm-model-probe
docker build -t llm-model-probe:test . 2>&1 | tail -5
```

If Docker isn't installed, skip this step and document in the README that
Dockerfile is shipped untested. If installed:

```bash
docker run --rm -d -p 8765:8765 -v "$HOME/.llm-model-probe:/data" \
  --name probe-smoke llm-model-probe:test
sleep 2
curl -s http://localhost:8765/api/health
docker stop probe-smoke
```

Expected: `{"ok":true}`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat(docker): 多阶段 Dockerfile + compose"
```

---

## Task 15: README updates + final cleanup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append UI + Docker sections to README**

Read current `README.md`. Insert a new section before the existing `## Project Layout` section:

```markdown
## Web UI

For a copy-paste friendly management page:

```bash
# 1. Build frontend (one time, or when frontend/ changes)
cd frontend && npm install && npm run build && cd ..

# 2. Launch
probe ui                # opens browser at http://localhost:8765
```

Dev mode (hot reload):

```bash
# Terminal 1: backend
probe ui --dev --no-browser

# Terminal 2: frontend
cd frontend && npm run dev
# open http://localhost:5173
```

Features:
- **Smart paste**: drop a JSON, dotenv block, or curl command into the Add dialog
  and it auto-fills the form.
- One-click retest / delete per row.
- "Retest all" button (blocks until done; no progress streaming v1).
- Detail drawer shows model-level status with masked API key.

UI is local-only (binds to 127.0.0.1). API keys are stored in the same SQLite
file as the CLI; both share `~/.llm-model-probe/probes.db`.

## Docker

```bash
docker compose up -d --build
# UI on http://localhost:8765
# DB volume mounted from host ~/.llm-model-probe
```
```

- [ ] **Step 2: Update Project Layout in README**

Replace the existing "## Project Layout" block with:

```markdown
## Project Layout

```
src/llm_model_probe/
  paths.py     # ~/.llm-model-probe resolution
  settings.py  # config.toml loader
  models.py    # Endpoint, ModelResult dataclasses
  store.py     # SQLite layer
  providers.py # async OpenAI/Anthropic SDK wrappers
  probe.py     # ProbeRunner: list/filter/probe orchestration
  report.py    # rich tables + markdown + json
  cli.py       # typer commands (add/list/show/retest/rm/export/ui)
  api.py       # FastAPI app for the web UI
frontend/      # Vite + TS + Tailwind + shadcn/ui SPA
docs/
  specs/       # design docs
  plans/       # implementation plans
tests/         # pytest suite (backend incl. API)
Dockerfile
docker-compose.yml
```
```

- [ ] **Step 3: Final sanity run**

```bash
cd ~/Code/Tools/llm-model-probe
uv run pytest -q                           # backend tests
uv run probe --help                        # CLI listing all 7 commands
ls frontend/dist/index.html                # frontend built
```

Expected: tests pass, CLI lists `add list show retest rm export ui`, dist exists.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README 增补 UI + Docker 使用"
```

---

## Self-Review (post-write)

**Spec coverage** (against `docs/specs/2026-05-01-ui-design.md`):

- ✅ Goal + Non-Goals — UI builds on existing CLI, blocks on retest, no auth, no edit (Task 3/4 + plan-wide).
- ✅ Architecture — FastAPI in api.py, React in frontend/, both share store via SQLite.
- ✅ All 9 REST endpoints — covered Tasks 1–5.
- ✅ Pydantic schemas — Task 1.
- ✅ api_key never returned in plain — Task 5 has explicit regression test.
- ✅ Frontend project layout — Task 7 sets it up; Tasks 8–12 fill components/lib.
- ✅ shadcn/ui + react-query + Tailwind — Tasks 7 + 8.
- ✅ Smart paste with 3 parsers + server fallback — Task 11 (UI) + Task 5 (server).
- ✅ Single page, drawer for detail, dialog for add — Tasks 9–12.
- ✅ `probe ui` + `--dev` + `--no-browser` — Task 6.
- ✅ Static mount in production — Task 6 (api.py change).
- ✅ Dockerfile multi-stage + compose with HOME volume — Task 14.
- ✅ Tests: API contract + parse + key-leak — Tasks 2, 3, 4, 5.
- ✅ README updates — Task 15.

**Placeholder scan**: no TBD/TODO; every code step shows full code; no "similar to Task N".

**Type/name consistency**:
- `EndpointCreate` / `EndpointSummary` / `EndpointDetail` / `ModelResultPublic` / `PasteParseRequest` / `PasteParseResponse` consistent across api.py + types.ts.
- `api.listEndpoints / getEndpoint / createEndpoint / deleteEndpoint / retestEndpoint / retestAll / parsePaste` consistent across api.ts and component callers.
- `mask_api_key` reused from existing `report.py`.
- `EndpointStore` methods (`get_endpoint`, `summary`, `last_tested_at`, etc.) match what the CLI tasks set up in the previous plan.

**Test isolation**: All API tests rely on the existing `isolated_home` fixture (defined in `tests/conftest.py` from the original plan). FastAPI `TestClient` doesn't bypass this — `_store()` calls `EndpointStore()` which respects `LLM_MODEL_PROBE_HOME`.

Plan is ready for execution.

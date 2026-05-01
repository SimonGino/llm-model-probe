# Probe UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the discover-then-test redesign described in `docs/specs/2026-05-02-probe-redesign-design.md`: split add/probe into two phases, add a per-model probe API, and rewrite the drawer + table to orchestrate probes from the frontend with live progress.

**Architecture:** Backend gains one new endpoint (`POST /api/endpoints/{id}/probe-model`) and adjusts `POST /api/endpoints` so `no_probe=true` discovers without probing. Frontend gets a shared probe orchestrator hook (concurrency=5 promise pool), a rewritten drawer with checkbox/Test-all UI, and an updated table whose row retest and "Retest all" button both go through the orchestrator. CLI is untouched.

**Tech Stack:** FastAPI/Pydantic, pytest+httpx for backend; React + react-query + shadcn/ui for frontend.

---

## File Structure

```
src/llm_model_probe/
├── api.py                              # MODIFY: schemas + create flow + new probe-model route

tests/
├── test_api_endpoints.py                # MODIFY: new tests for discover-no-probe + probe-model

frontend/src/
├── lib/
│   ├── types.ts                         # MODIFY: total_models, excluded_by_filter
│   ├── api.ts                           # MODIFY: probeModel method
│   └── orchestrator.ts                  # NEW: useProbeOrchestrator hook (p-limit + state)
└── components/
    ├── AddEndpointDialog.tsx            # MODIFY: no_probe=true always; onCreated callback
    ├── EndpointDetailDrawer.tsx         # REWRITE: interactive model list
    ├── EndpointTable.tsx                # MODIFY: row ↻ via orchestrator; new summary cell
    └── App.tsx                          # MODIFY: thread autoTest flag + orchestrator
```

No new files on the backend. One small new file on the frontend (`orchestrator.ts`).

---

## Task 1: Backend — discover-on-add + new summary/detail fields

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Modify: `tests/test_api_endpoints.py`

- [ ] **Step 1: Add `total_models` and `excluded_by_filter` to schemas**

In `src/llm_model_probe/api.py`, modify the `EndpointSummary` and
`EndpointDetail` classes:

```python
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
    total_models: int                     # NEW
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EndpointDetail(EndpointSummary):
    api_key_masked: str
    models: list[str]
    excluded_by_filter: list[str]         # NEW
    results: list[ModelResultPublic]
```

Then update `_summary` to populate `total_models`:

```python
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
        total_models=len(ep.models),
        last_tested_at=store.last_tested_at(ep.id),
        created_at=ep.created_at or datetime.now(),
        updated_at=ep.updated_at or datetime.now(),
    )
```

And update `_detail` to compute `excluded_by_filter`:

```python
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
    if ep.mode == "discover":
        from .probe import filter_models
        s = load_settings()
        _kept, skipped = filter_models(ep.models, s.exclude_patterns)
        excluded = skipped
    else:
        excluded = []
    return EndpointDetail(
        **summary.model_dump(),
        api_key_masked=mask_api_key(ep.api_key),
        models=ep.models,
        excluded_by_filter=excluded,
        results=results,
    )
```

- [ ] **Step 2: Modify `create_endpoint` to discover when `no_probe=true` in discover mode**

Replace the body of `create_endpoint` in `src/llm_model_probe/api.py`:

```python
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

    if payload.no_probe:
        # UI path: discover (or accept specified) but do not probe.
        if mode == "discover":
            from .providers import make_provider
            settings = load_settings()
            provider = make_provider(ep, settings.timeout_seconds)
            try:
                discovered = asyncio.run(provider.list_models())
                # persist discovered list onto the endpoint
                ep.models = list(discovered)
                _persist_models(store, ep.id, discovered)
                store.set_list_error(ep.id, None)
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                store.set_list_error(ep.id, err)
            finally:
                asyncio.run(provider.aclose())
    else:
        # CLI path: full discover + probe (unchanged).
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

The helper `_persist_models` does not yet exist. Add it next to `_apply_outcome`
in `api.py`:

```python
def _persist_models(store: EndpointStore, ep_id: str, models: list[str]) -> None:
    """Update endpoints.models JSON column without touching results."""
    import json as _j
    import sqlite3
    with sqlite3.connect(store._path) as c:
        c.execute(
            "UPDATE endpoints SET models_json = ?, updated_at = ? WHERE id = ?",
            (_j.dumps(models), datetime.now().isoformat(timespec="seconds"), ep_id),
        )
        c.commit()
```

(Yes, this reaches into `store._path`. The store has no public method for
this single-column update; adding one is overkill. Document the access in the
helper's docstring.)

- [ ] **Step 3: Write failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_create_no_probe_discover_populates_models(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """no_probe=true in discover mode should call list_models() and persist
    the result onto endpoints.models — without probing."""
    from llm_model_probe import api as api_mod

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4", "gpt-3.5", "text-embedding-3"]

    monkeypatch.setattr(
        api_mod.make_provider.__wrapped__ if hasattr(api_mod.make_provider, "__wrapped__")
        else "llm_model_probe.providers.OpenAIProvider.list_models",
        fake_list_models,
        raising=False,
    )
    # The simpler path: monkeypatch the class method.
    from llm_model_probe.providers import OpenAIProvider
    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    r = client.post("/api/endpoints", json={
        "name": "discover-only",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-aaaa1111bbbb2222",
        "no_probe": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "discover"
    assert body["models"] == ["gpt-4", "gpt-3.5", "text-embedding-3"]
    assert body["results"] == []                            # no probing
    assert body["total_models"] == 3
    # text-embedding-3 should land in excluded_by_filter (default exclude pattern)
    assert "text-embedding-3" in body["excluded_by_filter"]
    assert "gpt-4" not in body["excluded_by_filter"]


def test_create_no_probe_discover_list_error(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    async def fail_list_models(self):  # noqa: ARG001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(OpenAIProvider, "list_models", fail_list_models)

    r = client.post("/api/endpoints", json={
        "name": "broken-discover",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-aaaa1111bbbb2222",
        "no_probe": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["models"] == []
    assert body["list_error"] is not None
    assert "kaboom" in body["list_error"]
    assert body["total_models"] == 0


def test_endpoint_summary_includes_total_models(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """total_models should reflect endpoints.models length."""
    ep = _seed_endpoint(seed_store, "with-models")
    # `_seed_endpoint` defaults to discover mode with empty models;
    # update via store helper to inject models.
    seed_store.delete_endpoint(ep.id)
    ep2 = Endpoint(
        id=new_endpoint_id(),
        name="counted",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-1234567890aaaa",
        mode="specified",
        models=["a", "b", "c"],
        note="",
    )
    seed_store.insert_endpoint(ep2)
    r = client.get("/api/endpoints")
    item = next(x for x in r.json() if x["name"] == "counted")
    assert item["total_models"] == 3
```

- [ ] **Step 4: Run tests — expect failure**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: 3 new failures (response missing fields, discover not running list_models).

- [ ] **Step 5: Run tests — expect pass after the code from Step 1+2**

Run: `uv run pytest -q`
Expected: all green (43 prior + 3 new = 46).

- [ ] **Step 6: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): no_probe=true 在 discover 模式下做发现 + total_models / excluded_by_filter"
```

---

## Task 2: Backend — `POST /api/endpoints/{id}/probe-model`

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Modify: `tests/test_api_endpoints.py`, `tests/test_api_meta.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_probe_model_writes_result(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /probe-model probes one model and stores its row."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    # Seed an endpoint via API so endpoints.models is set
    from llm_model_probe.providers import OpenAIProvider as OP

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4"]
    monkeypatch.setattr(OP, "list_models", fake_list_models)

    create = client.post("/api/endpoints", json={
        "name": "probe-test",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-aaaa1111bbbb2222",
        "no_probe": True,
    })
    assert create.status_code == 201
    ep_id = create.json()["id"]

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=True,
            latency_ms=42,
            response_preview="hello",
        )
    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    r = client.post(
        f"/api/endpoints/{ep_id}/probe-model",
        json={"model": "gpt-4"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_id"] == "gpt-4"
    assert body["status"] == "available"
    assert body["latency_ms"] == 42

    # And the persisted detail now has 1 result
    detail = client.get(f"/api/endpoints/{ep_id}").json()
    assert len(detail["results"]) == 1
    assert detail["results"][0]["model_id"] == "gpt-4"
    assert detail["available"] == 1


def test_probe_model_unknown_model_400(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probing a model not in endpoint.models is rejected."""
    from llm_model_probe.providers import OpenAIProvider

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4"]
    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    create = client.post("/api/endpoints", json={
        "name": "scope-test",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-aaaa1111bbbb2222",
        "no_probe": True,
    })
    ep_id = create.json()["id"]

    r = client.post(
        f"/api/endpoints/{ep_id}/probe-model",
        json={"model": "not-listed"},
    )
    assert r.status_code == 400


def test_probe_model_endpoint_not_found_404(client: TestClient) -> None:
    r = client.post("/api/endpoints/ep_zzzzzz/probe-model",
                    json={"model": "anything"})
    assert r.status_code == 404


def test_probe_model_replaces_prior_result(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second probe for the same model overwrites the first row."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    async def fake_list_models(self):  # noqa: ARG001
        return ["m1"]
    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    create = client.post("/api/endpoints", json={
        "name": "replay",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-aaaa1111bbbb2222",
        "no_probe": True,
    })
    ep_id = create.json()["id"]

    call_count = {"n": 0}

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        call_count["n"] += 1
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=call_count["n"] == 2,    # first fail, second succeed
            latency_ms=10 * call_count["n"],
            error_type=None if call_count["n"] == 2 else "X",
            error_message=None if call_count["n"] == 2 else "fail",
        )
    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    r1 = client.post(f"/api/endpoints/{ep_id}/probe-model",
                     json={"model": "m1"}).json()
    assert r1["status"] == "failed"
    r2 = client.post(f"/api/endpoints/{ep_id}/probe-model",
                     json={"model": "m1"}).json()
    assert r2["status"] == "available"
    detail = client.get(f"/api/endpoints/{ep_id}").json()
    assert len(detail["results"]) == 1                  # not 2
    assert detail["results"][0]["status"] == "available"
```

Append to `tests/test_api_meta.py` — extend the key-leak guard:

```python
def test_no_api_key_leak_in_probe_model_response(
    isolated_home, monkeypatch
) -> None:
    """Regression: api_key plaintext must never appear in probe-model output."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    async def fake_list_models(self):  # noqa: ARG001
        return ["m"]
    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=True,
            latency_ms=1,
        )
    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    client = TestClient(app)
    raw_key = "sk-LEAK-CHECK-PROBE-MODEL-9999"
    create = client.post("/api/endpoints", json={
        "name": "leakcheck-pm",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": raw_key,
        "no_probe": True,
    })
    ep_id = create.json()["id"]
    pm = client.post(f"/api/endpoints/{ep_id}/probe-model",
                     json={"model": "m"}).text
    assert raw_key not in pm
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_api_endpoints.py tests/test_api_meta.py -q`
Expected: 4–5 new failures (route 404).

- [ ] **Step 3: Implement the route**

Append to `src/llm_model_probe/api.py` (after `retest_all`):

```python
class ProbeModelRequest(BaseModel):
    model: str = Field(min_length=1)


@app.post(
    "/api/endpoints/{name_or_id}/probe-model",
    response_model=ModelResultPublic,
)
def probe_model(name_or_id: str, req: ProbeModelRequest) -> ModelResultPublic:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    if req.model not in ep.models:
        raise HTTPException(
            status_code=400,
            detail=f"model '{req.model}' not in endpoint.models",
        )

    from .providers import make_provider
    settings = load_settings()
    provider = make_provider(ep, settings.timeout_seconds)
    try:
        pr = asyncio.run(
            provider.probe(req.model, settings.prompt, settings.max_tokens)
        )
    finally:
        asyncio.run(provider.aclose())

    source = "discovered" if ep.mode == "discover" else "specified"
    new_row = ModelResult(
        endpoint_id=ep.id,
        model_id=pr.model,
        source=source,  # type: ignore[arg-type]
        status="available" if pr.available else "failed",
        latency_ms=pr.latency_ms,
        error_type=pr.error_type,
        error_message=pr.error_message,
        response_preview=pr.response_preview,
        last_tested_at=datetime.now(),
    )
    _upsert_one_result(store, ep.id, new_row)
    return ModelResultPublic(
        model_id=new_row.model_id,
        source=new_row.source,
        status=new_row.status,
        latency_ms=new_row.latency_ms,
        error_type=new_row.error_type,
        error_message=new_row.error_message,
        response_preview=new_row.response_preview,
        last_tested_at=new_row.last_tested_at,
    )
```

Add the import for `ModelResult` near the existing imports:

```python
from .models import Endpoint, ModelResult
```

(`Endpoint` is already imported; add `ModelResult` to the same line.)

Add the `_upsert_one_result` helper next to `_persist_models`:

```python
def _upsert_one_result(
    store: EndpointStore, ep_id: str, result: ModelResult
) -> None:
    """Replace or insert a single model_results row for (ep_id, model_id)."""
    import sqlite3
    from .store import _iso
    with sqlite3.connect(store._path) as c:
        c.execute(
            "DELETE FROM model_results WHERE endpoint_id = ? AND model_id = ?",
            (ep_id, result.model_id),
        )
        c.execute(
            """INSERT INTO model_results
               (endpoint_id, model_id, source, status, latency_ms,
                error_type, error_message, response_preview, last_tested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                result.endpoint_id, result.model_id, result.source, result.status,
                result.latency_ms, result.error_type, result.error_message,
                result.response_preview, _iso(result.last_tested_at),
            ),
        )
        c.execute(
            "UPDATE endpoints SET updated_at = ? WHERE id = ?",
            (_iso(datetime.now()), ep_id),
        )
        c.commit()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest -q`
Expected: all green (46 prior + 4 new = 50).

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py tests/test_api_meta.py
git commit -m "feat(api): /api/endpoints/{id}/probe-model 单模型探活"
```

---

## Task 3: Frontend — types + api.ts + orchestrator hook

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/orchestrator.ts`

- [ ] **Step 1: Update types**

Modify `frontend/src/lib/types.ts`:

```ts
// Replace EndpointSummary and EndpointDetail with these versions:
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
  total_models: number;                            // NEW
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface EndpointDetail extends EndpointSummary {
  api_key_masked: string;
  models: string[];
  excluded_by_filter: string[];                    // NEW
  results: ModelResultPublic[];
}
```

- [ ] **Step 2: Add `probeModel` to api.ts**

Modify `frontend/src/lib/api.ts`. Add to the `api` object:

```ts
import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  PasteSuggestion,
  ModelResultPublic,                              // NEW
} from "./types";
```

Add the method to the export:

```ts
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
  probeModel: (id: string, model: string) =>                      // NEW
    req<ModelResultPublic>(
      "POST",
      `/api/endpoints/${encodeURIComponent(id)}/probe-model`,
      { model },
    ),
};
```

- [ ] **Step 3: Create the orchestrator hook**

Create `frontend/src/lib/orchestrator.ts`:

```ts
import { useCallback, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

const CONCURRENCY = 5;

/** Stable key per (endpoint, model). */
function k(ep: string, model: string): string {
  return `${ep}::${model}`;
}

type Listener = () => void;

type Status = "pending" | "done";

interface Inflight {
  status: Status;
}

class OrchestratorStore {
  private map = new Map<string, Inflight>();
  private inFlight = 0;
  private queue: Array<() => void> = [];
  private listeners = new Set<Listener>();

  subscribe = (cb: Listener): (() => void) => {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  };

  private emit() {
    for (const cb of this.listeners) cb();
  }

  /** Snapshot — useSyncExternalStore expects a stable reference when nothing
   *  changed; we return a number (revision) instead and compute lookups
   *  via the helper methods. */
  private rev = 0;
  getSnapshot = (): number => this.rev;

  isPending(ep: string, model: string): boolean {
    return this.map.get(k(ep, model))?.status === "pending";
  }

  pendingCountForEndpoint(ep: string): number {
    let n = 0;
    for (const [key, v] of this.map) {
      if (v.status === "pending" && key.startsWith(`${ep}::`)) n++;
    }
    return n;
  }

  totalPending(): number {
    let n = 0;
    for (const v of this.map.values()) if (v.status === "pending") n++;
    return n;
  }

  /** Schedule probes; resolves when all complete. */
  run(ep: string, models: string[], onResult: (m: string) => void): Promise<void> {
    return new Promise((resolve) => {
      let remaining = models.length;
      if (remaining === 0) return resolve();
      const tick = () => {
        while (this.inFlight < CONCURRENCY && this.queue.length) {
          const job = this.queue.shift()!;
          this.inFlight++;
          job();
        }
      };
      for (const m of models) {
        this.map.set(k(ep, m), { status: "pending" });
        this.queue.push(() => {
          api
            .probeModel(ep, m)
            .catch(() => {/* swallow; surfaced via cache invalidation */})
            .finally(() => {
              this.map.delete(k(ep, m));
              this.inFlight--;
              this.rev++;
              this.emit();
              onResult(m);
              remaining--;
              if (remaining === 0) resolve();
              tick();
            });
        });
      }
      this.rev++;
      this.emit();
      tick();
    });
  }
}

let singleton: OrchestratorStore | null = null;
function store(): OrchestratorStore {
  if (!singleton) singleton = new OrchestratorStore();
  return singleton;
}

/** React hook — re-renders on any orchestrator state change. */
export function useProbeOrchestrator() {
  const s = store();
  // Subscribe so any pending change re-renders this component.
  useSyncExternalStore(s.subscribe, s.getSnapshot, s.getSnapshot);
  const qc = useQueryClient();
  const startRef = useRef(s);

  const run = useCallback(
    async (ep: string, models: string[]) => {
      await startRef.current.run(ep, models, () => {
        qc.invalidateQueries({ queryKey: ["endpoint", ep] });
        qc.invalidateQueries({ queryKey: ["endpoints"] });
      });
    },
    [qc],
  );

  return {
    run,
    isPending: (ep: string, model: string) => s.isPending(ep, model),
    pendingForEndpoint: (ep: string) => s.pendingCountForEndpoint(ep),
    totalPending: () => s.totalPending(),
  };
}
```

- [ ] **Step 4: Verify build**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Expected: build succeeds, no TS errors.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/orchestrator.ts
git commit -m "feat(frontend): probeModel API + useProbeOrchestrator hook"
```

---

## Task 4: AddEndpointDialog — discover-only + auto-open drawer

**Files:**
- Modify: `frontend/src/components/AddEndpointDialog.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Modify AddEndpointDialog**

In `frontend/src/components/AddEndpointDialog.tsx`:

a) Update the prop signature to add an `onCreated` callback:

```tsx
export default function AddEndpointDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
```

b) Modify the mutation to use the created id and call `onCreated`:

```tsx
const create = useMutation({
  mutationFn: (payload: EndpointCreate) =>
    api.createEndpoint({ ...payload, no_probe: true }),     // CHANGED
  onSuccess: (data) => {                                    // CHANGED
    qc.invalidateQueries({ queryKey: ["endpoints"] });
    setForm(empty);
    setModelsText("");
    onClose();
    onCreated(data.id);                                     // NEW
  },
});
```

c) Update the submit button label:

```tsx
<Button
  onClick={submit}
  disabled={
    create.isPending ||
    !form.name ||
    !form.base_url ||
    !form.api_key
  }
>
  {create.isPending ? "Adding…" : "Add"}                    {/* CHANGED */}
</Button>
```

- [ ] **Step 2: Update App.tsx to pass onCreated**

In `frontend/src/App.tsx`:

```tsx
<AddEndpointDialog
  open={showAdd}
  onClose={() => setShowAdd(false)}
  onCreated={(id) => setSelected(id)}
/>
```

- [ ] **Step 3: Verify build + smoke**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Manual smoke (use isolated home):

```bash
cd ~/Code/Tools/llm-model-probe
export LLM_MODEL_PROBE_HOME="$(mktemp -d)/probe-home"
uv run probe ui --no-browser --port 8765 &
sleep 2
# In a browser: open http://localhost:8765
# Add an endpoint with mode=specified and bogus URL — dialog should close
# in <1s and the drawer should open showing the endpoint with empty results.
pkill -f "uvicorn.*8765"; rm -rf "$LLM_MODEL_PROBE_HOME"
```

(Manual visual confirmation; not automated.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AddEndpointDialog.tsx frontend/src/App.tsx
git commit -m "feat(frontend): Add 对话框默认 no_probe + 创建后自动打开 drawer"
```

---

## Task 5: EndpointDetailDrawer — interactive model list

**Files:**
- Replace: `frontend/src/components/EndpointDetailDrawer.tsx`

- [ ] **Step 1: Rewrite the drawer**

Replace the entire contents of `frontend/src/components/EndpointDetailDrawer.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { relative } from "@/lib/format";
import type { EndpointDetail, ModelResultPublic } from "@/lib/types";

export default function EndpointDetailDrawer({
  idOrName,
  autoTest,
  onAutoTestConsumed,
  onClose,
}: {
  idOrName: string | null;
  autoTest: boolean;
  onAutoTestConsumed: () => void;
  onClose: () => void;
}) {
  const open = idOrName !== null;
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName!),
    enabled: open,
  });
  const orch = useProbeOrchestrator();
  const [checked, setChecked] = useState<Set<string>>(new Set());

  // Reset checkbox state when the drawer's endpoint changes; default-check
  // models that are NOT in excluded_by_filter.
  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
  }, [detail.data?.id]);

  // Auto-trigger Test all if requested by parent (row ↻ click)
  useEffect(() => {
    if (autoTest && detail.data && detail.data.models.length > 0) {
      orch.run(detail.data.id, detail.data.models);
      onAutoTestConsumed();
    }
  }, [autoTest, detail.data?.id]);

  const resultByModel = useMemo(() => {
    const m = new Map<string, ModelResultPublic>();
    if (detail.data) for (const r of detail.data.results) m.set(r.model_id, r);
    return m;
  }, [detail.data]);

  function toggle(model: string) {
    setChecked((prev) => {
      const n = new Set(prev);
      if (n.has(model)) n.delete(model);
      else n.add(model);
      return n;
    });
  }

  const d = detail.data;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{d?.name ?? "…"}</SheetTitle>
        </SheetHeader>

        {detail.isLoading && (
          <div className="py-4 text-muted-foreground">Loading…</div>
        )}

        {d && (
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

            {d.models.length === 0 ? (
              <div className="text-muted-foreground italic">
                {d.list_error
                  ? "No models discovered. Try removing this endpoint and re-adding."
                  : "No models. Specified mode with empty list."}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">
                    Models ({d.models.length})
                  </h3>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={checked.size === 0}
                      onClick={() => orch.run(d.id, [...checked])}
                    >
                      Test selected ({checked.size})
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => orch.run(d.id, d.models)}
                    >
                      Test all
                    </Button>
                  </div>
                </div>

                <div className="border rounded-md divide-y">
                  {d.models.map((m) => (
                    <ModelRow
                      key={m}
                      model={m}
                      result={resultByModel.get(m) ?? null}
                      pending={orch.isPending(d.id, m)}
                      filterSkip={d.excluded_by_filter.includes(m)}
                      checked={checked.has(m)}
                      onToggle={() => toggle(m)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ModelRow({
  model,
  result,
  pending,
  filterSkip,
  checked,
  onToggle,
}: {
  model: string;
  result: ModelResultPublic | null;
  pending: boolean;
  filterSkip: boolean;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex items-center gap-2 px-3 py-2 hover:bg-muted/30 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-4 w-4"
      />
      <span className="font-mono text-xs flex-1 truncate">{model}</span>
      {filterSkip && !result && !pending && (
        <Badge variant="secondary" className="text-xs">
          filter-skip
        </Badge>
      )}
      <ModelStatus result={result} pending={pending} />
    </label>
  );
}

function ModelStatus({
  result,
  pending,
}: {
  result: ModelResultPublic | null;
  pending: boolean;
}) {
  if (pending)
    return <span className="text-muted-foreground text-xs">… testing</span>;
  if (!result)
    return <span className="text-muted-foreground text-xs">untested</span>;
  if (result.status === "available")
    return (
      <span className="text-green-600 text-xs">
        ✓ {result.latency_ms} ms
      </span>
    );
  return (
    <span className="text-destructive text-xs truncate max-w-[200px]">
      ✗ {result.error_type}
    </span>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
```

- [ ] **Step 2: Update App.tsx to thread autoTest state**

Modify `frontend/src/App.tsx`. Replace the `selected` state pattern:

```tsx
const [selected, setSelected] = useState<string | null>(null);
const [autoTest, setAutoTest] = useState(false);
```

Update the table prop (will be threaded in the next task — for now just compile-check):

```tsx
{list.data && (
  <EndpointTable
    endpoints={list.data}
    onSelect={(id) => { setSelected(id); setAutoTest(false); }}
    onRetest={(id) => { setSelected(id); setAutoTest(true); }}
  />
)}
```

(`onRetest` will be wired in Task 6; the change above prepares the call site.)

Update the drawer:

```tsx
<EndpointDetailDrawer
  idOrName={selected}
  autoTest={autoTest}
  onAutoTestConsumed={() => setAutoTest(false)}
  onClose={() => setSelected(null)}
/>
```

- [ ] **Step 3: Verify build**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Expected: TS compiles. (EndpointTable will warn about unused `onRetest` prop — Task 6 wires it.)

If build fails because EndpointTable's prop type doesn't yet declare `onRetest`,
do this minimal patch in `frontend/src/components/EndpointTable.tsx` to its
prop signature (full row-button rewrite is in Task 6):

```tsx
export default function EndpointTable({
  endpoints,
  onSelect,
  onRetest,
}: {
  endpoints: EndpointSummary[];
  onSelect: (idOrName: string) => void;
  onRetest?: (idOrName: string) => void;          // optional for now
}) {
  // … existing body unchanged; we'll replace the row ↻ in Task 6
  void onRetest;
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EndpointDetailDrawer.tsx frontend/src/components/EndpointTable.tsx frontend/src/App.tsx
git commit -m "feat(frontend): drawer 改为交互式模型列表 (Test selected / Test all)"
```

---

## Task 6: EndpointTable — orchestrator-based row retest + Retest all + summary

**Files:**
- Modify: `frontend/src/components/EndpointTable.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Replace EndpointTable**

Replace the entire contents of `frontend/src/components/EndpointTable.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { relative } from "@/lib/format";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function EndpointTable({
  endpoints,
  onSelect,
  onRetest,
}: {
  endpoints: EndpointSummary[];
  onSelect: (idOrName: string) => void;
  onRetest: (idOrName: string) => void;
}) {
  const qc = useQueryClient();
  const orch = useProbeOrchestrator();

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
        {endpoints.map((ep) => {
          const pendingForRow = orch.pendingForEndpoint(ep.id);
          const untested =
            ep.total_models - ep.available - ep.failed;
          return (
            <TableRow
              key={ep.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => onSelect(ep.id)}
            >
              <TableCell className="font-mono text-xs text-muted-foreground">
                {ep.id}
              </TableCell>
              <TableCell className="font-medium">{ep.name}</TableCell>
              <TableCell>{ep.sdk}</TableCell>
              <TableCell>{ep.mode}</TableCell>
              <TableCell>
                {ep.list_error ? (
                  <Badge variant="destructive">list-error</Badge>
                ) : ep.total_models === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <span className="text-xs">
                    <span className="text-green-600">{ep.available}</span>
                    {" / "}
                    <span className="text-destructive">{ep.failed}</span>
                    {untested > 0 && (
                      <>
                        {" / "}
                        <span className="text-muted-foreground">
                          {untested} untested
                        </span>
                      </>
                    )}
                    {pendingForRow > 0 && (
                      <span className="text-blue-600 ml-1">
                        ({pendingForRow} testing)
                      </span>
                    )}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {relative(ep.last_tested_at)}
              </TableCell>
              <TableCell className="text-muted-foreground max-w-[200px] truncate">
                {ep.note}
              </TableCell>
              <TableCell
                className="text-right space-x-1"
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ep.total_models === 0 || pendingForRow > 0}
                  title="Open + test all models"
                  onClick={() => onRetest(ep.id)}
                >
                  ↻
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
          );
        })}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 2: Replace the top "Retest all" button in App.tsx**

In `frontend/src/App.tsx`, replace the `retestAll` mutation and button block.

Find:

```tsx
const retestAll = useMutation({
  mutationFn: api.retestAll,
  onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
});
```

Replace with:

```tsx
import { useProbeOrchestrator } from "@/lib/orchestrator";
// (add this import near the top with other imports)

// ...inside App():
const orch = useProbeOrchestrator();
const totalPending = orch.totalPending();

async function retestEverything() {
  // Iterate endpoints, fetch each detail to get its model list, then queue
  // probes for that endpoint. The orchestrator's shared concurrency=5
  // limiter throttles all in-flight probes globally.
  if (!list.data) return;
  for (const ep of list.data) {
    if (ep.total_models === 0) continue;
    const detail = await api.getEndpoint(ep.id);
    // Don't await — let them run in background, all sharing the same limiter.
    void orch.run(ep.id, detail.models);
  }
}
```

Replace the button:

```tsx
<Button
  variant="outline"
  disabled={totalPending > 0}
  onClick={retestEverything}
>
  {totalPending > 0
    ? `Retesting (${totalPending} in flight)…`
    : "↻ Retest all"}
</Button>
```

Remove the `useMutation` for `retestAll` — it's no longer used. Also remove
the now-unused `useMutation` import if nothing else needs it (keep `useQuery`).

Final imports near the top of App.tsx:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";
```

- [ ] **Step 3: Verify build**

```bash
cd ~/Code/Tools/llm-model-probe/frontend && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Manual smoke**

```bash
cd ~/Code/Tools/llm-model-probe
export LLM_MODEL_PROBE_HOME="$(mktemp -d)/probe-home"
uv run probe ui --no-browser --port 8765 &
sleep 2
```

In the browser at http://localhost:8765:

1. Add an endpoint (specified mode, models=`a,b,c`, fake URL/key) — dialog
   closes in <1s, drawer auto-opens with 3 untested models.
2. Click "Test all" — rows show `… testing` then ✗ red as the network errors land.
3. Open another tab to http://localhost:8765 — table should be responsive.
4. Click row's ↻ — same drawer opens, auto-triggers Test all.
5. Top "Retest all" — runs across all endpoints; button shows `Retesting (X in flight)…`.

Cleanup:

```bash
pkill -f "uvicorn.*8765"
rm -rf "$LLM_MODEL_PROBE_HOME"
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EndpointTable.tsx frontend/src/App.tsx
git commit -m "feat(frontend): 行 ↻ + Retest all 改为前端编排 (orchestrator)"
```

---

## Task 7: README + final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README's Web UI section**

In `README.md`, replace the bullets in the "Features" subsection of "Web UI" with:

```markdown
Features:
- **Discover then test** — Add registers the endpoint and lists models in 1–3s; you then choose which models to probe. No more waiting on a 50-model auto-probe.
- **Smart paste** — drop a JSON, dotenv block, or curl command into the Add dialog and it auto-fills the form.
- **Live progress** — each model probes via its own short HTTP call; rows update incrementally (`… testing` → ✓/✗) while the rest of the UI stays responsive.
- **One-click retest / delete** per row.
- "Retest all" runs across every endpoint; concurrency is throttled to 5 in-flight probes globally.
- Detail drawer shows model-level status with masked API key + checkbox to pick which models to test.
```

- [ ] **Step 2: Final test suite + smoke**

```bash
cd ~/Code/Tools/llm-model-probe
uv run pytest -q                          # backend tests
cd frontend && npm run build && cd ..     # frontend builds
uv run probe --help                       # CLI still has all 7 commands
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README 更新 UI 描述（discover-then-test）"
```

---

## Self-Review (post-write)

**Spec coverage check:**

- ✅ Goal — eliminating long-blocking dialog: Tasks 1 + 4 (no_probe=true on add).
- ✅ Goal — server stays responsive during probes: Tasks 2 + 3 + 6 (per-model API + orchestrator).
- ✅ POST /api/endpoints behavior change: Task 1.
- ✅ POST /api/endpoints/{id}/probe-model: Task 2.
- ✅ EndpointSummary.total_models: Task 1.
- ✅ EndpointDetail.excluded_by_filter: Task 1.
- ✅ AddEndpointDialog → no_probe=true + auto-open drawer: Task 4.
- ✅ EndpointDetailDrawer interactive model list with checkboxes / Test selected / Test all: Task 5.
- ✅ EndpointTable row ↻ uses orchestrator: Task 6.
- ✅ "Retest all" frontend-orchestrated with shared concurrency=5: Task 6.
- ✅ Default-checked = `models − excluded_by_filter`: Task 5.
- ✅ Backend tests for new fields and probe-model: Tasks 1 + 2.
- ✅ key-leak regression covers probe-model: Task 2.
- ✅ CLI / `/retest` / `/retest-all` unchanged: confirmed by Task scope (no modifications to those paths).

**Placeholder scan:** No TBD/TODO; every code-changing step has full code.

**Type / name consistency:**
- `EndpointSummary.total_models`, `EndpointDetail.excluded_by_filter`, `ModelResultPublic.model_id`, `api.probeModel(id, model)`, `useProbeOrchestrator().run/isPending/pendingForEndpoint/totalPending` — used consistently across api.py, types.ts, orchestrator.ts, drawer, table.
- `_persist_models` and `_upsert_one_result` defined in api.py and used in the create + probe-model routes respectively.
- `ProbeModelRequest.model` field name matches the JS `probeModel(id, model)` body shape.

Plan ready for execution.

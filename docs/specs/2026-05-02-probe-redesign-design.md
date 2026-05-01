# Probe UX Redesign — Discover-then-test, per-model API

**Date**: 2026-05-02
**Status**: approved (verbal)
**Builds on**: `docs/specs/2026-05-01-design.md`, `docs/specs/2026-05-01-ui-design.md`

## Goal

Eliminate two pain points in the current "Add & Probe" flow:

1. **Long blocking dialog** — adding an endpoint with 50 models keeps the
   dialog spinning for several minutes.
2. **Server unresponsive while bulk probe runs** — single-worker uvicorn does
   `asyncio.run()` per request, so any other API call queues until the bulk
   probe finishes.

Solution: split add and probe into two phases. Add only discovers the model
list (1–3 s). User then explicitly chooses which models to test. Each model is
probed via its own short HTTP request, with concurrency orchestrated on the
frontend. The server never holds a long blocking request, and the UI shows
live progress as rows update.

## Non-Goals

- Probe cancellation (mid-flight). User can navigate away; in-flight requests
  finish and store their result.
- Server-Sent Events / WebSocket streaming.
- Backend bulk progress tracking. Progress lives in the React state.
- CLI behavior change — `probe add` keeps its current "discover + probe all"
  semantics for scripting users.
- Refresh / re-discover of endpoint model list (provider added new models).
  v1 escape hatch: `rm` + `add` again. (See _Out of Scope_.)

## Architecture Change

```
BEFORE                                    AFTER
───────                                   ─────
POST /api/endpoints                       POST /api/endpoints  (no_probe=true)
  → store + list_models()                   → store + list_models() only
  → asyncio.run(probe all)                  → returns 1-3 s with discovered models
  → 30 s – 5 min response                 (mode=specified: stores models, no list call)

                                          POST /api/endpoints/{id}/probe-model
                                            body: {"model": "gpt-4"}
                                            → probes that one model
                                            → 5 – 15 s response
                                            → frontend fires N in parallel,
                                              concurrency=5 throttle
```

### Why per-model

| Concern | Per-model wins |
|---|---|
| Server responsiveness | Each request is short; uvicorn worker isn't camped |
| UI feedback | Each result lands incrementally; UI updates that row only |
| Concurrency control | Frontend p-limit picks N; server semaphore unused for UI path |
| Cancellation | Just stop firing requests; in-flight finish naturally |
| Code change scope | One new endpoint; existing logic reused unchanged |

## Data Model

No schema migration. The existing tables already support what's needed:

- `endpoints.models` (TEXT JSON array)
  - Mode `specified`: user-supplied list (unchanged).
  - Mode `discover`: **now populated** with the result of `list_models()` at
    add time. Previously empty for discover-mode endpoints.
- `model_results` rows are written one at a time by `/probe-model`.
- A model in `endpoints.models` with no matching `model_results` row = "untested".

## API Changes

### Modified: `POST /api/endpoints`

- When `no_probe=true` (UI path):
  - **discover mode**: call `list_models()`; persist result in `endpoints.models`.
    On failure: store `list_error`, leave `models` empty, return 200 with detail.
    Do not probe.
  - **specified mode**: persist user's models. Do not list, do not probe.
- When `no_probe=false` (CLI path): unchanged. Still discovers, filters, probes
  all in one request.

The `EndpointDetail` response now reliably has `models` populated for
discover-mode endpoints (was empty before).

### New: `POST /api/endpoints/{name_or_id}/probe-model`

Probes a single model and persists the result.

```python
class ProbeModelRequest(BaseModel):
    model: str = Field(min_length=1)

@app.post("/api/endpoints/{name_or_id}/probe-model",
          response_model=ModelResultPublic)
def probe_model(name_or_id: str, req: ProbeModelRequest) -> ModelResultPublic:
    ...
```

Behavior:

- 404 if endpoint not found.
- 400 if `req.model` is not in `endpoint.models` (defends against probing
  arbitrary models for an endpoint).
- Calls `provider.probe(model, prompt, max_tokens)` directly (skips the
  `ProbeRunner` orchestration since there's only one model).
- Upserts the corresponding `model_results` row (replaces any prior result
  for that endpoint+model).
- Returns the new `ModelResultPublic`.

### Modified: `EndpointSummary`

Add one field for the table to show "X / Y tested":

```python
class EndpointSummary(BaseModel):
    # ... existing ...
    total_models: int    # len(endpoints.models); untested = total - available - failed
```

### Modified: `EndpointDetail`

Add a server-computed list so the drawer knows which boxes to leave unchecked
without re-implementing fnmatch in JS:

```python
class EndpointDetail(EndpointSummary):
    # ... existing ...
    excluded_by_filter: list[str]   # subset of `models` matching config.toml
                                    # exclude patterns. Empty for specified mode
                                    # (user explicit list bypasses filter).
```

Frontend logic: default-checked set = `models − excluded_by_filter`.

### Unchanged (kept for CLI compatibility)

- `POST /api/endpoints/{id}/retest` — still does the bulk async probe. CLI's
  `probe retest` uses this. UI no longer calls it.
- `POST /api/retest-all` — same. CLI's `probe retest --all` uses this. UI no
  longer calls it.

## Frontend Changes

### `AddEndpointDialog`

- Always send `no_probe: true`.
- Button label: `Add` (was `Add & Probe`).
- On success:
  - Close dialog.
  - Auto-open `EndpointDetailDrawer` for the new endpoint
    (`setSelected(newEndpoint.id)`).
- Smart paste, validation: unchanged.

### `EndpointDetailDrawer` (significant)

Replace the static results display with an interactive model list:

```
┌──────────────────────────────────────────────────┐
│ bob-glm           [Test selected]  [Test all]    │
├──────────────────────────────────────────────────┤
│ ☑ glm-4              ✓ 120ms  hi there            │
│ ☑ glm-4-plus         ✗ AuthError  401 ...         │
│ ☑ glm-4-air          · untested                   │
│ ☐ glm-embedding      · untested  (filter-skip)    │
│ ☑ glm-3-turbo        … testing                    │
│ ...                                                │
└──────────────────────────────────────────────────┘
```

Per row:
- Checkbox (default checked unless `model_id ∈ excluded_by_filter` returned by the detail endpoint).
- Model id (mono).
- Status: `untested` / `✓ <latency>` / `✗ <error_type>` / `… testing` (during probe).
- Tooltip / inline preview of response (available) or error message (failed).

Top buttons:
- **Test selected**: probes only checked rows.
- **Test all**: probes every row regardless of checkbox.

Both reuse the same orchestration:

```ts
async function probeMany(endpointId: string, models: string[], onResult) {
  // p-limit equivalent, no extra dep
  const concurrency = 5;
  let inFlight = 0, idx = 0;
  return new Promise<void>((resolve) => {
    const tick = () => {
      while (inFlight < concurrency && idx < models.length) {
        const m = models[idx++];
        inFlight++;
        api.probeModel(endpointId, m)
          .then((r) => onResult(m, r, null))
          .catch((e) => onResult(m, null, e))
          .finally(() => {
            inFlight--;
            if (idx >= models.length && inFlight === 0) resolve();
            else tick();
          });
      }
    };
    tick();
  });
}
```

`onResult` updates a per-model React state map: `{ [model]: 'pending' | result | error }`.
On completion of any model, react-query invalidates the endpoint detail so
the persisted state syncs.

### `EndpointTable`

- Per-row retest button (↻): change behavior. Instead of calling `/retest`,
  open the drawer for that endpoint and auto-trigger "Test all".
- Top "Retest all" button: same orchestration but across all endpoints.
  - Total budget: still concurrency=5 across all in-flight probes
    (one shared limiter, not 5 per endpoint).
  - Show progress in the button label: `Retesting (12 / 87)…`
  - On completion: invalidate `["endpoints"]` query.

The change to summary card display:
- Old: `8/12 ✓` (available/failed)
- New: `8 ✓ / 4 ✗ / 18 untested` or compact: `8/4/18` with green/red/gray colors.
  When all probed: `8/4` (no untested badge).

### Removed: bulk button blocking

The old `useMutation({ mutationFn: api.retestAll })` is gone. Both retest paths
(per-endpoint, all-endpoints) become frontend-orchestrated.

### State management

A small `useProbeOrchestrator` hook owns:
- Map of `endpoint_id → { [model]: ProbeState }` for live "testing" indicators.
- Concurrency limiter (one shared instance per page).
- Cleanup on unmount: doesn't cancel; lets in-flight finish.

## Error Handling

| Situation | Behavior |
|---|---|
| Endpoint deleted while probing | Per-model API returns 404; UI removes the row |
| Network error on one probe | UI shows ✗ Network for that row; others continue |
| All probes fail | UI just shows N red rows; user retries individually |
| `list_models()` fails on add | 200 + `list_error` set; UI shows endpoint with empty model list and a banner offering "rm and re-add to retry" |
| Probing a model not in endpoint.models | 400 (defensive) |

## Backend Test Additions

In `tests/test_api_endpoints.py`:

- `test_create_no_probe_discover_populates_models` — monkeypatch the provider's
  `list_models` to return `["a", "b"]`; POST with discover mode + no_probe.
  Assert `endpoints.models == ["a", "b"]`, no `model_results` rows.
- `test_create_no_probe_discover_list_error` — monkeypatch `list_models` to raise.
  Assert response has `list_error` set, `models` empty.
- `test_probe_model_writes_result` — seed endpoint, monkeypatch `provider.probe`,
  POST `/probe-model`, assert `model_results` row exists with new data.
- `test_probe_model_unknown_model_400` — seed endpoint with models=["a"]; POST
  `/probe-model` with `model="z"` → 400.
- `test_probe_model_endpoint_not_found_404`.
- `test_probe_model_does_not_leak_api_key` — extend the existing key-leak test.

## Frontend Test Additions

Per existing convention: no unit tests. Manual smoke checklist (added to
README's troubleshooting):

1. Add a (mocked) endpoint with discover mode → dialog closes, drawer opens,
   models listed as `untested`.
2. Click "Test all" → rows fill in incrementally, no full-screen spinner.
3. While probing, the table on the page background should still respond to
   refresh / row click.
4. Reload page mid-probe → completed results persist, in-flight ones lost.

## Out of Scope (v1 explicit)

- `POST /api/endpoints/{id}/rediscover` — escape hatch when `list_models()`
  fails on add. v1: user does `rm` then re-`add`. Adding this is a small change
  but adds another endpoint; defer until someone actually needs it.
- Probe cancellation. User just navigates away.
- Frontend optimistic updates (we wait for response before turning row green).
- Reordering / sorting / filtering the model list. v1 keeps server-returned
  order. Add UI controls if 50+ models becomes unwieldy.
- A live progress bar at the top of the page tracking N-of-M for the
  cross-endpoint "Retest all". v1: just a count in the button label.

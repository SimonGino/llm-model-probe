# AI Paste Parser

Date: 2026-05-06

## Problem

`AddEndpointDialog` already has a "smart paste" path: paste a blob → local
regex parser tries JSON / curl / dotenv → form fields auto-fill. This works
for clean structured input but fails on natural-language content (Slack
messages, emails, vendor docs paragraphs). User then has to copy each field
out by hand.

We want the user to pick one of their already-configured endpoints+models as
a default LLM parser, then click an `✨ AI Parse` button to let the LLM
extract the same fields.

## Scope

**In:**
- New `app_settings` table (single-row K/V) holding `parser.endpoint_id` and
  `parser.model_id`.
- New REST routes: read/write the default-parser setting, run an AI parse.
- New `Settings` modal in the UI (gear icon in the top bar) with one section:
  pick endpoint + model.
- New `✨ AI Parse` button in `AddEndpointDialog` that triggers the LLM call
  and overwrites the four target form fields.

**Out (YAGNI):**
- Multiple parser candidates / fallback chain.
- User-customizable prompt template.
- Parse-history or response caching.
- Streaming UI for the LLM response.
- Auto language detection (LLM handles zh/en directly).

## Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Trigger: manual button | Keep the zero-latency rule path for clean inputs; only spend tokens when the user explicitly opts in. |
| 2 | Default parser stored in SQLite (not config.toml) | toml is for static tuning; this is a runtime UI-mutable setting. |
| 3 | Selection granularity: endpoint + model | Different models on the same endpoint have very different ability/cost. |
| 4 | LLM call lives in the backend | Reuses existing `OpenAIProvider`/`AnthropicProvider`; api_key never leaves SQLite. |
| 5 | Fields extracted: `base_url`, `api_key`, `sdk`, `name` | `models` is left to discover-mode auto-list. |
| 6 | Output handling: overwrite (skip null fields) | User clicked the button, intent is clear; null fields don't clobber existing values. |

## Data Model

New SQLite table:

```sql
CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Idempotent migration in `EndpointStore.init_schema()`. Stored keys for this
feature:

- `parser.endpoint_id` → endpoint id (e.g. `ep_064f07`)
- `parser.model_id`    → a model id that must be present in the chosen
  endpoint's `models` list at write time

If the chosen endpoint or model goes away later (deletion / rediscover drops
it), `GET /api/settings/parser` returns `{null, null}` — the UI treats this
as "not configured" and re-prompts the user on next AI-parse attempt.

## API

### GET /api/settings/parser

Response 200:
```json
{ "endpoint_id": "ep_064f07", "model_id": "gpt-4o-mini" }
```

Returns `{null, null}` if not configured, or if the stored endpoint/model is
no longer valid (auto-recover instead of erroring).

### PUT /api/settings/parser

Request:
```json
{ "endpoint_id": "ep_064f07", "model_id": "gpt-4o-mini" }
```

- 200 + same shape on success.
- 400 if endpoint not found.
- 400 if `model_id` not in `endpoint.models`.

### POST /api/ai-parse

Request:
```json
{ "blob": "..." }
```

Response 200:
```json
{
  "name": "...",
  "sdk": "openai",
  "base_url": "...",
  "api_key": "...",
  "confidence": 1.0,
  "latency_ms": 1180
}
```
Any of the field values may be `null` (LLM didn't pick that field up).
`confidence` is `0.0` when no usable JSON came back; `1.0` when at least
`base_url` AND `api_key` are non-null; `0.5` for partial.

Status codes:
- **412** — no default parser configured (or stored one is stale).
- **502** — LLM call raised (`error_type=Timeout`, etc.).
- **200 + confidence=0** — LLM responded but the response wasn't usable.

## LLM Call

Add a `complete(prompt: str, max_tokens: int) -> CompleteResult` method to
the `Provider` protocol and to both `OpenAIProvider` and `AnthropicProvider`.
It returns `{text: str, latency_ms: int}` or raises.

OpenAI implementation first attempts:
```python
chat.completions.create(
    model=parser_model,
    messages=[{"role":"user","content":prompt}],
    max_tokens=400,
    response_format={"type":"json_object"},
)
```
If the endpoint rejects `response_format` (some compat proxies do) we catch
and retry without it.

Anthropic just uses `messages.create(max_tokens=400, ...)` — Claude is
already good at returning bare JSON when prompted strictly.

**Prompt template** (lives in `src/llm_model_probe/parser_prompt.py`):

```
Extract OpenAI/Anthropic-compatible endpoint config from the text below.
Output strict JSON only — no commentary, no markdown fences.

Schema:
{
  "base_url": string|null,    // root URL (no /chat/completions suffix)
  "api_key":  string|null,    // bearer / x-api-key
  "sdk":      "openai"|"anthropic"|null,
  "name":     string|null     // a short human label like "GLM via Bob" or null
}

Text:
---
{blob}
---
```

If `len(blob) > 4000`, truncate to the first 4000 chars and append
`[truncated]` to the prompt body. (Pre-LLM check; surfaces in the prompt so
the model knows the input may be incomplete.)

JSON parsing:
1. Try `json.loads(text)`.
2. On failure: regex out the first `{...}` block and try again.
3. On second failure: return `confidence=0` with all fields null.

## Frontend

### Settings modal

- Top bar gets a new gear icon to the right of the existing
  sun/moon/logout cluster.
- Click → modal with one section, "Default AI Parser":
  - Endpoint dropdown — list endpoints with health != "all down" (computed
    from existing `EndpointSummary`).
  - Model dropdown — populated from the selected endpoint's `models`,
    filtered to those whose latest result is `available`.
  - `Save` (calls `PUT /api/settings/parser`) and `Cancel`.
- Footer disclaimer: *"AI Parse 会把粘贴的文本发到这里选中的 endpoint
  做解析；该 endpoint 的服务方会看到内容（可能含其他 endpoint 的
  api_key）。"*

### AddEndpointDialog change

- Inside the existing smart-paste textarea region, add an `✨ AI Parse`
  button at the right edge of the helper-text row.
- States:
  - Idle: enabled when textarea has non-whitespace content.
  - Loading: label `Parsing… {sec}s`, disabled.
  - Error: red helper text under the textarea showing
    `error_type: error_message` (truncated).
- On 200: write `name`/`sdk`/`base_url`/`api_key` to the form, skipping any
  field where AI returned null (don't clobber whatever the rule parser
  filled in).
- On 412: toast "Set a default parser in Settings first" with a button that
  opens the Settings modal.

## Error Handling Matrix

| Scenario | Behavior |
|---|---|
| Default parser endpoint deleted | `GET /api/settings/parser` returns `{null, null}` (auto-recover) |
| Default parser model removed by rediscover | same as above |
| LLM call timeout | 502 with `error_type=Timeout`; UI shows error, form untouched |
| LLM responds with non-JSON | 200 + `confidence=0` + null fields |
| LLM partial extraction (only base_url) | 200 + `confidence=0.5` + filled fields written, others left alone |
| `response_format=json_object` rejected | Backend silently retries without it |
| Blob > 4000 chars | Truncated server-side; prompt notes truncation |
| User clicks AI Parse with empty textarea | Button is disabled |

## Testing

**Backend (pytest)**
- `test_app_settings_store.py` — store-level GET/SET/auto-recover.
- `test_settings_parser.py` — `/api/settings/parser` GET/PUT, the 400 cases,
  and the auto-null behavior when stored ep/model goes stale.
- `test_ai_parse.py`:
  - 412 when not configured.
  - 200 with valid mocked provider response.
  - 200 + confidence=0 when provider returns non-JSON.
  - 502 when provider raises timeout.
  - Truncation: blob > 4000 chars → mock verifies the prompt was truncated.
  - `response_format` retry path (mock first call rejects, second succeeds).

**Frontend**
- `tsc --noEmit` + `vite build` only. UI flows are exercised manually in
  dev-server (matches existing repo convention).

## Risk Notes

- **Prompt injection from pasted blob**: a malicious blob could try to
  redirect the LLM. Worst case: garbage fields fill the form, user reviews
  before saving. Acceptable; we explicitly tell the user to verify.
- **Privacy**: pasted content (which often contains an api_key the user is
  trying to register) is sent to the chosen parser endpoint. Disclosed in
  the Settings modal footer; not silent.
- **Cost**: one short request per click. With `max_tokens=400`, expect
  &lt;$0.001 per parse on most models. No throttle needed.

## Implementation Order

1. Backend: `app_settings` table + store methods + migration.
2. Backend: `Provider.complete()` + OpenAI/Anthropic implementations.
3. Backend: `/api/settings/parser` GET/PUT.
4. Backend: `/api/ai-parse` POST.
5. Backend: tests for all of the above.
6. Frontend: API client methods.
7. Frontend: Settings modal.
8. Frontend: AddEndpointDialog AI Parse button + result wiring.
9. Manual UI smoke test: dev server + paste scenarios (clean JSON, messy
   prose, missing fields).

# llm-model-probe

CLI tool to register OpenAI/Anthropic API endpoints into a local SQLite registry
and probe per-model availability on demand.

Built for the workflow: someone hands over a `(base_url, api_key)`, you want
to know which models actually work — now and again next week.

## Install

```bash
git clone <this repo>
cd llm-model-probe
uv sync
uv run probe --help
```

For a global install:

```bash
uv tool install --from . llm-model-probe
probe --help
```

## Quick Start

```bash
# 1. Add an endpoint, auto-discover models, probe immediately
probe add --name bob-glm --sdk openai \
  --base-url https://glm.example.com/v1 \
  --api-key "$GLM_KEY" \
  --note "from Bob 2026-05-01"

# 2. Add an endpoint with specified models (skip discovery)
probe add --name partner-claude --sdk anthropic \
  --base-url https://api.anthropic.com \
  --api-key "$CLAUDE_KEY" \
  --models claude-3-5-sonnet-latest,claude-3-haiku-20240307

# 3. See registry overview
probe list

# 4. Detailed view (model-level status)
probe show bob-glm

# 5. Re-probe one endpoint, or all (24h cooldown unless --force)
probe retest bob-glm
probe retest --all

# 6. Export a report
probe export --format md -o report.md
probe export --format json | jq .

# 7. Remove an endpoint
probe rm bob-glm
```

## Configuration

First run creates `~/.llm-model-probe/config.toml`. Edit it to tune probe
behavior:

```toml
[probe]
concurrency = 5            # parallel probes per endpoint
timeout_seconds = 30
max_tokens = 8             # ask for a tiny completion only
prompt = "Hi"
retest_cooldown_hours = 24 # skip --all retest within this window

[filters]
exclude = [                # discover-mode skip list (fnmatch, case-insensitive)
    "*embedding*", "*whisper*", "*tts*", "*image*",
    "*moderation*", "*rerank*",
]
```

Override the data directory via `LLM_MODEL_PROBE_HOME=/some/path`.

## Storage

| Path | Purpose |
|---|---|
| `~/.llm-model-probe/probes.db` | SQLite registry (perms 0600) |
| `~/.llm-model-probe/config.toml` | Global probe + filter settings |

API keys are stored as plaintext in SQLite. The directory is `0700` and
the DB file is `0600`. Don't sync this directory to anything you don't trust.
The CLI masks keys in display (`sk-1...wxyz`).

## Discover vs Specified

- **Discover mode** (default): on `add`, calls `models.list()` and probes
  every returned model against the global filter. Best when the provider's
  `/v1/models` is honest.
- **Specified mode**: pass `--models a,b,c`. The list endpoint isn't called;
  filter is bypassed; only those models are probed. Use this for proxies that
  return fake models or hide them.

You can switch modes by `rm`-ing and `add`-ing again.

## Probe Semantics

- OpenAI: `chat.completions.create(model=…, messages=[{"role":"user","content":prompt}], max_tokens=8)`. On reasoning-model `max_completion_tokens` errors, retries with that param instead.
- Anthropic: `messages.create(model=…, max_tokens=8, messages=[…])`.
- Captures: success bool, latency, error class + message, first ~80 chars of response.
- `models.list()` failure on retest keeps the prior snapshot so you don't lose data when a key briefly fails.

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
- **Smart paste** — drop a JSON, dotenv block, or curl command into the Add dialog and it auto-fills the form.
- One-click retest / delete per row.
- "Retest all" button (blocks until done; no streaming progress in v1).
- Detail drawer shows model-level status with masked API key.

UI is local-only (binds to `127.0.0.1`). API keys are stored in the same SQLite file as the CLI; both share `~/.llm-model-probe/probes.db`.

## Docker

```bash
docker compose up -d --build
# UI on http://localhost:8765
# DB volume mounted from host ~/.llm-model-probe
```

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

## Testing

```bash
uv run pytest -q
```

## Out of Scope

Time-series history, scheduled probing, encrypted-at-rest keys, multi-user/auth.
See `docs/specs/2026-05-01-design.md` and `docs/specs/2026-05-01-ui-design.md`
for the full design rationale.

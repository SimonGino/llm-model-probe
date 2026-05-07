# llm-model-probe

CLI tool to register OpenAI/Anthropic API endpoints into a local SQLite registry
and probe per-model availability on demand.

Built for the workflow: someone hands over a `(base_url, api_key)`, you want
to know which models actually work — now and again next week.

## Install

```bash
git clone https://github.com/SimonGino/llm-model-probe.git
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
- **Discover then test** — Add registers the endpoint and lists models in 1–3s; you then choose which models to probe. No more waiting on a 50-model auto-probe.
- **Smart paste** — drop a JSON, dotenv block, or curl command into the Add dialog and it auto-fills the form.
- **Live progress** — each model probes via its own short HTTP call; rows update incrementally (`… testing` → ✓/✗) while the rest of the UI stays responsive.
- **One-click retest / delete** per row.
- "Retest all" runs across every endpoint; concurrency is throttled to 5 in-flight probes globally.
- Detail drawer shows model-level status with masked API key + checkbox to pick which models to test.

UI binds to `127.0.0.1` by default. API keys are stored in the same SQLite file as the CLI; both share `~/.llm-model-probe/probes.db`.

## Migrating between machines (dump / load)

The registry (endpoints + their api keys) lives in `~/.llm-model-probe/probes.db`. To move it to another machine — for example, when your test box and prod box drifted — use `probe dump` and `probe load`:

```bash
# On the source machine
probe dump --include-keys -o registry.json
scp registry.json prod-box:/tmp/

# On the destination
probe load /tmp/registry.json                       # default: skip name conflicts
probe load /tmp/registry.json --on-conflict=replace # overwrite local on conflict
probe load /tmp/registry.json --on-conflict=error   # abort if any conflict
```

By default `probe dump` writes `api_key: null` for every endpoint — safe to commit, share, or sync. Pass `--include-keys` to include plaintext keys; the output file is `chmod 0600`.

The web UI has a matching `Export` button (with the same `Include API keys` checkbox). There is no UI import — load is a CLI-only operation.

The dump format is endpoints-only: probe results, the discover-time filter list, and machine-local settings are not included. Run `probe retest --all` after a load to re-derive results.

## Docker

```bash
docker compose up -d --build
# UI on http://localhost:8765 (反代再决定要不要给公网)
# DB volume mounted from host ~/.llm-model-probe
```

或者直接拉预构建镜像（CI 推到 Docker Hub，支持 amd64 + arm64）：

```bash
docker pull simongino/llm-model-probe:latest
```

## 公网部署 (single user, token auth)

如果你想把这个工具暴露到公网（VPS 或家里 mac mini + 反代），加一道 token 墙就够单用户场景：

1. 生成一个长 token：
   ```bash
   openssl rand -hex 32
   ```
2. 写到 `.env` 或 host environment：
   ```bash
   echo "LLM_MODEL_PROBE_TOKEN=<上面那串>" >> .env
   ```
3. `docker compose up -d --build`
4. 反代加 HTTPS（Caddy 例）：
   ```
   probe.example.com {
       reverse_proxy localhost:8765
   }
   ```
   Caddy 自动签证书。

5. 浏览器开 `https://probe.example.com` → 弹登录页 → 输入 token → 进入 UI

**安全要点**：

- **绝对不要**直接暴露 `8765` 端口到公网（HTTP 明文 → token 被截听）
- 反代必须开 HTTPS
- `LLM_MODEL_PROBE_TOKEN` 没设 + 绑非 localhost = server 拒启（防呆）
- `/api/health` 永远不需要 token（给反代健康检查用）
- CLI（`probe add/list/...`）直接读 SQLite，不走 HTTP，不受 token 影响

直接在裸机上跑、绑 0.0.0.0 + 配 token：

```bash
export LLM_MODEL_PROBE_TOKEN=$(openssl rand -hex 32)
probe ui --listen 0.0.0.0
```

只本机用，跳过 token 和反代：
```bash
probe ui    # 默认 bind 127.0.0.1, 无认证
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

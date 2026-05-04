# 公网部署 + Token 认证 + Reveal Key 实施计划

> **给 agent 用**：用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 一个任务一个任务地执行。每步用 `- [ ]` 复选框跟踪。

**目标**：实现 `docs/specs/2026-05-04-public-deploy-design.md`：所有 `/api/*`（除 `/api/health`）按需启用 Bearer Token 认证；CLI `probe ui --listen` 选项 + 防呆；Drawer 显示 / 复制完整 API key。

**架构**：后端用 FastAPI HTTP middleware 做 token 校验（比 router 重组更小的 diff）；前端 fetch wrapper 自动带 `Authorization` header，401 触发登录页；ApiKeyReveal 是个小受控组件。

**技术栈**：FastAPI / Pydantic（后端），React + TypeScript + lucide-react + react-query（前端），Typer + Click 测试（CLI）。

---

## 文件结构

```
src/llm_model_probe/
├── api.py             # 修改: + auth middleware, + /api/auth/check, + /api/endpoints/{id}/api-key
└── cli.py             # 修改: probe ui 加 --listen + bind 防呆

frontend/src/
├── lib/
│   ├── auth.ts        # 新建: localStorage 封装
│   └── api.ts         # 修改: fetch wrapper 加 Bearer + 401 处理 + getApiKey + authCheck
├── components/
│   ├── LoginScreen.tsx       # 新建: 登录页
│   └── ApiKeyReveal.tsx      # 新建: 眼睛 + 复制
├── App.tsx            # 修改: 认证 gate + logout 按钮
└── components/EndpointDetailDrawer.tsx  # 修改: API key 行用 ApiKeyReveal

tests/
├── test_api_auth.py   # 新建
├── test_api_endpoints.py  # 修改: 加 reveal-key 测试 + 回归
└── test_cli.py        # 新建（小，仅 --listen 防呆）

README.md              # 修改: 加"公网部署"章节
docker-compose.yml     # 修改: 注入 LLM_MODEL_PROBE_TOKEN 示例
```

---

## 任务 1：后端 — Auth Middleware + 测试

**文件**：
- 修改：`src/llm_model_probe/api.py`
- 新建：`tests/test_api_auth.py`

- [ ] **步骤 1：写失败测试**

新建 `tests/test_api_auth.py`：

```python
"""Authentication middleware tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app


def test_no_token_env_means_no_auth_required(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/api/endpoints")
    assert r.status_code == 200


def test_token_set_blocks_unauthenticated(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/endpoints")
    assert r.status_code == 401


def test_token_set_allows_correct_bearer(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


def test_token_set_rejects_wrong_bearer(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_token_set_rejects_missing_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "s3cret"},  # no "Bearer " prefix
    )
    assert r.status_code == 401


def test_health_no_auth_even_with_token_set(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """/api/health is exempt — reverse proxy health check 用得着."""
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_non_api_path_no_auth_even_with_token_set(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Static files (HTML/JS) 不需要 token, 否则登录页本身都进不来."""
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/")
    # 静态没挂载所以 404 — 但不应该是 401
    assert r.status_code != 401
```

- [ ] **步骤 2：跑测试确认失败**

Run: `cd ~/Code/Tools/llm-model-probe && uv run pytest tests/test_api_auth.py -q`
Expected: 5 个 fail（带 token 的请求都返回 200 而不是 401，因为还没加 middleware）。

- [ ] **步骤 3：实现 middleware**

修改 `src/llm_model_probe/api.py`，imports 顶部加：

```python
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
```

（`Request` / `JSONResponse` 是新加的）

在 CORS middleware 之后、所有路由之前，加：

```python
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    expected = os.environ.get("LLM_MODEL_PROBE_TOKEN", "")
    if not expected:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path == "/api/health":
        return await call_next(request)
    if request.method == "OPTIONS":
        # CORS preflight, 不卡 token
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "missing bearer token"},
        )
    if auth_header[len("Bearer ") :] != expected:
        return JSONResponse(
            status_code=401,
            content={"detail": "invalid token"},
        )

    return await call_next(request)
```

- [ ] **步骤 4：跑测试确认通过**

Run: `uv run pytest tests/test_api_auth.py -q`
Expected: 7 个 pass。

- [ ] **步骤 5：跑完整测试套件检查没回归**

Run: `uv run pytest -q`
Expected: 全绿。其他测试没设 LLM_MODEL_PROBE_TOKEN，middleware 直接放行，不影响。

- [ ] **步骤 6：提交**

```bash
cd ~/Code/Tools/llm-model-probe
git add src/llm_model_probe/api.py tests/test_api_auth.py
git commit -m "feat(api): Bearer token middleware (env LLM_MODEL_PROBE_TOKEN)"
```

---

## 任务 2：后端 — `/api/auth/check` endpoint

**文件**：
- 修改：`src/llm_model_probe/api.py`
- 修改：`tests/test_api_auth.py`

- [ ] **步骤 1：追加测试**

在 `tests/test_api_auth.py` 末尾加：

```python
def test_auth_check_with_valid_token(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/auth/check",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_auth_check_without_token(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/auth/check")
    assert r.status_code == 401


def test_auth_check_when_disabled(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """没设 token 也应该返回 200（前端用这个判断"我能直接进了"）."""
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/api/auth/check")
    assert r.status_code == 200
```

- [ ] **步骤 2：跑测试确认 fail**

Run: `uv run pytest tests/test_api_auth.py::test_auth_check_when_disabled -q`
Expected: 404（路径不存在）。

- [ ] **步骤 3：实现 endpoint**

`src/llm_model_probe/api.py`，在 `health` 路由之后加：

```python
class AuthCheckResponse(BaseModel):
    ok: bool


@app.get("/api/auth/check", response_model=AuthCheckResponse)
def auth_check() -> AuthCheckResponse:
    # middleware 已经验过 token；走到这里就是认证通过（或没启用 auth）
    return AuthCheckResponse(ok=True)
```

- [ ] **步骤 4：跑测试**

Run: `uv run pytest tests/test_api_auth.py -q`
Expected: 全绿。

- [ ] **步骤 5：提交**

```bash
git add src/llm_model_probe/api.py tests/test_api_auth.py
git commit -m "feat(api): /api/auth/check 让前端判断 token 有效性"
```

---

## 任务 3：后端 — `GET /api/endpoints/{id}/api-key`

**文件**：
- 修改：`src/llm_model_probe/api.py`
- 修改：`tests/test_api_endpoints.py`

- [ ] **步骤 1：写失败测试**

`tests/test_api_endpoints.py` 末尾追加：

```python
def test_get_api_key_returns_full_plaintext(
    client: TestClient, isolated_home: Path
) -> None:
    """专属 endpoint 返回完整明文 key."""
    raw_key = "sk-FULL-PLAINTEXT-1234567890"
    create = client.post(
        "/api/endpoints",
        json={
            "name": "fullkey",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]
    r = client.get(f"/api/endpoints/{ep_id}/api-key")
    assert r.status_code == 200, r.text
    assert r.json() == {"api_key": raw_key}


def test_get_api_key_unknown_endpoint_404(client: TestClient) -> None:
    r = client.get("/api/endpoints/ep_zzzzzz/api-key")
    assert r.status_code == 404


def test_detail_still_masks_api_key(
    client: TestClient, isolated_home: Path
) -> None:
    """回归: 详情接口不能因为加了 api-key endpoint 就也返回明文."""
    raw_key = "sk-MUST-NOT-LEAK-IN-DETAIL-1234"
    create = client.post(
        "/api/endpoints",
        json={
            "name": "mask-test",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]
    detail = client.get(f"/api/endpoints/{ep_id}").text
    assert raw_key not in detail
    detail_json = client.get(f"/api/endpoints/{ep_id}").json()
    assert "api_key" not in detail_json  # 没有 api_key 字段, 只有 api_key_masked
    assert detail_json["api_key_masked"].startswith("sk-M")
    assert detail_json["api_key_masked"].endswith("1234")
```

- [ ] **步骤 2：跑测试确认 fail**

Run: `uv run pytest tests/test_api_endpoints.py -q`
Expected: 3 个 fail（`/api-key` 路径 404）。

- [ ] **步骤 3：实现 endpoint**

`src/llm_model_probe/api.py`，找到 `set_tags` 路由，在它之后追加：

```python
class ApiKeyResponse(BaseModel):
    api_key: str


@app.get(
    "/api/endpoints/{name_or_id}/api-key",
    response_model=ApiKeyResponse,
)
def get_api_key(name_or_id: str) -> ApiKeyResponse:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return ApiKeyResponse(api_key=ep.api_key)
```

- [ ] **步骤 4：跑测试**

Run: `uv run pytest -q`
Expected: 全绿。

- [ ] **步骤 5：提交**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): GET /api/endpoints/{id}/api-key 显式取明文 key"
```

---

## 任务 4：CLI `--listen` 选项 + 防呆

**文件**：
- 修改：`src/llm_model_probe/cli.py`
- 新建：`tests/test_cli.py`

- [ ] **步骤 1：写失败测试**

新建 `tests/test_cli.py`：

```python
"""CLI command-level tests (light, only the bind safeguard)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from llm_model_probe.cli import app

runner = CliRunner()


def test_ui_refuses_non_localhost_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """绑非-localhost 且没配 token → 报错退出 1."""
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(tmp_path))
    result = runner.invoke(
        app, ["ui", "--listen", "0.0.0.0", "--no-browser", "--port", "18999"]
    )
    assert result.exit_code == 1
    # 错误消息提示如何修
    out = (result.stdout + (result.stderr or "")).lower()
    assert "llm_model_probe_token" in out or "token" in out


def test_ui_allows_non_localhost_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """绑非-localhost + 配了 token → 通过防呆.

    （我们不真起 server, 只验证防呆不再 abort. 用 monkeypatch 替换 uvicorn.run.）
    """
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(tmp_path))

    called = {}

    def fake_run(app_str, host, port):
        called["host"] = host
        called["port"] = port

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = runner.invoke(
        app,
        ["ui", "--listen", "0.0.0.0", "--no-browser", "--port", "18999", "--dev"],
    )
    # --dev 跳过 dist 检查, 进入 uvicorn.run (我们 fake 了)
    assert result.exit_code == 0
    assert called["host"] == "0.0.0.0"
```

- [ ] **步骤 2：跑测试确认 fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: 第一个 fail（CLI 还没加 `--listen`）；第二个可能也 fail。

- [ ] **步骤 3：修改 `probe ui` 命令**

打开 `src/llm_model_probe/cli.py`，找到 `def ui(...)`，整体替换成：

```python
@app.command()
def ui(
    port: int = typer.Option(8765, "--port"),
    listen: str = typer.Option(
        "127.0.0.1",
        "--listen",
        help="Bind address. 默认 127.0.0.1 仅本机；公网部署用 0.0.0.0.",
    ),
    no_browser: bool = typer.Option(False, "--no-browser"),
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Dev mode: assume vite dev server at :5173, skip static mount",
    ),
) -> None:
    """Start the local web UI."""
    import os
    import webbrowser
    from pathlib import Path

    import uvicorn

    is_localhost = listen in ("127.0.0.1", "localhost", "::1")
    if not is_localhost and not os.environ.get("LLM_MODEL_PROBE_TOKEN"):
        console.print(
            "[red]✗[/red] 拒绝绑非-localhost 地址而 LLM_MODEL_PROBE_TOKEN 未设置。\n"
            "  公网/局域网部署前请先 export LLM_MODEL_PROBE_TOKEN=<密钥>。"
        )
        raise typer.Exit(1)

    if dev:
        os.environ["LLM_MODEL_PROBE_DEV"] = "1"
    else:
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

    url = f"http://{listen}:{port}"
    console.print(f"[green]→[/green] {url}")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run("llm_model_probe.api:app", host=listen, port=port)
```

- [ ] **步骤 4：跑 CLI 测试**

Run: `uv run pytest tests/test_cli.py -q`
Expected: 2 个 pass。

- [ ] **步骤 5：跑完整套件**

Run: `uv run pytest -q`
Expected: 全绿。

- [ ] **步骤 6：提交**

```bash
git add src/llm_model_probe/cli.py tests/test_cli.py
git commit -m "feat(cli): probe ui --listen + 没 token 时拒绑非 localhost"
```

---

## 任务 5：前端 — `auth.ts` + `api.ts` Bearer/401 改造

**文件**：
- 新建：`frontend/src/lib/auth.ts`
- 修改：`frontend/src/lib/api.ts`

- [ ] **步骤 1：新建 `auth.ts`**

`frontend/src/lib/auth.ts`：

```ts
const KEY = "llm_model_probe_token";

export const auth = {
  get: (): string => localStorage.getItem(KEY) ?? "",
  set: (token: string): void => localStorage.setItem(KEY, token),
  clear: (): void => localStorage.removeItem(KEY),
};

export class UnauthorizedError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "UnauthorizedError";
  }
}
```

- [ ] **步骤 2：改造 `api.ts`**

完整替换 `frontend/src/lib/api.ts`：

```ts
import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  PasteSuggestion,
  ModelResultPublic,
} from "./types";
import { auth, UnauthorizedError } from "./auth";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = auth.get();
  const headers: Record<string, string> = body
    ? { "Content-Type": "application/json" }
    : {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) {
    auth.clear();
    throw new UnauthorizedError();
  }
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(`${r.status} ${detail}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  authCheck: () => req<{ ok: boolean }>("GET", "/api/auth/check"),
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
  probeModel: (id: string, model: string) =>
    req<ModelResultPublic>(
      "POST",
      `/api/endpoints/${encodeURIComponent(id)}/probe-model`,
      { model },
    ),
  setTags: (idOrName: string, tags: string[]) =>
    req<EndpointSummary>(
      "PUT",
      `/api/endpoints/${encodeURIComponent(idOrName)}/tags`,
      { tags },
    ),
  getApiKey: (idOrName: string) =>
    req<{ api_key: string }>(
      "GET",
      `/api/endpoints/${encodeURIComponent(idOrName)}/api-key`,
    ),
};
```

- [ ] **步骤 3：build 验证**

Run: `cd ~/Code/Tools/llm-model-probe/frontend && npm run build 2>&1 | tail -5`
Expected: 成功（UI 还没用 401 处理，但代码是合法的 TS）。

- [ ] **步骤 4：提交**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/lib/auth.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): auth.ts + api.ts 加 Bearer header + 401 → UnauthorizedError"
```

---

## 任务 6：前端 — LoginScreen + App 认证 gate + Logout

**文件**：
- 新建：`frontend/src/components/LoginScreen.tsx`
- 修改：`frontend/src/App.tsx`

- [ ] **步骤 1：新建 LoginScreen**

`frontend/src/components/LoginScreen.tsx`：

```tsx
import { useState } from "react";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginScreen({
  onSuccess,
}: {
  onSuccess: () => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    auth.set(token.trim());
    try {
      await api.authCheck();
      onSuccess();
    } catch (err) {
      auth.clear();
      if (err instanceof UnauthorizedError) {
        setError("Token 无效");
      } else {
        setError(`${err}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 border rounded-lg p-6 bg-card"
      >
        <div>
          <h1 className="text-xl font-bold">llm-model-probe</h1>
          <p className="text-sm text-muted-foreground mt-1">
            访问需要 token
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="token">Access token</Label>
          <Input
            id="token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
            disabled={busy}
          />
        </div>
        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        <Button type="submit" disabled={busy || !token.trim()} className="w-full">
          {busy ? "校验中…" : "Continue"}
        </Button>
      </form>
    </div>
  );
}
```

- [ ] **步骤 2：改造 `App.tsx`**

完整替换 `frontend/src/App.tsx`：

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";
import LoginScreen from "@/components/LoginScreen";

export default function App() {
  const [bumpAuth, setBumpAuth] = useState(0);
  const authState = useQuery({
    queryKey: ["auth-check", bumpAuth],
    queryFn: api.authCheck,
    retry: false,
  });

  if (authState.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-muted-foreground">
        校验登录…
      </div>
    );
  }
  if (authState.error instanceof UnauthorizedError) {
    return <LoginScreen onSuccess={() => setBumpAuth((n) => n + 1)} />;
  }
  if (authState.error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-destructive">
        服务异常: {String(authState.error)}
      </div>
    );
  }
  return <MainApp onLogout={() => {
    auth.clear();
    setBumpAuth((n) => n + 1);
  }} />;
}

function MainApp({ onLogout }: { onLogout: () => void }) {
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const orch = useProbeOrchestrator();
  const totalPending = orch.totalPending();

  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [autoTest, setAutoTest] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<Set<string>>(new Set());

  async function retestEverything() {
    if (!list.data) return;
    for (const ep of list.data) {
      if (ep.total_models === 0) continue;
      const detail = await api.getEndpoint(ep.id);
      void orch.run(ep.id, detail.models);
    }
  }

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">llm-model-probe</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={totalPending > 0}
            onClick={retestEverything}
          >
            {totalPending > 0
              ? `Retesting (${totalPending} in flight)…`
              : "↻ Retest all"}
          </Button>
          <Button onClick={() => setShowAdd(true)}>+ Add endpoint</Button>
          <Button variant="ghost" onClick={onLogout} title="Logout">
            ↪
          </Button>
        </div>
      </div>

      {list.isLoading && (
        <div className="text-muted-foreground">Loading…</div>
      )}
      {list.error && (
        <div className="text-destructive">Error: {String(list.error)}</div>
      )}
      {list.data && (
        <EndpointTable
          endpoints={list.data}
          search={search}
          setSearch={setSearch}
          tagFilter={tagFilter}
          setTagFilter={setTagFilter}
          onSelect={(id) => {
            setSelected(id);
            setAutoTest(false);
          }}
          onRetest={(id) => {
            setSelected(id);
            setAutoTest(true);
          }}
        />
      )}

      <AddEndpointDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(id) => setSelected(id)}
      />
      <EndpointDetailDrawer
        idOrName={selected}
        autoTest={autoTest}
        onAutoTestConsumed={() => setAutoTest(false)}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
```

- [ ] **步骤 3：build 验证**

Run: `cd ~/Code/Tools/llm-model-probe/frontend && npm run build 2>&1 | tail -5`
Expected: 成功。

- [ ] **步骤 4：本地烟雾测试**

```bash
cd ~/Code/Tools/llm-model-probe
pkill -f "uvicorn.*8765" 2>/dev/null; sleep 1
# 不带 token, 老路径
uv run probe ui --no-browser --port 8765 &
sleep 2
curl -s http://localhost:8765/api/auth/check    # 期望 {"ok":true}
echo
pkill -f "uvicorn.*8765"; sleep 1

# 带 token
LLM_MODEL_PROBE_TOKEN=secret123 uv run probe ui --no-browser --port 8765 &
sleep 2
echo "=== 不带 token ==="
curl -s -w "\nHTTP %{http_code}\n" http://localhost:8765/api/auth/check
echo "=== 错 token ==="
curl -s -w "\nHTTP %{http_code}\n" -H "Authorization: Bearer wrong" http://localhost:8765/api/auth/check
echo "=== 对的 token ==="
curl -s -w "\nHTTP %{http_code}\n" -H "Authorization: Bearer secret123" http://localhost:8765/api/auth/check
pkill -f "uvicorn.*8765"
```

Expected: 401, 401, 200。

浏览器测试：开 http://localhost:8765 → 弹登录页 → 输 `secret123` → 进入 App。点右上角 ↪ → 回到登录页。

- [ ] **步骤 5：提交**

```bash
git add frontend/src/components/LoginScreen.tsx frontend/src/App.tsx
git commit -m "feat(frontend): LoginScreen + auth gate + logout 按钮"
```

---

## 任务 7：前端 — ApiKeyReveal 组件 + 接入 Drawer

**文件**：
- 新建：`frontend/src/components/ApiKeyReveal.tsx`
- 修改：`frontend/src/components/EndpointDetailDrawer.tsx`

- [ ] **步骤 1：新建 ApiKeyReveal 组件**

`frontend/src/components/ApiKeyReveal.tsx`：

```tsx
import { useState } from "react";
import { Eye, EyeOff, Copy, Check } from "lucide-react";
import { api } from "@/lib/api";

export default function ApiKeyReveal({
  endpointId,
  masked,
}: {
  endpointId: string;
  masked: string;
}) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  async function ensureFull(): Promise<string> {
    if (revealed) return revealed;
    setBusy(true);
    try {
      const { api_key } = await api.getApiKey(endpointId);
      setRevealed(api_key);
      return api_key;
    } finally {
      setBusy(false);
    }
  }

  async function toggleReveal() {
    if (revealed) {
      setRevealed(null);
      return;
    }
    await ensureFull();
  }

  async function copy() {
    const k = await ensureFull();
    await navigator.clipboard.writeText(k);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <span className="inline-flex items-center gap-1">
      <code className="text-xs">{revealed ?? masked}</code>
      <button
        type="button"
        title={revealed ? "Hide" : "Reveal"}
        onClick={toggleReveal}
        disabled={busy}
        className="text-muted-foreground hover:text-foreground p-1 rounded flex-shrink-0"
      >
        {revealed ? (
          <EyeOff className="h-3.5 w-3.5" />
        ) : (
          <Eye className="h-3.5 w-3.5" />
        )}
      </button>
      <button
        type="button"
        title="Copy full api_key"
        onClick={copy}
        disabled={busy}
        className="text-muted-foreground hover:text-foreground p-1 rounded flex-shrink-0"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-600" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </span>
  );
}
```

- [ ] **步骤 2：在 Drawer 里替换 API key 行**

修改 `frontend/src/components/EndpointDetailDrawer.tsx`：

a) 顶部 imports 加：

```tsx
import ApiKeyReveal from "./ApiKeyReveal";
```

b) 找到 `<Row label="API key">`，替换：

```tsx
              <Row label="API key">
                <ApiKeyReveal endpointId={d.id} masked={d.api_key_masked} />
              </Row>
```

- [ ] **步骤 3：build 验证**

Run: `cd ~/Code/Tools/llm-model-probe/frontend && npm run build 2>&1 | tail -5`
Expected: 成功。

- [ ] **步骤 4：本地烟雾测试**

restart server（不带 token 也行），开浏览器，进 drawer：

- API key 行显示 `sk-f...426d` + 眼睛 + 复制
- 点眼睛：变 EyeOff，code 显示完整 key
- 再点眼睛：回到 mask
- 点复制：1.2s 显示绿色 ✓，剪贴板有完整 key

- [ ] **步骤 5：提交**

```bash
cd ~/Code/Tools/llm-model-probe
git add frontend/src/components/ApiKeyReveal.tsx frontend/src/components/EndpointDetailDrawer.tsx
git commit -m "feat(frontend): drawer API key 行加 reveal/copy"
```

---

## 任务 8：Docker compose + README "公网部署"章节

**文件**：
- 修改：`docker-compose.yml`
- 修改：`README.md`

- [ ] **步骤 1：改 docker-compose.yml**

替换 `docker-compose.yml`：

```yaml
services:
  probe:
    build: .
    image: llm-model-probe:latest
    container_name: llm-model-probe
    environment:
      # 公网部署务必设置一个长 token，例如:
      #   openssl rand -hex 32
      # 没设的话只能从容器内本机访问 (绑 0.0.0.0 + 没 token = server 拒启)
      - LLM_MODEL_PROBE_TOKEN=${LLM_MODEL_PROBE_TOKEN:-}
    ports:
      # 默认只 bind 宿主 localhost; 反代来负责对外
      - "127.0.0.1:8765:8765"
    volumes:
      - ${HOME}/.llm-model-probe:/data
    restart: unless-stopped
```

- [ ] **步骤 2：在 README.md 现有 `## Docker` 章节替换为完整的部署章节**

打开 `README.md`，找到 `## Docker` 章节，整体替换为：

```markdown
## Docker

```bash
docker compose up -d --build
# UI on http://localhost:8765 (反代再决定要不要给公网)
# DB volume mounted from host ~/.llm-model-probe
```

## 公网部署 (single user, token auth)

如果你想把这个工具暴露到公网（VPS 或家里 mac mini + 反代），加一道 token
墙就够单用户场景：

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
- token 没设 + 绑非 localhost = server 拒启（防呆）
- CLI（`probe add/list/...`）直接读 SQLite，不走 HTTP，不受 token 影响

如果只本机用，跳过 token 和反代：
```bash
probe ui    # 默认 bind 127.0.0.1, 无认证
```
```

- [ ] **步骤 3：最终验证**

```bash
cd ~/Code/Tools/llm-model-probe
uv run pytest -q                            # 后端测试全过
cd frontend && npm run build && cd ..       # 前端 build 成功
uv run probe --help                         # CLI 还在
uv run probe ui --help | grep listen        # --listen 选项存在
```

期望：所有测试绿；build 成功；`--listen` 在 ui 命令的选项里。

- [ ] **步骤 4：提交**

```bash
git add docker-compose.yml README.md
git commit -m "docs: README 加公网部署章节 + docker-compose 注入 LLM_MODEL_PROBE_TOKEN"
```

---

## 自审复核

**Spec 覆盖**：
- ✅ Bearer Token middleware：任务 1
- ✅ `/api/health` 例外：任务 1（middleware 内白名单）
- ✅ `/api/auth/check`：任务 2
- ✅ `/api/endpoints/{id}/api-key` 完整明文 + 详情仍 mask（回归）：任务 3
- ✅ CLI `--listen` + 防呆：任务 4
- ✅ 没 token + localhost = 老模式：任务 1（middleware "if not expected: return await call_next"）
- ✅ 前端 token 存 localStorage：任务 5（auth.ts）
- ✅ 前端每个 fetch 自动带 Bearer + 401 处理：任务 5（api.ts）
- ✅ LoginScreen + App gate：任务 6
- ✅ Logout 按钮：任务 6
- ✅ ApiKeyReveal 眼睛 + 复制：任务 7
- ✅ docker-compose 注入 token：任务 8
- ✅ README 公网部署文档：任务 8
- ✅ CLI 数据层不动（add/list/show 等）：plan 全程没改这些命令 → ✓

**占位符扫描**：每步都有完整代码，无 TBD / "类似任务 N"。

**类型一致性**：
- `auth.get/set/clear` 在 auth.ts 定义、api.ts 和 LoginScreen 使用，签名一致
- `UnauthorizedError` 在 auth.ts 定义、api.ts throw、App.tsx instanceof 判断 —— 一致
- `api.authCheck()` 返回 `{ok: boolean}`，用作 react-query 的 queryFn —— 一致
- `api.getApiKey(idOrName)` 返回 `{api_key: string}`，ApiKeyReveal 解构使用 —— 一致
- 后端 `LLM_MODEL_PROBE_TOKEN` env var 名字在 middleware、CLI 防呆、docker-compose、README 全部一致

**测试隔离**：
- `test_api_auth.py` 用 `monkeypatch` 设/清除 env var；不污染其他测试
- `test_cli.py` 同样 monkeypatch + tmp_path 隔离 HOME

实施计划已就绪。

# 公网部署 + Token 认证 + Reveal API Key

**日期**: 2026-05-04
**状态**: 已口头确认
**基于**: `docs/specs/2026-05-01-design.md`、`2026-05-01-ui-design.md`、`2026-05-02-probe-redesign-design.md`

## 目标

让这个工具能**安全地暴露在公网**，单用户访问。同时解决"想看到并复制自己 API key"的体验问题。

具体场景：
- 用户把 server 部署到 VPS / 家里 mac mini 通过 frp 穿透 / 反代到公网域名
- 浏览器从公网访问 → 弹登录页 → 输入 token → 进入 UI
- 任何未带正确 token 的请求一律 401，包括拿 API key 的接口
- 浏览器记住 token（localStorage），下次自动带上不用重输

## 不做的事

- 多用户 / 多 token（单 token 共享）
- Token 轮转管理 UI（直接改 env var 重启服务即可）
- HTTPS 终端（用反代 Caddy/Cloudflare/nginx 来做，不在 app 里）
- 加密静态存储（SSH 隧道 + 文件权限够当前威胁模型；如果 key 价值变高再开 Tier 3 单独做）
- Token 过期 / 滑动续期（单用户场景过度）
- 限流 / 暴力破解防御（反代层 fail2ban 之类来做）
- 审计日志

## 安全模型

**威胁**：公网上随机扫描器 / 路过的人想拿到我的 API key 列表 / 删除我的 endpoint。

**防御**：
- 所有 `/api/*` 路由都要 `Authorization: Bearer <token>` 头才放行（除 `/api/health`）
- 静态资源（HTML/JS/CSS）不需要 token 也能拿（前端就是个登录页 + 应用）
- token 通过环境变量 `LLM_MODEL_PROBE_TOKEN` 配置
- **没配 token + 绑非 localhost = 服务器拒绝启动**（防呆，避免裸奔）
- 没配 token + 绑 localhost = 现有本地无认证模式不变（你 mac 上现在用的）

**不防御**：
- 反代后没开 HTTPS 的 token 截听 → 文档里强烈建议 HTTPS
- 反代被绕过直接打 8765 端口 → 反代部署时端口隔离 / 防火墙的事
- 内存 dump / 物理盗取 → 不在威胁模型里

## API 改动

### 认证逻辑（middleware-style）

```python
# api.py 顶部
EXPECTED_TOKEN = os.environ.get("LLM_MODEL_PROBE_TOKEN", "")

def require_token(authorization: str | None = Header(default=None)) -> None:
    if not EXPECTED_TOKEN:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization[7:] != EXPECTED_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
```

应用到所有 `/api/*` 路由。FastAPI 用 `dependencies=[Depends(require_token)]`：
- 路由级一个个加 → 麻烦
- **更好**：用 router + 全局 dependency

实施方法：把所有 `/api/*` 路由迁到 `APIRouter`，在 router 上挂 `dependencies`：

```python
api_router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

@api_router.get("/endpoints", ...)
def list_endpoints(): ...

# health 例外（用于反代健康检查 + 前端启动探测）
health_router = APIRouter(prefix="/api")

@health_router.get("/health")
def health(): ...

app.include_router(health_router)  # 不需要 token
app.include_router(api_router)     # 需要 token
```

### 新增：`GET /api/auth/check`

```python
class AuthCheckResponse(BaseModel):
    ok: bool

@api_router.get("/auth/check", response_model=AuthCheckResponse)
def auth_check() -> AuthCheckResponse:
    return AuthCheckResponse(ok=True)
```

前端用这个判断"我的 token 还有效吗"。401 → 提示重输 token。

### 新增：`GET /api/endpoints/{name_or_id}/api-key`

```python
class ApiKeyResponse(BaseModel):
    api_key: str

@api_router.get(
    "/endpoints/{name_or_id}/api-key",
    response_model=ApiKeyResponse,
)
def get_api_key(name_or_id: str) -> ApiKeyResponse:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return ApiKeyResponse(api_key=ep.api_key)
```

继续保留 `EndpointDetail.api_key_masked` mask 形式 —— 默认所有响应都不回完整 key，**只有显式调这一个 endpoint** 才返回。理由：
- devtools network 历史 / 截图 debug 不会到处是明文
- shoulder-surfing 防护
- 以后真要做更细粒度审计，gate 这一个就够

## CLI 改动

### `probe ui` 加 `--listen` 选项

```python
@app.command()
def ui(
    port: int = typer.Option(8765, "--port"),
    listen: str = typer.Option("127.0.0.1", "--listen",
        help="Bind address. Use 0.0.0.0 to listen on all interfaces (公网部署时)"),
    no_browser: bool = typer.Option(False, "--no-browser"),
    dev: bool = typer.Option(False, "--dev", help="Dev mode"),
) -> None:
    ...
    # 防呆：非 localhost + 没配 token 直接拒绝启动
    is_localhost = listen in ("127.0.0.1", "localhost", "::1")
    if not is_localhost and not os.environ.get("LLM_MODEL_PROBE_TOKEN"):
        console.print(
            "[red]✗[/red] 拒绝绑非-localhost 地址当 LLM_MODEL_PROBE_TOKEN 没配置时。\n"
            "  公网部署请先 export LLM_MODEL_PROBE_TOKEN=<密钥>。"
        )
        raise typer.Exit(1)
    ...
    uvicorn.run("llm_model_probe.api:app", host=listen, port=port)
```

CLI 数据层操作（`add / list / show / retest / rm / export`）**完全不动** —— 直接读 SQLite，跟 token 无关。

## 前端改动

### 1. 新建 `lib/auth.ts`

```ts
const KEY = "llm_model_probe_token";

export const auth = {
  get: (): string => localStorage.getItem(KEY) ?? "",
  set: (token: string): void => localStorage.setItem(KEY, token),
  clear: (): void => localStorage.removeItem(KEY),
};
```

### 2. 修改 `lib/api.ts`

每个请求自动带 token。封装 `req` 函数加：

```ts
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
    // 触发 App 重新渲染到登录页 —— 通过抛已知 error type
    throw new UnauthorizedError();
  }
  // ... 既有逻辑
}

export class UnauthorizedError extends Error {}
```

### 3. 新增 `getApiKey` 方法

```ts
getApiKey: (idOrName: string) =>
  req<{ api_key: string }>(
    "GET",
    `/api/endpoints/${encodeURIComponent(idOrName)}/api-key`,
  ),
```

### 4. 新增 `LoginScreen.tsx`

```
┌───────────────────────────────┐
│  llm-model-probe              │
│                               │
│  Access token                 │
│  [_______________________]    │
│                               │
│  [    Continue    ]           │
│                               │
│  错误提示：token 无效（如有）  │
└───────────────────────────────┘
```

- 一个 input + 一个按钮
- 点 Continue → 写 localStorage → 调 `/api/auth/check` 验证 → 通过则刷新页面 / 重渲染 App，401 则显示错误并清掉
- 居中布局，最简

### 5. 修改 `App.tsx` 加认证 gate

```tsx
function App() {
  const [token, setToken] = useState(auth.get());
  const check = useQuery({
    queryKey: ["auth-check"],
    queryFn: api.authCheck,
    enabled: !!token,
    retry: false,
  });

  // 没 token 或 check 失败 → 登录页
  if (!token || check.error) {
    return <LoginScreen onSuccess={(t) => { auth.set(t); setToken(t); }} />;
  }
  if (check.isLoading) {
    return <div className="p-6 text-muted-foreground">校验登录…</div>;
  }
  // 正常 App 树（既有内容）
  return <MainApp />;
}
```

### 6. Header 加退出按钮

主界面顶栏 `+ Add endpoint` 按钮旁边加一个 `↪ Logout`：点击 → `auth.clear()` + `setToken("")` → 回到 LoginScreen。

### 7. Drawer 的 API Key 行加 reveal/copy

把现在 `<code>{d.api_key_masked}</code>` 改成 `<ApiKeyReveal endpointId={d.id} masked={d.api_key_masked} />`：

```tsx
function ApiKeyReveal({ endpointId, masked }) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function fetchFull(): Promise<string> {
    if (revealed) return revealed;
    const { api_key } = await api.getApiKey(endpointId);
    setRevealed(api_key);
    return api_key;
  }

  return (
    <span className="flex items-center gap-1">
      <code>{revealed ?? masked}</code>
      <button onClick={() => revealed ? setRevealed(null) : fetchFull()}>
        {revealed ? <EyeOff/> : <Eye/>}
      </button>
      <button onClick={async () => {
        const k = await fetchFull();
        await navigator.clipboard.writeText(k);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}>
        {copied ? <Check className="text-green-600"/> : <Copy/>}
      </button>
    </span>
  );
}
```

state 不进 react-query 缓存（关 drawer 重新打开就重置回 mask）。

## Docker / 部署文档

### Dockerfile 不变（已经支持 env var）

### docker-compose.yml 加示例

```yaml
services:
  probe:
    build: .
    environment:
      - LLM_MODEL_PROBE_TOKEN=${LLM_MODEL_PROBE_TOKEN}  # 必须从 .env 或 host env 注入
    ports:
      - "127.0.0.1:8765:8765"   # 默认只本机访问，反代再决定要不要给公网
    volumes:
      - ${HOME}/.llm-model-probe:/data
    restart: unless-stopped
```

### README 新增"公网部署"章节

```markdown
## 公网部署

1. 生成一个长 token: `openssl rand -hex 32`
2. 写到 .env: `LLM_MODEL_PROBE_TOKEN=<token>`
3. `docker compose up -d`
4. 反代（Caddy 例）：

   ```
   probe.example.com {
       reverse_proxy localhost:8765
   }
   ```
   Caddy 自动签 HTTPS 证书。

5. 访问 https://probe.example.com → 弹登录页 → 输入 token

**绝对不要**直接把 8765 暴露到公网（HTTP 明文 → token 被截听）。
```

## 后端测试

`tests/test_api_auth.py` 新文件：

- `test_auth_disabled_when_no_env_var` —— LLM_MODEL_PROBE_TOKEN 未设 → `/api/endpoints` 直接 200 返回（保留本地兼容）
- `test_auth_required_when_env_var_set` —— monkeypatch env，请求不带 Authorization → 401
- `test_auth_invalid_token_401`
- `test_auth_valid_token_200`
- `test_auth_check_endpoint`（带 token → 200，不带 → 401）
- `test_health_endpoint_no_auth_required` —— `/api/health` 永远不要 token

`tests/test_api_endpoints.py` 加：
- `test_get_api_key_returns_full_plaintext`
- `test_get_api_key_unknown_endpoint_404`
- `test_detail_still_masks_api_key`（回归）

`tests/test_cli.py`（如果不存在则新建）：
- `test_ui_refuses_non_localhost_without_token` —— monkeypatch env 没 token + `--listen 0.0.0.0` → CLI 报错退出 1

## 兼容性

- 老 DB 不变
- 现有 API 调用方**如果不在乎 token**（即没设 env var）= 完全兼容，老路径继续工作
- 一旦设了 token，所有客户端必须带 Bearer header；UI 自动处理（首次弹登录页），CLI 不受影响

## 文件结构

```
src/llm_model_probe/
├── api.py             # 修改：拆 router + 加 require_token + 加 /auth/check + /api-key
└── cli.py             # 修改：probe ui 加 --listen + 防呆

frontend/src/
├── lib/
│   ├── auth.ts        # 新建：token localStorage 封装
│   └── api.ts         # 修改：每个请求带 Authorization header；UnauthorizedError
├── components/
│   ├── LoginScreen.tsx       # 新建：登录页
│   └── ApiKeyReveal.tsx      # 新建：眼睛 + 复制 + mask
└── App.tsx            # 修改：认证 gate + logout 按钮

tests/
├── test_api_auth.py   # 新建
├── test_api_endpoints.py  # 修改：加 reveal-key 相关测试
└── test_cli.py        # 新建（小）

README.md              # 修改：加"公网部署"章节
docker-compose.yml     # 修改：注入 LLM_MODEL_PROBE_TOKEN env
```

## 工作量估计

- 后端 router 重组 + auth dep + 测试 ≈ 2-3 小时
- reveal-key endpoint + 测试 ≈ 30 分钟
- CLI `--listen` + 防呆 + 测试 ≈ 30 分钟
- 前端 auth.ts + api.ts 改造 + LoginScreen + App gate + Logout ≈ 2 小时
- 前端 ApiKeyReveal 组件 ≈ 30 分钟
- README 公网部署文档 + docker-compose ≈ 30 分钟

总计：~6-7 小时，半天到一天的活。

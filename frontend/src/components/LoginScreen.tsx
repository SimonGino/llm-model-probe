import { useState } from "react";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { BrandMark, Icon } from "@/components/atoms";

export default function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
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
        setError("token 校验失败");
      } else {
        setError(`${err}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "var(--bg)",
        backgroundImage: `
          radial-gradient(circle at 20% 0%, color-mix(in oklab, var(--text) 4%, transparent) 0%, transparent 50%),
          radial-gradient(circle at 100% 100%, color-mix(in oklab, var(--text) 3%, transparent) 0%, transparent 60%)
        `,
      }}
    >
      <div style={{ width: "100%", maxWidth: 380 }} className="anim-fade-in">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 32,
          }}
        >
          <BrandMark />
          <div style={{ fontWeight: 600, letterSpacing: -0.2 }}>
            llm-model-probe
          </div>
        </div>

        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            margin: 0,
            marginBottom: 6,
            letterSpacing: -0.3,
          }}
        >
          登录
        </h1>
        <p
          style={{
            color: "var(--text-muted)",
            margin: 0,
            marginBottom: 24,
            fontSize: 13,
          }}
        >
          输入服务端{" "}
          <code
            className="mono"
            style={{
              background: "var(--bg-sunk)",
              padding: "1px 5px",
              borderRadius: 4,
            }}
          >
            LLM_MODEL_PROBE_TOKEN
          </code>{" "}
          继续。
        </p>

        <form onSubmit={submit}>
          <div style={{ position: "relative", marginBottom: 12 }}>
            <Icon
              name="key"
              size={14}
              style={{
                position: "absolute",
                left: 11,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--text-faint)",
              }}
            />
            <input
              type="password"
              autoFocus
              className="input mono"
              placeholder="paste token…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              style={{ paddingLeft: 32, height: 38, fontSize: 13 }}
              disabled={busy}
            />
          </div>

          {error && (
            <div
              className="badge badge-bad"
              style={{
                height: "auto",
                padding: "6px 9px",
                marginBottom: 12,
                width: "100%",
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", height: 38, fontSize: 13 }}
            disabled={busy || !token.trim()}
          >
            {busy ? "校验中…" : "进入面板"}
          </button>
        </form>

        <div
          style={{
            marginTop: 24,
            fontSize: 11,
            color: "var(--text-faint)",
            lineHeight: 1.6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="lock" size={11} /> 仅 token 鉴权 · 反代后建议启用 HTTPS
          </div>
          <div style={{ marginTop: 4 }}>
            CLI 直接读 SQLite，不受 token 影响。
          </div>
        </div>
      </div>
    </div>
  );
}

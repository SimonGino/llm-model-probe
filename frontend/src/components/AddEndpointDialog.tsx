import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointCreate, PasteSuggestion } from "@/lib/types";
import { parseLocally } from "@/lib/parsePaste";
import { Icon } from "@/components/atoms";

const empty: EndpointCreate = {
  name: "",
  sdk: "openai",
  base_url: "",
  api_key: "",
  models: [],
  note: "",
};

export default function AddEndpointDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<EndpointCreate>(empty);
  const [modelsText, setModelsText] = useState("");
  const [paste, setPaste] = useState("");
  const [suggestion, setSuggestion] = useState<PasteSuggestion | null>(null);
  const [parsing, setParsing] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(empty);
      setModelsText("");
      setPaste("");
      setSuggestion(null);
    }
  }, [open]);

  const create = useMutation({
    mutationFn: (payload: EndpointCreate) =>
      api.createEndpoint({ ...payload, no_probe: true }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      onClose();
      onCreated(data.id);
    },
  });

  function update<K extends keyof EndpointCreate>(k: K, v: EndpointCreate[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function reparse(value: string) {
    setPaste(value);
    if (!value.trim()) {
      setSuggestion(null);
      return;
    }
    const local = parseLocally(value);
    if (local.confidence >= 0.5) {
      const { confidence, parser, ...suggested } = local;
      setSuggestion({
        suggested,
        confidence,
        parser: parser as PasteSuggestion["parser"],
      });
      return;
    }
    setParsing(true);
    try {
      const remote = await api.parsePaste(value);
      setSuggestion(remote);
    } catch {
      setSuggestion({ suggested: {}, confidence: 0, parser: "none" });
    } finally {
      setParsing(false);
    }
  }

  function applyPaste() {
    if (!suggestion || suggestion.parser === "none") return;
    const s = suggestion.suggested;
    setForm((f) => ({
      ...f,
      name: s.name ?? f.name,
      sdk: s.sdk ?? f.sdk,
      base_url: s.base_url ?? f.base_url,
      api_key: s.api_key ?? f.api_key,
      note: s.note ?? f.note,
    }));
    if (s.models && s.models.length) setModelsText(s.models.join(", "));
    setPaste("");
    setSuggestion(null);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const models = modelsText
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    create.mutate({ ...form, models });
  }

  if (!open) return null;
  const filledFields = suggestion
    ? Object.values(suggestion.suggested).filter(Boolean).length
    : 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        background: "rgba(10, 10, 9, 0.4)",
        backdropFilter: "blur(3px)",
        display: "grid",
        placeItems: "start center",
        padding: "8vh 24px 24px",
        animation: "fadeIn .15s ease-out",
        overflowY: "auto",
      }}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        style={{
          width: "min(560px, 100%)",
          background: "var(--bg-elev)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          boxShadow: "var(--shadow-lg)",
          overflow: "hidden",
          animation: "popIn .2s cubic-bezier(.2,.8,.2,1)",
        }}
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <h2
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 600,
                letterSpacing: -0.2,
              }}
            >
              注册端点
            </h2>
            <div
              style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}
            >
              注册后可立即发现模型，再选择性地探测可用性。
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            onClick={onClose}
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ padding: 20, display: "grid", gap: 14 }}>
          <div>
            <Label>
              Smart paste{" "}
              <span style={{ color: "var(--text-faint)", fontWeight: 400 }}>
                · JSON / curl / .env
              </span>
            </Label>
            <textarea
              className="input mono"
              placeholder="粘贴 curl 命令 / JSON / dotenv 块 — 自动填表"
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
              onBlur={() => reparse(paste)}
              style={{
                height: 70,
                padding: 10,
                fontSize: 11,
                resize: "vertical",
                lineHeight: 1.5,
              }}
            />
            {suggestion && suggestion.parser !== "none" && (
              <div
                style={{
                  marginTop: 6,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                }}
              >
                <span className="badge badge-info">
                  {suggestion.parser}
                  {parsing && "…"}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  识别到 {filledFields} 个字段
                </span>
                <button type="button" className="btn btn-sm" onClick={applyPaste}>
                  应用
                </button>
              </div>
            )}
            {suggestion && suggestion.parser === "none" && (
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  color: "var(--text-muted)",
                }}
              >
                无法识别格式 — 请手动填写下方表单。
              </div>
            )}
          </div>

          <Divider />

          <Field label="Name" required>
            <input
              className="input"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="bob-glm"
            />
          </Field>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr",
              gap: 10,
            }}
          >
            <Field label="SDK">
              <select
                className="select"
                value={form.sdk}
                onChange={(e) =>
                  update("sdk", e.target.value as EndpointCreate["sdk"])
                }
              >
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
              </select>
            </Field>
            <Field label="Base URL" required>
              <input
                className="input mono"
                value={form.base_url}
                onChange={(e) => update("base_url", e.target.value)}
                placeholder="https://api.example.com/v1"
                style={{ fontSize: 12 }}
              />
            </Field>
          </div>

          <Field label="API key" required>
            <input
              className="input mono"
              type="password"
              value={form.api_key}
              onChange={(e) => update("api_key", e.target.value)}
              placeholder="sk-…"
              style={{ fontSize: 12 }}
            />
          </Field>

          <Field label="Models" hint="留空触发 discover；多个用逗号分隔">
            <input
              className="input mono"
              value={modelsText}
              onChange={(e) => setModelsText(e.target.value)}
              placeholder="gpt-4o, gpt-4o-mini"
              style={{ fontSize: 12 }}
            />
          </Field>

          <Field label="Note">
            <input
              className="input"
              value={form.note ?? ""}
              onChange={(e) => update("note", e.target.value)}
              placeholder="from Bob 2026-05-04"
            />
          </Field>

          {create.error && (
            <div className="badge badge-bad" style={{ width: "100%" }}>
              {String(create.error)}
            </div>
          )}
        </div>

        <div
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--border)",
            background: "var(--bg-sunk)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--text-faint)",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Icon name="lock" size={11} /> Key 写入本地 SQLite，权限 0600
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn" onClick={onClose}>
              取消 <span className="kbd">Esc</span>
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                !form.name ||
                !form.base_url ||
                !form.api_key ||
                create.isPending
              }
            >
              {create.isPending ? "添加中…" : "Add endpoint"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <Label>
        {label}
        {required && (
          <span style={{ color: "var(--bad)", marginLeft: 3 }}>*</span>
        )}
        {hint && (
          <span
            style={{
              color: "var(--text-faint)",
              fontWeight: 400,
              marginLeft: 6,
            }}
          >
            {hint}
          </span>
        )}
      </Label>
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 500,
        color: "var(--text-muted)",
        marginBottom: 5,
        textTransform: "uppercase",
        letterSpacing: 0.4,
      }}
    >
      {children}
    </div>
  );
}

function Divider() {
  return <div style={{ height: 1, background: "var(--border)" }} />;
}

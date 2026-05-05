import { useState } from "react";
import { api } from "@/lib/api";
import { Icon } from "@/components/atoms";

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
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <code
        className="mono"
        style={{
          background: "var(--bg-sunk)",
          padding: "2px 6px",
          borderRadius: 4,
          fontSize: 11,
          letterSpacing: 0.5,
          wordBreak: "break-all",
        }}
      >
        {revealed ?? masked}
      </code>
      <button
        type="button"
        className="btn btn-ghost btn-icon btn-sm"
        title={revealed ? "Hide" : "Reveal"}
        onClick={toggleReveal}
        disabled={busy}
      >
        <Icon
          name={revealed ? "eye-off" : "eye"}
          size={12}
          style={{ color: "var(--text-muted)" }}
        />
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-icon btn-sm"
        title="Copy full api_key"
        onClick={copy}
        disabled={busy}
      >
        <Icon
          name={copied ? "check" : "copy"}
          size={12}
          style={{ color: copied ? "var(--ok)" : "var(--text-muted)" }}
        />
      </button>
    </span>
  );
}

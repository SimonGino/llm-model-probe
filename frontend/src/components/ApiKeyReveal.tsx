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

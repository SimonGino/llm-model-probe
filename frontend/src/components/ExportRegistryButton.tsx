import { useState } from "react";
import { downloadRegistry } from "@/lib/api";
import { Icon } from "@/components/atoms";

export default function ExportRegistryButton() {
  const [open, setOpen] = useState(false);
  const [includeKeys, setIncludeKeys] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onDownload() {
    if (busy) return;
    setBusy(true);
    try {
      const { blob, filename } = await downloadRegistry(includeKeys);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch (e) {
      alert(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <button
        className="btn"
        onClick={() => setOpen((v) => !v)}
        title="Export registry to JSON"
      >
        <Icon name="download" size={12} /> Export
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 6px)",
            zIndex: 50,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 12,
            minWidth: 260,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
          }}
        >
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={includeKeys}
              onChange={(e) => setIncludeKeys(e.target.checked)}
            />
            Include API keys
          </label>
          {includeKeys && (
            <p
              style={{
                margin: "6px 0 0",
                fontSize: 11,
                color: "var(--bad)",
              }}
            >
              Plaintext keys will be written to the file.
            </p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn"
              onClick={() => setOpen(false)}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={onDownload}
              disabled={busy}
            >
              {busy ? "Downloading…" : "Download"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

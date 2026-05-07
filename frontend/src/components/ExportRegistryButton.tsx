import { useEffect, useRef, useState } from "react";
import { downloadRegistry } from "@/lib/api";
import { Icon } from "@/components/atoms";

export default function ExportRegistryButton() {
  const [open, setOpen] = useState(false);
  const [includeKeys, setIncludeKeys] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Dismiss on Escape or outside-click while popover is open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onMouseDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onMouseDown);
    };
  }, [open]);

  // Clear error when popover closes (so re-opening starts clean).
  useEffect(() => {
    if (!open) setError(null);
  }, [open]);

  async function onDownload() {
    if (busy) return;
    setBusy(true);
    setError(null);
    let url: string | null = null;
    try {
      const { blob, filename } = await downloadRegistry(includeKeys);
      url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      try {
        a.click();
      } finally {
        a.remove();
      }
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (url) URL.revokeObjectURL(url);
      setBusy(false);
    }
  }

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
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
          {error && (
            <p
              style={{
                margin: "6px 0 0",
                fontSize: 11,
                color: "var(--bad)",
              }}
            >
              Export failed: {error}
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

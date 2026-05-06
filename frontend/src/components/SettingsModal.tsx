import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { endpointHealth } from "@/components/atoms";

export default function SettingsModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["parser-settings"],
    queryFn: () => api.getParserSettings(),
    enabled: open,
  });
  const endpoints = useQuery({
    queryKey: ["endpoints"],
    queryFn: () => api.listEndpoints(),
    enabled: open,
  });

  const [endpointId, setEndpointId] = useState<string>("");
  const [modelId, setModelId] = useState<string>("");
  const [endpointModels, setEndpointModels] = useState<string[]>([]);

  useEffect(() => {
    if (settings.data) {
      setEndpointId(settings.data.endpoint_id ?? "");
      setModelId(settings.data.model_id ?? "");
    }
  }, [settings.data]);

  // When the chosen endpoint changes, fetch its detail to populate model list.
  const detail = useQuery({
    queryKey: ["endpoint", endpointId],
    queryFn: () => api.getEndpoint(endpointId),
    enabled: !!endpointId && open,
  });

  useEffect(() => {
    if (detail.data) {
      const availableModels = detail.data.results
        .filter((r) => r.status === "available")
        .map((r) => r.model_id);
      setEndpointModels(
        availableModels.length > 0 ? availableModels : detail.data.models,
      );
    }
  }, [detail.data]);

  const usableEndpoints = useMemo(
    () =>
      (endpoints.data ?? []).filter(
        (e: EndpointSummary) => endpointHealth(e).tone !== "bad",
      ),
    [endpoints.data],
  );

  const save = useMutation({
    mutationFn: () =>
      api.setParserSettings({
        endpoint_id: endpointId || null,
        model_id: modelId || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parser-settings"] });
      onClose();
    },
  });

  if (!open) return null;
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.45)",
        display: "grid",
        placeItems: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          color: "var(--text)",
          padding: 24,
          borderRadius: 10,
          minWidth: 420,
          maxWidth: 540,
          border: "1px solid var(--border)",
        }}
      >
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Settings</h3>
        <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
          Default AI Parser
        </h4>

        <label style={{ display: "block", fontSize: 11, marginBottom: 4 }}>
          Endpoint
        </label>
        <select
          value={endpointId}
          onChange={(e) => {
            setEndpointId(e.target.value);
            setModelId("");
          }}
          style={{ width: "100%", marginBottom: 12, height: 32 }}
        >
          <option value="">— select —</option>
          {usableEndpoints.map((e: EndpointSummary) => (
            <option key={e.id} value={e.id}>
              {e.name} ({e.sdk})
            </option>
          ))}
        </select>

        <label style={{ display: "block", fontSize: 11, marginBottom: 4 }}>
          Model
        </label>
        <select
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          disabled={!endpointId}
          style={{ width: "100%", marginBottom: 12, height: 32 }}
        >
          <option value="">— select —</option>
          {endpointModels.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        <p style={{ fontSize: 11, color: "var(--text-muted)" }}>
          AI Parse 会把粘贴文本发给这里选中的 endpoint；该 endpoint 的服务方
          会看到内容（可能含其他 endpoint 的 api_key）。
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 14,
          }}
        >
          <button className="btn btn-sm btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-sm btn-primary"
            disabled={!endpointId || !modelId || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

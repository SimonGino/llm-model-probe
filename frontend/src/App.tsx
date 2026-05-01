import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";

export default function App() {
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const orch = useProbeOrchestrator();
  const totalPending = orch.totalPending();

  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [autoTest, setAutoTest] = useState(false);

  async function retestEverything() {
    if (!list.data) return;
    for (const ep of list.data) {
      if (ep.total_models === 0) continue;
      const detail = await api.getEndpoint(ep.id);
      // Don't await — run in background, sharing the global concurrency=5 limiter.
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

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";

export default function App() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const retestAll = useMutation({
    mutationFn: api.retestAll,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  void selected;

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">llm-model-probe</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={retestAll.isPending}
            onClick={() => retestAll.mutate()}
          >
            {retestAll.isPending ? "Retesting…" : "↻ Retest all"}
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
        <EndpointTable endpoints={list.data} onSelect={setSelected} />
      )}

      {/* AddEndpointDialog wired in next task */}
      {showAdd && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setShowAdd(false)}
        >
          <div
            className="bg-card p-4 rounded-md"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="mb-2">Add dialog placeholder — implemented in Task 10.</p>
            <Button onClick={() => setShowAdd(false)}>Close</Button>
          </div>
        </div>
      )}
    </div>
  );
}

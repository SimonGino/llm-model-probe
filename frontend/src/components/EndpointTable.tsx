import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { relative } from "@/lib/format";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export default function EndpointTable({
  endpoints,
  search,
  setSearch,
  tagFilter,
  setTagFilter,
  onSelect,
  onRetest,
}: {
  endpoints: EndpointSummary[];
  search: string;
  setSearch: (s: string) => void;
  tagFilter: Set<string>;
  setTagFilter: (f: Set<string>) => void;
  onSelect: (idOrName: string) => void;
  onRetest: (idOrName: string) => void;
}) {
  const qc = useQueryClient();
  const orch = useProbeOrchestrator();

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteEndpoint(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });

  const allTags = useMemo(() => {
    const s = new Set<string>();
    for (const ep of endpoints) for (const t of ep.tags) s.add(t);
    return [...s].sort();
  }, [endpoints]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return endpoints.filter((ep) => {
      if (tagFilter.size > 0) {
        const has = ep.tags.some((t) => tagFilter.has(t));
        if (!has) return false;
      }
      if (q) {
        const haystack = [
          ep.name.toLowerCase(),
          ep.note.toLowerCase(),
          ...ep.tags.map((t) => t.toLowerCase()),
        ];
        if (!haystack.some((h) => h.includes(q))) return false;
      }
      return true;
    });
  }, [endpoints, search, tagFilter]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <Input
          placeholder="Search name / note / tag..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        {allTags.length > 0 && (
          <TagFilterDropdown
            allTags={allTags}
            selected={tagFilter}
            onChange={setTagFilter}
          />
        )}
        {(search || tagFilter.size > 0) && (
          <span className="text-xs text-muted-foreground">
            {filtered.length} / {endpoints.length}
          </span>
        )}
      </div>

      {filtered.length === 0 ? (
        <div className="text-muted-foreground p-8 text-center border rounded-md">
          {endpoints.length === 0
            ? "No endpoints yet. Click + Add endpoint."
            : "No endpoints match the current filter."}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>SDK</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Tested</TableHead>
              <TableHead>Tags</TableHead>
              <TableHead>Note</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((ep) => {
              const pendingForRow = orch.pendingForEndpoint(ep.id);
              const untested = ep.total_models - ep.available - ep.failed;
              return (
                <TableRow
                  key={ep.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => onSelect(ep.id)}
                >
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {ep.id}
                  </TableCell>
                  <TableCell className="font-medium">{ep.name}</TableCell>
                  <TableCell>{ep.sdk}</TableCell>
                  <TableCell>{ep.mode}</TableCell>
                  <TableCell>
                    {ep.list_error ? (
                      <Badge variant="destructive">list-error</Badge>
                    ) : ep.total_models === 0 ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <span className="text-xs">
                        <span className="text-green-600">{ep.available}</span>
                        {" / "}
                        <span className="text-destructive">{ep.failed}</span>
                        {untested > 0 && (
                          <>
                            {" / "}
                            <span className="text-muted-foreground">
                              {untested} untested
                            </span>
                          </>
                        )}
                        {pendingForRow > 0 && (
                          <span className="text-blue-600 ml-1">
                            ({pendingForRow} testing)
                          </span>
                        )}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {relative(ep.last_tested_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {ep.tags.slice(0, 3).map((t) => (
                        <Badge key={t} variant="secondary" className="text-xs">
                          {t}
                        </Badge>
                      ))}
                      {ep.tags.length > 3 && (
                        <Badge variant="outline" className="text-xs">
                          +{ep.tags.length - 3}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-[160px] truncate">
                    {ep.note}
                  </TableCell>
                  <TableCell
                    className="text-right space-x-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={ep.total_models === 0 || pendingForRow > 0}
                      title="Open + test all models"
                      onClick={() => onRetest(ep.id)}
                    >
                      ↻
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        if (confirm(`Delete '${ep.name}'?`)) remove.mutate(ep.id);
                      }}
                    >
                      ✕
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function TagFilterDropdown({
  allTags,
  selected,
  onChange,
}: {
  allTags: string[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
}) {
  function toggle(tag: string) {
    const n = new Set(selected);
    if (n.has(tag)) n.delete(tag);
    else n.add(tag);
    onChange(n);
  }
  return (
    <details className="relative">
      <summary className="list-none cursor-pointer">
        <Badge variant={selected.size > 0 ? "default" : "outline"}>
          Tags {selected.size > 0 && `(${selected.size})`} ▾
        </Badge>
      </summary>
      <div className="absolute z-10 mt-1 bg-popover border rounded-md shadow-md p-2 min-w-[180px] max-h-60 overflow-y-auto">
        {allTags.map((t) => (
          <label
            key={t}
            className="flex items-center gap-2 px-1 py-1 hover:bg-muted/50 cursor-pointer text-sm rounded"
          >
            <input
              type="checkbox"
              checked={selected.has(t)}
              onChange={() => toggle(t)}
            />
            <span>{t}</span>
          </label>
        ))}
        {selected.size > 0 && (
          <button
            className="w-full text-xs text-muted-foreground mt-2 px-1 py-1 hover:bg-muted/50 rounded text-left"
            onClick={() => onChange(new Set())}
          >
            清空
          </button>
        )}
      </div>
    </details>
  );
}

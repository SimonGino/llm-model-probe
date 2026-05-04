import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Check, Copy } from "lucide-react";
import { relative } from "@/lib/format";
import TagEditor from "./TagEditor";
import ApiKeyReveal from "./ApiKeyReveal";
import type { ModelResultPublic } from "@/lib/types";

export default function EndpointDetailDrawer({
  idOrName,
  autoTest,
  onAutoTestConsumed,
  onClose,
}: {
  idOrName: string | null;
  autoTest: boolean;
  onAutoTestConsumed: () => void;
  onClose: () => void;
}) {
  const open = idOrName !== null;
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName!),
    enabled: open,
  });
  const orch = useProbeOrchestrator();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [modelSearch, setModelSearch] = useState("");

  // Reset checkbox state when the drawer's endpoint changes; default-check
  // models that are NOT in excluded_by_filter.
  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
  }, [detail.data?.id]);

  // Auto-trigger Test all if requested by parent (row ↻ click)
  useEffect(() => {
    if (autoTest && detail.data && detail.data.models.length > 0) {
      orch.run(detail.data.id, detail.data.models);
      onAutoTestConsumed();
    }
  }, [autoTest, detail.data?.id]);

  const resultByModel = useMemo(() => {
    const m = new Map<string, ModelResultPublic>();
    if (detail.data) for (const r of detail.data.results) m.set(r.model_id, r);
    return m;
  }, [detail.data]);

  function toggle(model: string) {
    setChecked((prev) => {
      const n = new Set(prev);
      if (n.has(model)) n.delete(model);
      else n.add(model);
      return n;
    });
  }

  const d = detail.data;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{d?.name ?? "…"}</SheetTitle>
        </SheetHeader>

        {detail.isLoading && (
          <div className="py-4 text-muted-foreground">Loading…</div>
        )}

        {d && (
          <div className="space-y-4 py-4 text-sm">
            <div className="space-y-1">
              <Row label="ID">{d.id}</Row>
              <Row label="SDK">{d.sdk}</Row>
              <Row label="URL">
                <code>{d.base_url}</code>
              </Row>
              <Row label="API key">
                <ApiKeyReveal endpointId={d.id} masked={d.api_key_masked} />
              </Row>
              <Row label="Mode">{d.mode}</Row>
              <Row label="Tags">
                <TagEditor endpointId={d.id} tags={d.tags} />
              </Row>
              {d.note && <Row label="Note">{d.note}</Row>}
              <Row label="Last tested">{relative(d.last_tested_at)}</Row>
              {d.list_error && (
                <Row label="List error">
                  <Badge variant="destructive">{d.list_error}</Badge>
                </Row>
              )}
            </div>

            {d.models.length === 0 ? (
              <div className="text-muted-foreground italic">
                {d.list_error
                  ? "No models discovered. Try removing this endpoint and re-adding."
                  : "No models. Specified mode with empty list."}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">
                      Models ({d.models.length})
                    </h3>
                    <Input
                      placeholder="Search models..."
                      value={modelSearch}
                      onChange={(e) => setModelSearch(e.target.value)}
                      className="h-8 text-xs w-44"
                    />
                  </div>
                  <div className="flex gap-2">
                    {(() => {
                      const q = modelSearch.trim().toLowerCase();
                      const filteredAll = q
                        ? d.models.filter((m) => m.toLowerCase().includes(q))
                        : d.models;
                      const filteredChecked = q
                        ? [...checked].filter((m) =>
                            m.toLowerCase().includes(q),
                          )
                        : [...checked];
                      const filtered = !!q;
                      return (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={filteredChecked.length === 0}
                            onClick={() => orch.run(d.id, filteredChecked)}
                          >
                            Test selected ({filteredChecked.length}
                            {filtered ? ", filtered" : ""})
                          </Button>
                          <Button
                            size="sm"
                            disabled={filteredAll.length === 0}
                            onClick={() => orch.run(d.id, filteredAll)}
                          >
                            Test all
                            {filtered ? ` (filtered: ${filteredAll.length})` : ""}
                          </Button>
                        </>
                      );
                    })()}
                  </div>
                </div>

                {(() => {
                  const q = modelSearch.trim().toLowerCase();
                  const visible = q
                    ? d.models.filter((m) => m.toLowerCase().includes(q))
                    : d.models;

                  const available: string[] = [];
                  const failed: string[] = [];
                  const untested: string[] = [];
                  for (const m of visible) {
                    const r = resultByModel.get(m);
                    const te = orch.errorFor(d.id, m);
                    if (r?.status === "available") available.push(m);
                    else if (r || te) failed.push(m);
                    else untested.push(m);
                  }

                  available.sort((a, b) => {
                    const la =
                      resultByModel.get(a)?.latency_ms ??
                      Number.MAX_SAFE_INTEGER;
                    const lb =
                      resultByModel.get(b)?.latency_ms ??
                      Number.MAX_SAFE_INTEGER;
                    if (la !== lb) return la - lb;
                    return a.localeCompare(b);
                  });
                  failed.sort((a, b) => {
                    const ea =
                      resultByModel.get(a)?.error_type ??
                      orch.errorFor(d.id, a) ??
                      "";
                    const eb =
                      resultByModel.get(b)?.error_type ??
                      orch.errorFor(d.id, b) ??
                      "";
                    if (ea !== eb) return ea.localeCompare(eb);
                    return a.localeCompare(b);
                  });
                  untested.sort((a, b) => a.localeCompare(b));

                  const renderRow = (m: string) => (
                    <ModelRow
                      key={m}
                      model={m}
                      result={resultByModel.get(m) ?? null}
                      pending={orch.isPending(d.id, m)}
                      transientError={orch.errorFor(d.id, m)}
                      filterSkip={d.excluded_by_filter.includes(m)}
                      checked={checked.has(m)}
                      onToggle={() => toggle(m)}
                    />
                  );
                  return (
                    <div className="space-y-3">
                      {available.length > 0 && (
                        <Section
                          title="Available"
                          count={available.length}
                          tone="green"
                        >
                          {available.map(renderRow)}
                        </Section>
                      )}
                      {failed.length > 0 && (
                        <Section
                          title="Failed"
                          count={failed.length}
                          tone="red"
                        >
                          {failed.map(renderRow)}
                        </Section>
                      )}
                      {untested.length > 0 && (
                        <Section
                          title="Untested"
                          count={untested.length}
                          tone="muted"
                        >
                          {untested.map(renderRow)}
                        </Section>
                      )}
                      {visible.length === 0 && (
                        <div className="text-xs text-muted-foreground italic">
                          没有匹配 "{modelSearch}" 的模型
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({
  title,
  count,
  tone,
  children,
}: {
  title: string;
  count: number;
  tone: "green" | "red" | "muted";
  children: React.ReactNode;
}) {
  const titleColor =
    tone === "green"
      ? "text-green-700"
      : tone === "red"
      ? "text-destructive"
      : "text-muted-foreground";
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wide mb-1 ${titleColor}`}>
        {title} ({count})
      </h4>
      <div className="border rounded-md divide-y">{children}</div>
    </div>
  );
}

function ModelRow({
  model,
  result,
  pending,
  transientError,
  filterSkip,
  checked,
  onToggle,
}: {
  model: string;
  result: ModelResultPublic | null;
  pending: boolean;
  transientError: string | null;
  filterSkip: boolean;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex items-center gap-2 px-3 py-2 hover:bg-muted/30 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-4 w-4 flex-shrink-0"
      />
      <div className="flex items-center gap-1 flex-1 min-w-0">
        <span className="font-mono text-xs truncate">{model}</span>
        <CopyButton text={model} />
      </div>
      {filterSkip && !result && !pending && !transientError && (
        <Badge variant="secondary" className="text-xs flex-shrink-0">
          filter-skip
        </Badge>
      )}
      <ModelStatus
        result={result}
        pending={pending}
        transientError={transientError}
      />
    </label>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Copy model id"
      aria-label={`Copy ${text}`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          })
          .catch(() => {
            /* ignore */
          });
      }}
      className="text-muted-foreground hover:text-foreground p-1 rounded flex-shrink-0"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-600" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

function ModelStatus({
  result,
  pending,
  transientError,
}: {
  result: ModelResultPublic | null;
  pending: boolean;
  transientError: string | null;
}) {
  if (pending)
    return <span className="text-muted-foreground text-xs">… testing</span>;
  if (result) {
    if (result.status === "available")
      return (
        <span className="text-green-600 text-xs">
          ✓ {result.latency_ms} ms
        </span>
      );
    return (
      <span
        className="text-destructive text-xs truncate max-w-[200px]"
        title={result.error_message ?? undefined}
      >
        ✗ {result.error_type}
      </span>
    );
  }
  if (transientError)
    return (
      <span
        className="text-destructive text-xs truncate max-w-[200px]"
        title={transientError}
      >
        ✗ request: {transientError}
      </span>
    );
  return <span className="text-muted-foreground text-xs">untested</span>;
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}

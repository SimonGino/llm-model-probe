import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { relative } from "@/lib/format";

export default function EndpointDetailDrawer({
  idOrName,
  onClose,
}: {
  idOrName: string | null;
  onClose: () => void;
}) {
  const open = idOrName !== null;
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName!),
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{detail.data?.name ?? "…"}</SheetTitle>
        </SheetHeader>

        {detail.isLoading && (
          <div className="py-4 text-muted-foreground">Loading…</div>
        )}
        {detail.data &&
          (() => {
            const d = detail.data;
            const ok = d.results.filter((r) => r.status === "available");
            const fail = d.results.filter((r) => r.status === "failed");
            return (
              <div className="space-y-4 py-4 text-sm">
                <div className="space-y-1">
                  <Row label="ID">{d.id}</Row>
                  <Row label="SDK">{d.sdk}</Row>
                  <Row label="URL">
                    <code>{d.base_url}</code>
                  </Row>
                  <Row label="API key">
                    <code>{d.api_key_masked}</code>
                  </Row>
                  <Row label="Mode">{d.mode}</Row>
                  {d.note && <Row label="Note">{d.note}</Row>}
                  <Row label="Last tested">{relative(d.last_tested_at)}</Row>
                  {d.list_error && (
                    <Row label="List error">
                      <Badge variant="destructive">{d.list_error}</Badge>
                    </Row>
                  )}
                </div>

                {ok.length > 0 && (
                  <div>
                    <h3 className="font-semibold mb-2 text-green-700">
                      Available ({ok.length})
                    </h3>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-muted-foreground">
                          <th className="py-1">Model</th>
                          <th className="py-1">Latency</th>
                          <th className="py-1">Preview</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ok.map((r) => (
                          <tr key={r.model_id} className="border-t">
                            <td className="py-1 font-mono">{r.model_id}</td>
                            <td className="py-1">{r.latency_ms} ms</td>
                            <td className="py-1 text-muted-foreground">
                              {r.response_preview}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {fail.length > 0 && (
                  <div>
                    <h3 className="font-semibold mb-2 text-destructive">
                      Failed ({fail.length})
                    </h3>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-muted-foreground">
                          <th className="py-1">Model</th>
                          <th className="py-1">Error</th>
                          <th className="py-1">Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fail.map((r) => (
                          <tr key={r.model_id} className="border-t">
                            <td className="py-1 font-mono">{r.model_id}</td>
                            <td className="py-1">{r.error_type}</td>
                            <td className="py-1 text-muted-foreground truncate max-w-xs">
                              {r.error_message}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })()}
      </SheetContent>
    </Sheet>
  );
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

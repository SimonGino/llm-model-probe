import { useCallback, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

const CONCURRENCY = 5;

function k(ep: string, model: string): string {
  return `${ep}::${model}`;
}

type Listener = () => void;

interface Inflight {
  status: "pending";
}

class OrchestratorStore {
  private map = new Map<string, Inflight>();
  private errors = new Map<string, string>();
  private inFlight = 0;
  private queue: Array<() => void> = [];
  private listeners = new Set<Listener>();
  private rev = 0;

  subscribe = (cb: Listener): (() => void) => {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  };

  private emit() {
    this.rev++;
    for (const cb of this.listeners) cb();
  }

  getSnapshot = (): number => this.rev;

  isPending(ep: string, model: string): boolean {
    return this.map.get(k(ep, model))?.status === "pending";
  }

  pendingCountForEndpoint(ep: string): number {
    let n = 0;
    const prefix = `${ep}::`;
    for (const [key, v] of this.map) {
      if (v.status === "pending" && key.startsWith(prefix)) n++;
    }
    return n;
  }

  totalPending(): number {
    let n = 0;
    for (const v of this.map.values()) if (v.status === "pending") n++;
    return n;
  }

  errorFor(ep: string, model: string): string | null {
    return this.errors.get(k(ep, model)) ?? null;
  }

  run(
    ep: string,
    models: string[],
    onResult: (m: string) => void,
  ): Promise<void> {
    return new Promise((resolve) => {
      let remaining = models.length;
      if (remaining === 0) {
        resolve();
        return;
      }
      const tick = () => {
        while (this.inFlight < CONCURRENCY && this.queue.length) {
          const job = this.queue.shift()!;
          this.inFlight++;
          job();
        }
      };
      for (const m of models) {
        this.map.set(k(ep, m), { status: "pending" });
        this.errors.delete(k(ep, m));
        this.queue.push(() => {
          api
            .probeModel(ep, m)
            .then(() => {
              this.errors.delete(k(ep, m));
            })
            .catch((err) => {
              const msg = String(err?.message ?? err).slice(0, 120);
              this.errors.set(k(ep, m), msg);
              // eslint-disable-next-line no-console
              console.error(`[probe] ${ep}/${m}: ${msg}`);
            })
            .finally(() => {
              this.map.delete(k(ep, m));
              this.inFlight--;
              this.emit();
              onResult(m);
              remaining--;
              if (remaining === 0) resolve();
              else tick();
            });
        });
      }
      this.emit();
      tick();
    });
  }
}

let singleton: OrchestratorStore | null = null;
function store(): OrchestratorStore {
  if (!singleton) singleton = new OrchestratorStore();
  return singleton;
}

export function useProbeOrchestrator() {
  const s = store();
  useSyncExternalStore(s.subscribe, s.getSnapshot, s.getSnapshot);
  const qc = useQueryClient();
  const startRef = useRef(s);

  const run = useCallback(
    async (ep: string, models: string[]) => {
      await startRef.current.run(ep, models, () => {
        qc.invalidateQueries({ queryKey: ["endpoint", ep] });
        qc.invalidateQueries({ queryKey: ["endpoints"] });
      });
    },
    [qc],
  );

  return {
    run,
    isPending: (ep: string, model: string) => s.isPending(ep, model),
    errorFor: (ep: string, model: string) => s.errorFor(ep, model),
    pendingForEndpoint: (ep: string) => s.pendingCountForEndpoint(ep),
    totalPending: () => s.totalPending(),
  };
}

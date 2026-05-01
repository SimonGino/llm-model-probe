import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  PasteSuggestion,
} from "./types";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(`${r.status} ${detail}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  listEndpoints: () => req<EndpointSummary[]>("GET", "/api/endpoints"),
  getEndpoint: (idOrName: string) =>
    req<EndpointDetail>("GET", `/api/endpoints/${encodeURIComponent(idOrName)}`),
  createEndpoint: (payload: EndpointCreate) =>
    req<EndpointDetail>("POST", "/api/endpoints", payload),
  deleteEndpoint: (id: string) =>
    req<void>("DELETE", `/api/endpoints/${encodeURIComponent(id)}`),
  retestEndpoint: (id: string) =>
    req<EndpointDetail>("POST", `/api/endpoints/${encodeURIComponent(id)}/retest`),
  retestAll: () => req<{ retested: number }>("POST", "/api/retest-all"),
  parsePaste: (blob: string) =>
    req<PasteSuggestion>("POST", "/api/parse-paste", { blob }),
};

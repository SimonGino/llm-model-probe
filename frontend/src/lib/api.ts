import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  EndpointUpdate,
  PasteSuggestion,
  ModelResultPublic,
  ParserSettings,
  AiParseResult,
} from "./types";
import { auth, UnauthorizedError } from "./auth";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = auth.get();
  const headers: Record<string, string> = body
    ? { "Content-Type": "application/json" }
    : {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) {
    auth.clear();
    throw new UnauthorizedError();
  }
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
  authCheck: () => req<{ ok: boolean }>("GET", "/api/auth/check"),
  listEndpoints: () => req<EndpointSummary[]>("GET", "/api/endpoints"),
  getEndpoint: (idOrName: string) =>
    req<EndpointDetail>("GET", `/api/endpoints/${encodeURIComponent(idOrName)}`),
  createEndpoint: (payload: EndpointCreate) =>
    req<EndpointDetail>("POST", "/api/endpoints", payload),
  deleteEndpoint: (id: string) =>
    req<void>("DELETE", `/api/endpoints/${encodeURIComponent(id)}`),
  retestEndpoint: (id: string) =>
    req<EndpointDetail>("POST", `/api/endpoints/${encodeURIComponent(id)}/retest`),
  rediscoverEndpoint: (id: string) =>
    req<EndpointDetail>(
      "POST",
      `/api/endpoints/${encodeURIComponent(id)}/rediscover`,
    ),
  retestAll: () => req<{ retested: number }>("POST", "/api/retest-all"),
  parsePaste: (blob: string) =>
    req<PasteSuggestion>("POST", "/api/parse-paste", { blob }),
  probeModel: (id: string, model: string) =>
    req<ModelResultPublic>(
      "POST",
      `/api/endpoints/${encodeURIComponent(id)}/probe-model`,
      { model },
    ),
  patchEndpoint: (idOrName: string, body: EndpointUpdate) =>
    req<EndpointDetail>(
      "PATCH",
      `/api/endpoints/${encodeURIComponent(idOrName)}`,
      body,
    ),
  setTags: (idOrName: string, tags: string[]) =>
    req<EndpointSummary>(
      "PUT",
      `/api/endpoints/${encodeURIComponent(idOrName)}/tags`,
      { tags },
    ),
  getApiKey: (idOrName: string) =>
    req<{ api_key: string }>(
      "GET",
      `/api/endpoints/${encodeURIComponent(idOrName)}/api-key`,
    ),
  getParserSettings: () =>
    req<ParserSettings>("GET", "/api/settings/parser"),
  setParserSettings: (s: ParserSettings) =>
    req<ParserSettings>("PUT", "/api/settings/parser", s),
  aiParse: (blob: string) =>
    req<AiParseResult>("POST", "/api/ai-parse", { blob }),
};

export async function downloadRegistry(
  includeKeys: boolean,
): Promise<{ blob: Blob; filename: string }> {
  const token = auth.get();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const url = `/api/registry/dump?include_keys=${includeKeys ? "true" : "false"}`;
  const r = await fetch(url, { headers });
  if (r.status === 401) {
    auth.clear();
    throw new UnauthorizedError();
  }
  if (!r.ok) {
    throw new Error(`HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") ?? "";
  const m = cd.match(/filename="([^"]+)"/);
  const filename =
    m?.[1] ??
    `llm-model-probe-registry-${new Date().toISOString().slice(0, 10)}.json`;
  return { blob, filename };
}

import type { EndpointCreate } from "./types";

type Suggestion = Partial<EndpointCreate> & { confidence: number; parser: string };

const URL_RE = /https?:\/\/[^\s'"]+/i;
const BEARER_RE = /Authorization:\s*Bearer\s+(\S+)/i;
const KV_RE = /^([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$/;

function guessSdk(url: string): "openai" | "anthropic" {
  return url.toLowerCase().includes("anthropic") ? "anthropic" : "openai";
}

function tryJson(blob: string): Suggestion | null {
  try {
    const obj = JSON.parse(blob);
    if (typeof obj !== "object" || obj === null) return null;
    const out: Suggestion = { confidence: 0, parser: "json" };
    const bu = obj.base_url ?? obj.baseUrl ?? obj.BASE_URL;
    if (bu) out.base_url = String(bu).replace(/\/+$/, "");
    const ak = obj.api_key ?? obj.apiKey ?? obj.API_KEY;
    if (ak) out.api_key = String(ak);
    if (Array.isArray(obj.models)) out.models = obj.models.map(String);
    if (obj.name) out.name = String(obj.name);
    if (obj.sdk === "openai" || obj.sdk === "anthropic") out.sdk = obj.sdk;
    else if (out.base_url) out.sdk = guessSdk(out.base_url);
    if (!out.base_url && !out.api_key) return null;
    out.confidence = out.base_url && out.api_key ? 1 : 0.6;
    return out;
  } catch {
    return null;
  }
}

function tryCurl(blob: string): Suggestion | null {
  if (!blob.toLowerCase().includes("curl")) return null;
  const out: Suggestion = { confidence: 0, parser: "curl" };
  const b = blob.match(BEARER_RE);
  if (b) out.api_key = b[1].replace(/^['"]|['"]$/g, "");
  const u = blob.match(URL_RE);
  if (u) {
    let url = u[0].replace(/[,;]+$/, "");
    if (url.includes("/v1")) {
      url = url.split("/v1")[0] + "/v1";
    } else {
      try {
        const parsed = new URL(url);
        url = `${parsed.protocol}//${parsed.host}`;
      } catch {
        // ignore
      }
    }
    out.base_url = url;
    out.sdk = guessSdk(url);
  }
  if (!out.base_url && !out.api_key) return null;
  out.confidence = out.base_url && out.api_key ? 1 : 0.6;
  return out;
}

function tryDotenv(blob: string): Suggestion | null {
  const out: Suggestion = { confidence: 0, parser: "dotenv" };
  for (const raw of blob.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(KV_RE);
    if (!m) continue;
    const key = m[1].toUpperCase();
    const val = m[2].trim().replace(/^['"]|['"]$/g, "");
    if (key.includes("BASE_URL") || key === "URL" || key.endsWith("_URL"))
      out.base_url = val.replace(/\/+$/, "");
    else if (key.includes("API_KEY") || key === "KEY" || key.endsWith("_KEY"))
      out.api_key = val;
  }
  if (!out.base_url && !out.api_key) return null;
  if (out.base_url) out.sdk = guessSdk(out.base_url);
  out.confidence = out.base_url && out.api_key ? 1 : 0.6;
  return out;
}

export function parseLocally(blob: string): Suggestion {
  const trimmed = blob.trim();
  return (
    tryJson(trimmed) ??
    tryCurl(trimmed) ??
    tryDotenv(trimmed) ?? { confidence: 0, parser: "none" }
  );
}

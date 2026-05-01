export type Sdk = "openai" | "anthropic";
export type Mode = "discover" | "specified";
export type Status = "available" | "failed";

export interface EndpointSummary {
  id: string;
  name: string;
  sdk: Sdk;
  base_url: string;
  mode: Mode;
  note: string;
  list_error: string | null;
  available: number;
  failed: number;
  total_models: number;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModelResultPublic {
  model_id: string;
  source: "discovered" | "specified";
  status: Status;
  latency_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  response_preview: string | null;
  last_tested_at: string | null;
}

export interface EndpointDetail extends EndpointSummary {
  api_key_masked: string;
  models: string[];
  excluded_by_filter: string[];
  results: ModelResultPublic[];
}

export interface EndpointCreate {
  name: string;
  sdk: Sdk;
  base_url: string;
  api_key: string;
  models?: string[];
  note?: string;
  no_probe?: boolean;
}

export interface PasteSuggestion {
  suggested: Partial<EndpointCreate>;
  confidence: number;
  parser: "json" | "dotenv" | "curl" | "none";
}

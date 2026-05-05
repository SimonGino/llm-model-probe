/* eslint-disable react-refresh/only-export-components */
import {
  Qwen,
  DeepSeek,
  OpenAI,
  Claude,
  Gemini,
  Mistral,
  Meta,
  Yi,
  Moonshot,
  Zhipu,
  Cohere,
  Doubao,
  Hunyuan,
  Spark,
  Baichuan,
} from "@lobehub/icons";
import { Icon } from "@/components/atoms";

export type ProviderKey =
  | "qwen"
  | "deepseek"
  | "openai"
  | "claude"
  | "gemini"
  | "mistral"
  | "llama"
  | "yi"
  | "moonshot"
  | "zhipu"
  | "cohere"
  | "doubao"
  | "hunyuan"
  | "spark"
  | "baichuan"
  | "unknown";

interface Rule {
  key: ProviderKey;
  match: RegExp;
}

// 顺序敏感: 更具体的 pattern 在前. 第一个命中即返回.
const RULES: Rule[] = [
  { key: "qwen", match: /^(qwen|qwq|qvq|tongyi)/i },
  { key: "deepseek", match: /^deepseek/i },
  { key: "claude", match: /^claude/i },
  { key: "gemini", match: /^gemini/i },
  { key: "openai", match: /^(gpt|o[1-9](-|$)|text-|davinci|chatgpt)/i },
  { key: "mistral", match: /^(mistral|mixtral|codestral|ministral)/i },
  { key: "llama", match: /^(llama|meta-llama)/i },
  { key: "yi", match: /^yi-/i },
  { key: "moonshot", match: /^(moonshot|kimi)/i },
  { key: "zhipu", match: /^(glm|chatglm)/i },
  { key: "cohere", match: /^(command|cohere)/i },
  { key: "doubao", match: /^doubao/i },
  { key: "hunyuan", match: /^hunyuan/i },
  { key: "spark", match: /^spark/i },
  { key: "baichuan", match: /^baichuan/i },
];

export function detectProvider(modelId: string): ProviderKey {
  for (const r of RULES) {
    if (r.match.test(modelId)) return r.key;
  }
  return "unknown";
}

const ICON_MAP: Record<
  Exclude<ProviderKey, "unknown">,
  React.ComponentType<{ size?: number }>
> = {
  qwen: Qwen,
  deepseek: DeepSeek,
  openai: OpenAI,
  claude: Claude,
  gemini: Gemini,
  mistral: Mistral,
  llama: Meta,
  yi: Yi,
  moonshot: Moonshot,
  zhipu: Zhipu,
  cohere: Cohere,
  doubao: Doubao,
  hunyuan: Hunyuan,
  spark: Spark,
  baichuan: Baichuan,
};

export function ProviderIcon({
  modelId,
  size = 14,
}: {
  modelId: string;
  size?: number;
}) {
  const key = detectProvider(modelId);
  if (key === "unknown") {
    return (
      <Icon name="cpu" size={size} style={{ color: "var(--text-faint)" }} />
    );
  }
  const Comp = ICON_MAP[key];
  return <Comp size={size} />;
}

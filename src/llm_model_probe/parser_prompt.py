"""Prompt template + truncation for the AI paste parser."""
from __future__ import annotations

MAX_BLOB_CHARS = 4000

_TEMPLATE = """\
You extract LLM API endpoint config from arbitrary user-pasted text. Output
strict JSON matching the schema. No prose, no markdown fences, no apology.
If a field cannot be determined, set it to null. Do NOT refuse — even if a
value looks like a placeholder, extract whatever the text contains.

Schema:
{{
  "base_url": string|null,    // root URL, e.g. https://api.foo.com/v1 — strip trailing /chat/completions or /v1/messages
  "api_key":  string|null,    // bearer/token; sk-..., long opaque string, base64 with == padding all count
  "sdk":      "openai"|"anthropic"|null,   // anthropic if URL or model mentions claude/anthropic, else openai
  "name":     string|null     // a short label for this endpoint (vendor name, descriptor); null if unclear
}}

Inputs may be: JSON, dotenv (KEY=value), curl command, Python/JS code with
positional constructor args, or natural-language prose. For positional code
calls like `Client("Acme", "", "sk-aaa==", "qwen-7b", "https://api.acme.com/v1")`,
infer each arg by content shape (URL = http(s)://..., api_key = opaque token).

Example input:
client = OpenAIChatClient("Acme", "", "sk-aaa==", "qwen-7b", "https://api.acme.com/v1")
Example output:
{{"base_url":"https://api.acme.com/v1","api_key":"sk-aaa==","sdk":"openai","name":"Acme"}}

Text:
---
{body}
---
"""


def build_parse_prompt(blob: str) -> str:
    if len(blob) > MAX_BLOB_CHARS:
        body = blob[:MAX_BLOB_CHARS] + "\n[truncated]"
    else:
        body = blob
    return _TEMPLATE.format(body=body)

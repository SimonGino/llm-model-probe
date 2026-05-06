"""Prompt template + truncation for the AI paste parser."""
from __future__ import annotations

MAX_BLOB_CHARS = 4000

_TEMPLATE = """\
Extract OpenAI/Anthropic-compatible endpoint config from the text below.
Output strict JSON only — no commentary, no markdown fences.

Schema:
{{
  "base_url": string|null,
  "api_key":  string|null,
  "sdk":      "openai"|"anthropic"|null,
  "name":     string|null
}}

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

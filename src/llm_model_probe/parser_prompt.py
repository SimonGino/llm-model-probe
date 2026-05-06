"""Build the LLM prompt for AI-based paste parsing."""
from __future__ import annotations

MAX_BLOB_CHARS = 4000

_PROMPT_TEMPLATE = """\
You are an assistant that extracts LLM API configuration from user-supplied text.

Extract the following fields and return ONLY a JSON object (no extra prose):
- base_url: the API base URL (string or null)
- api_key:  the API key / token (string or null)
- sdk:      one of "openai" or "anthropic" — infer from the URL or key prefix (string or null)
- name:     a short human-readable name for this endpoint, if discernible (string or null)

Rules:
- If a field cannot be determined, set it to null.
- Strip trailing slashes and well-known path suffixes (/v1/messages, /chat/completions) from base_url.
- Do NOT include any explanation or markdown — reply with a single JSON object only.

Text to parse:
---
{blob}
---"""


def build_parse_prompt(blob: str) -> str:
    """Build the parse prompt, truncating *blob* to MAX_BLOB_CHARS if needed."""
    if len(blob) > MAX_BLOB_CHARS:
        blob = blob[:MAX_BLOB_CHARS] + " [truncated]"
    return _PROMPT_TEMPLATE.format(blob=blob)

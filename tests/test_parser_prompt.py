"""Tests for AI-parse prompt builder."""
from __future__ import annotations

from llm_model_probe.parser_prompt import MAX_BLOB_CHARS, build_parse_prompt


def test_short_blob_embedded_verbatim() -> None:
    blob = "BASE_URL=https://x.example.com/v1\nKEY=sk-foo"
    prompt = build_parse_prompt(blob)
    assert blob in prompt
    assert "[truncated]" not in prompt
    # Schema must be in the prompt so the LLM knows the shape
    assert "base_url" in prompt
    assert "api_key" in prompt
    assert "sdk" in prompt
    assert "name" in prompt


def test_long_blob_truncated() -> None:
    blob = "X" * (MAX_BLOB_CHARS + 500)
    prompt = build_parse_prompt(blob)
    assert "[truncated]" in prompt
    assert prompt.count("X") == MAX_BLOB_CHARS


def test_max_blob_chars_is_4000() -> None:
    """Spec pins this at 4000."""
    assert MAX_BLOB_CHARS == 4000

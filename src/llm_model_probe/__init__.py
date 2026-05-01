"""LLM model availability probe."""
from __future__ import annotations


def main() -> None:
    from .cli import app
    app()

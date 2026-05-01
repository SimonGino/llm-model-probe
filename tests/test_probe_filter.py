"""Filter logic tests for probe orchestration."""
from llm_model_probe.probe import filter_models


def test_filter_excludes_patterns() -> None:
    models = ["gpt-4", "text-embedding-3-small", "whisper-1", "gpt-4-turbo"]
    kept, skipped = filter_models(models, exclude=["*embedding*", "*whisper*"])
    assert kept == ["gpt-4", "gpt-4-turbo"]
    assert skipped == ["text-embedding-3-small", "whisper-1"]


def test_filter_no_excludes_keeps_all() -> None:
    models = ["a", "b", "c"]
    kept, skipped = filter_models(models, exclude=[])
    assert kept == ["a", "b", "c"]
    assert skipped == []


def test_filter_case_insensitive() -> None:
    models = ["Embedding-3", "gpt-4"]
    kept, skipped = filter_models(models, exclude=["*embedding*"])
    assert kept == ["gpt-4"]
    assert "Embedding-3" in skipped

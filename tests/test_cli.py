"""CLI command-level tests (light, only the bind safeguard)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from llm_model_probe.cli import app

runner = CliRunner()


def test_ui_refuses_non_localhost_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Bind to non-localhost without token → exit 1 with helpful message."""
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(tmp_path))
    result = runner.invoke(
        app, ["ui", "--listen", "0.0.0.0", "--no-browser", "--port", "18999"]
    )
    assert result.exit_code == 1
    out = (result.stdout or "") + (result.stderr or "")
    assert "token" in out.lower() or "LLM_MODEL_PROBE_TOKEN" in out


def test_ui_allows_non_localhost_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Bind non-localhost + token set → safeguard passes (we don't actually
    start uvicorn, just verify the safeguard doesn't abort)."""
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(tmp_path))

    called: dict = {}

    import uvicorn

    def fake_run(app_str, host, port):
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = runner.invoke(
        app,
        ["ui", "--listen", "0.0.0.0", "--no-browser", "--port", "18999", "--dev"],
    )
    assert result.exit_code == 0, result.output
    assert called.get("host") == "0.0.0.0"

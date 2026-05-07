"""End-to-end CLI tests for `probe dump` and `probe load`."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_model_probe.cli import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.store import EndpointStore

runner = CliRunner()


def _seed(store: EndpointStore, name: str = "alpha", api_key: str = "sk-real") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key=api_key,
        mode="discover",
        models=["gpt-4o"],
        note="seed",
    )
    store.insert_endpoint(ep)
    return ep


def test_dump_writes_file_without_keys(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-secret")
    out = tmp_path / "reg.json"

    result = runner.invoke(app, ["dump", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["kind"] == "llm-model-probe-registry"
    assert payload["endpoints"][0]["name"] == "alpha"
    assert payload["endpoints"][0]["api_key"] is None


def test_dump_file_chmod_0600(isolated_home: Path, tmp_path: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")
    out = tmp_path / "reg.json"

    runner.invoke(app, ["dump", "--output", str(out)])

    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600


def test_dump_to_stdout_when_no_output(isolated_home: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")

    result = runner.invoke(app, ["dump"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["name"] == "alpha"


def test_dump_include_keys_writes_real_key(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-real")
    out = tmp_path / "reg.json"

    result = runner.invoke(
        app, ["dump", "--include-keys", "--output", str(out)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text())
    assert payload["endpoints"][0]["api_key"] == "sk-real"

"""End-to-end CLI tests for `probe dump` and `probe load`."""
from __future__ import annotations

import json
import stat
from pathlib import Path

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


def test_load_imports_from_file(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "preexisting")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_NEW",
            "name": "new-one",
            "sdk": "openai",
            "base_url": "https://other.example.com/v1",
            "api_key": "sk-x",
            "mode": "specified",
            "models": ["m1"],
            "tags": [],
            "note": "",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-01T10:00:00",
        }],
    }))

    result = runner.invoke(app, ["load", str(file)])

    assert result.exit_code == 0, result.output
    assert "imported" in result.output.lower()
    fresh = EndpointStore()
    fresh.init_schema()
    names = {ep.name for ep in fresh.list_endpoints()}
    assert names == {"preexisting", "new-one"}


def test_load_with_conflict_replace(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-LOCAL")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_FROM_FILE",
            "name": "alpha",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-FROM-FILE",
            "mode": "discover",
            "models": ["gpt-4o"],
            "tags": [],
            "note": "from file",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-06T14:00:00",
        }],
    }))

    result = runner.invoke(
        app, ["load", str(file), "--on-conflict", "replace"]
    )

    assert result.exit_code == 0, result.output
    fresh = EndpointStore()
    fresh.init_schema()
    alpha = fresh.get_endpoint("alpha")
    assert alpha is not None
    assert alpha.api_key == "sk-FROM-FILE"


def test_load_with_conflict_error_exits_2(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_X",
            "name": "alpha",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-x",
            "mode": "discover",
            "models": [],
            "tags": [],
            "note": "",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-01T10:00:00",
        }],
    }))

    result = runner.invoke(
        app, ["load", str(file), "--on-conflict", "error"]
    )

    assert result.exit_code == 2, result.output
    assert "alpha" in result.output


def test_load_nonexistent_file_friendly_error(
    isolated_home: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "no-such.json"
    result = runner.invoke(app, ["load", str(missing)])

    assert result.exit_code != 0
    # Should be a helpful one-liner, not a Python traceback.
    assert "Traceback" not in result.output


def test_load_garbage_file_friendly_error(
    isolated_home: Path, tmp_path: Path
) -> None:
    garbage = tmp_path / "junk.txt"
    garbage.write_text("this is not JSON")

    result = runner.invoke(app, ["load", str(garbage)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "json" in result.output.lower() or "valid" in result.output.lower()


def test_dump_to_unwritable_path_friendly_error(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")
    # parent directory does not exist
    bad = tmp_path / "no-such-dir" / "reg.json"

    result = runner.invoke(app, ["dump", "--output", str(bad)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "cannot write" in result.output.lower() or "no such" in result.output.lower()

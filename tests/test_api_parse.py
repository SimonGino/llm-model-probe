"""Tests for /api/parse-paste."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_model_probe.api import app


def _client(isolated_home: Path) -> TestClient:
    return TestClient(app)


def test_parse_json_blob(isolated_home: Path) -> None:
    blob = '{"base_url": "https://api.x/v1", "api_key": "sk-1", "models": ["a"]}'
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "json"
    assert body["suggested"]["base_url"] == "https://api.x/v1"
    assert body["suggested"]["api_key"] == "sk-1"
    assert body["suggested"]["models"] == ["a"]
    assert body["confidence"] >= 0.8


def test_parse_dotenv(isolated_home: Path) -> None:
    blob = "OPENAI_BASE_URL=https://api.y/v1\nOPENAI_API_KEY=sk-y"
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    body = r.json()
    assert body["parser"] == "dotenv"
    assert body["suggested"]["base_url"] == "https://api.y/v1"
    assert body["suggested"]["api_key"] == "sk-y"
    assert body["suggested"]["sdk"] == "openai"


def test_parse_curl(isolated_home: Path) -> None:
    blob = (
        "curl https://api.anthropic.com/v1/messages "
        "-H 'Authorization: Bearer sk-ant-xxx' "
        "-H 'content-type: application/json'"
    )
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": blob})
    body = r.json()
    assert body["parser"] == "curl"
    assert body["suggested"]["api_key"] == "sk-ant-xxx"
    assert "anthropic.com" in body["suggested"]["base_url"]
    assert body["suggested"]["sdk"] == "anthropic"


def test_parse_unrecognized(isolated_home: Path) -> None:
    r = _client(isolated_home).post("/api/parse-paste", json={"blob": "hello"})
    body = r.json()
    assert body["parser"] == "none"
    assert body["confidence"] == 0
    assert body["suggested"] == {}

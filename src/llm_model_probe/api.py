"""FastAPI app exposing /api/* for the local management UI."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

DEV_MODE = os.environ.get("LLM_MODEL_PROBE_DEV") == "1"

app = FastAPI(title="llm-model-probe")

if DEV_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------- Pydantic schemas ----------

SdkType = Literal["openai", "anthropic"]
Mode = Literal["discover", "specified"]
Status = Literal["available", "failed"]
ResultSource = Literal["discovered", "specified"]


class EndpointSummary(BaseModel):
    id: str
    name: str
    sdk: SdkType
    base_url: str
    mode: Mode
    note: str
    list_error: str | None
    available: int
    failed: int
    total_models: int
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelResultPublic(BaseModel):
    model_id: str
    source: ResultSource
    status: Status
    latency_ms: int | None
    error_type: str | None
    error_message: str | None
    response_preview: str | None
    last_tested_at: datetime | None


class EndpointDetail(EndpointSummary):
    api_key_masked: str
    models: list[str]
    excluded_by_filter: list[str]
    results: list[ModelResultPublic]


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1)
    sdk: SdkType
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    models: list[str] = []
    note: str = ""
    no_probe: bool = False


class PasteParseRequest(BaseModel):
    blob: str


class PasteParseResponse(BaseModel):
    suggested: dict
    confidence: float
    parser: Literal["json", "dotenv", "curl", "none"]


# ---------- routes ----------

from fastapi import HTTPException

from .models import Endpoint, ModelResult
from .report import mask_api_key
from .store import EndpointStore


def _store() -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _summary(store: EndpointStore, ep: Endpoint) -> EndpointSummary:
    ok, fail = store.summary(ep.id)
    return EndpointSummary(
        id=ep.id,
        name=ep.name,
        sdk=ep.sdk,
        base_url=ep.base_url,
        mode=ep.mode,
        note=ep.note,
        list_error=ep.list_error,
        available=ok,
        failed=fail,
        total_models=len(ep.models),
        last_tested_at=store.last_tested_at(ep.id),
        created_at=ep.created_at or datetime.now(),
        updated_at=ep.updated_at or datetime.now(),
    )


def _detail(store: EndpointStore, ep: Endpoint) -> EndpointDetail:
    summary = _summary(store, ep)
    results = [
        ModelResultPublic(
            model_id=r.model_id,
            source=r.source,
            status=r.status,
            latency_ms=r.latency_ms,
            error_type=r.error_type,
            error_message=r.error_message,
            response_preview=r.response_preview,
            last_tested_at=r.last_tested_at,
        )
        for r in store.list_model_results(ep.id)
    ]
    if ep.mode == "discover":
        from .probe import filter_models
        s = load_settings()
        _kept, skipped = filter_models(ep.models, s.exclude_patterns)
        excluded = skipped
    else:
        excluded = []
    return EndpointDetail(
        **summary.model_dump(),
        api_key_masked=mask_api_key(ep.api_key),
        models=ep.models,
        excluded_by_filter=excluded,
        results=results,
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/endpoints", response_model=list[EndpointSummary])
def list_endpoints() -> list[EndpointSummary]:
    store = _store()
    return [_summary(store, ep) for ep in store.list_endpoints()]


@app.get("/api/endpoints/{name_or_id}", response_model=EndpointDetail)
def get_endpoint(name_or_id: str) -> EndpointDetail:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return _detail(store, ep)


import asyncio
from fastapi import status

from .models import new_endpoint_id
from .probe import ProbeRunner
from .settings import load_settings


def _persist_models(store: EndpointStore, ep_id: str, models: list[str]) -> None:
    """Update endpoints.models JSON column without touching results.

    Reaches into store._path because the store has no public method for this
    single-column update; adding one is overkill.
    """
    import json as _j
    import sqlite3
    with sqlite3.connect(store._path) as c:
        c.execute(
            "UPDATE endpoints SET models_json = ?, updated_at = ? WHERE id = ?",
            (_j.dumps(models), datetime.now().isoformat(timespec="seconds"), ep_id),
        )
        c.commit()


@app.post(
    "/api/endpoints",
    response_model=EndpointDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_endpoint(payload: EndpointCreate) -> EndpointDetail:
    store = _store()
    mode = "specified" if payload.models else "discover"
    ep = Endpoint(
        id=new_endpoint_id(),
        name=payload.name,
        sdk=payload.sdk,
        base_url=str(payload.base_url).rstrip("/"),
        api_key=payload.api_key,
        mode=mode,  # type: ignore[arg-type]
        models=list(payload.models),
        note=payload.note,
    )
    try:
        store.insert_endpoint(ep)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if payload.no_probe:
        # UI path: discover (or accept specified) but do not probe.
        if mode == "discover":
            from .providers import make_provider
            settings = load_settings()

            async def _discover() -> list[str]:
                provider = make_provider(ep, settings.timeout_seconds)
                try:
                    return await provider.list_models()
                finally:
                    await provider.aclose()

            try:
                discovered = asyncio.run(_discover())
                ep.models = list(discovered)
                _persist_models(store, ep.id, discovered)
                store.set_list_error(ep.id, None)
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                store.set_list_error(ep.id, err)
    else:
        # CLI path: full discover + probe (unchanged).
        runner = ProbeRunner(load_settings())
        outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=False))
        if outcome.list_error:
            store.set_list_error(ep.id, outcome.list_error)
        else:
            store.set_list_error(ep.id, None)
            if outcome.new_results is not None:
                store.replace_model_results(ep.id, outcome.new_results)

    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _detail(store, fresh)


@app.delete("/api/endpoints/{name_or_id}", status_code=204)
def delete_endpoint(name_or_id: str) -> None:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    store.delete_endpoint(ep.id)


def _apply_outcome(store: EndpointStore, ep: Endpoint, outcome) -> None:
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
    if outcome.new_results is not None:
        store.replace_model_results(ep.id, outcome.new_results)


@app.post("/api/endpoints/{name_or_id}/retest", response_model=EndpointDetail)
def retest_endpoint(name_or_id: str) -> EndpointDetail:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    runner = ProbeRunner(load_settings())
    outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=True))
    _apply_outcome(store, ep, outcome)
    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _detail(store, fresh)


@app.post("/api/retest-all")
def retest_all() -> dict:
    store = _store()
    runner = ProbeRunner(load_settings())
    eps = store.list_endpoints()

    async def run_all() -> None:
        for ep in eps:
            outcome = await runner.probe_endpoint(ep, allow_partial=True)
            _apply_outcome(store, ep, outcome)

    asyncio.run(run_all())
    return {"retested": len(eps)}


# ---------- per-model probe ----------

class ProbeModelRequest(BaseModel):
    model: str = Field(min_length=1)


def _upsert_one_result(
    store: EndpointStore, ep_id: str, result: ModelResult
) -> None:
    """Replace or insert a single model_results row for (ep_id, model_id)."""
    import sqlite3

    from .store import _iso

    with sqlite3.connect(store._path) as c:
        c.execute(
            "DELETE FROM model_results WHERE endpoint_id = ? AND model_id = ?",
            (ep_id, result.model_id),
        )
        c.execute(
            """INSERT INTO model_results
               (endpoint_id, model_id, source, status, latency_ms,
                error_type, error_message, response_preview, last_tested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                result.endpoint_id, result.model_id, result.source, result.status,
                result.latency_ms, result.error_type, result.error_message,
                result.response_preview, _iso(result.last_tested_at),
            ),
        )
        c.execute(
            "UPDATE endpoints SET updated_at = ? WHERE id = ?",
            (_iso(datetime.now()), ep_id),
        )
        c.commit()


@app.post(
    "/api/endpoints/{name_or_id}/probe-model",
    response_model=ModelResultPublic,
)
def probe_model(name_or_id: str, req: ProbeModelRequest) -> ModelResultPublic:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    if req.model not in ep.models:
        raise HTTPException(
            status_code=400,
            detail=f"model '{req.model}' not in endpoint.models",
        )

    from .providers import make_provider
    settings = load_settings()

    async def _probe_one():
        provider = make_provider(ep, settings.timeout_seconds)
        try:
            return await provider.probe(
                req.model, settings.prompt, settings.max_tokens
            )
        finally:
            await provider.aclose()

    pr = asyncio.run(_probe_one())

    source = "discovered" if ep.mode == "discover" else "specified"
    new_row = ModelResult(
        endpoint_id=ep.id,
        model_id=pr.model,
        source=source,  # type: ignore[arg-type]
        status="available" if pr.available else "failed",
        latency_ms=pr.latency_ms,
        error_type=pr.error_type,
        error_message=pr.error_message,
        response_preview=pr.response_preview,
        last_tested_at=datetime.now(),
    )
    _upsert_one_result(store, ep.id, new_row)
    return ModelResultPublic(
        model_id=new_row.model_id,
        source=new_row.source,
        status=new_row.status,
        latency_ms=new_row.latency_ms,
        error_type=new_row.error_type,
        error_message=new_row.error_message,
        response_preview=new_row.response_preview,
        last_tested_at=new_row.last_tested_at,
    )


# ---------- parse-paste + settings ----------

import json as _json
import re

_DOTENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$")
_BEARER = re.compile(r"Authorization:\s*Bearer\s+(\S+)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s'\"]+")


def _guess_sdk(base_url: str) -> SdkType:
    return "anthropic" if "anthropic" in base_url.lower() else "openai"


def _parse_json(blob: str) -> dict | None:
    try:
        obj = _json.loads(blob)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    out: dict = {}
    bu = obj.get("base_url") or obj.get("baseUrl") or obj.get("BASE_URL")
    if bu:
        out["base_url"] = str(bu).rstrip("/")
    ak = obj.get("api_key") or obj.get("apiKey") or obj.get("API_KEY")
    if ak:
        out["api_key"] = str(ak)
    if isinstance(obj.get("models"), list):
        out["models"] = [str(m) for m in obj["models"]]
    if obj.get("name"):
        out["name"] = str(obj["name"])
    if obj.get("sdk") in ("openai", "anthropic"):
        out["sdk"] = obj["sdk"]
    elif "base_url" in out:
        out["sdk"] = _guess_sdk(out["base_url"])
    return out or None


def _parse_curl(blob: str) -> dict | None:
    if "curl" not in blob.lower():
        return None
    out: dict = {}
    bearer = _BEARER.search(blob)
    if bearer:
        out["api_key"] = bearer.group(1).strip("\"'")
    url_match = _URL.search(blob)
    if url_match:
        url = url_match.group(0).rstrip(",;")
        if "/v1" in url:
            url = url.split("/v1", 1)[0] + "/v1"
        else:
            from urllib.parse import urlsplit
            sp = urlsplit(url)
            url = f"{sp.scheme}://{sp.netloc}"
        out["base_url"] = url
        out["sdk"] = _guess_sdk(url)
    return out or None


def _parse_dotenv(blob: str) -> dict | None:
    out: dict = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _DOTENV_LINE.match(line)
        if not m:
            continue
        key, raw = m.group(1).upper(), m.group(2).strip().strip("\"'")
        if "BASE_URL" in key or key.endswith("_URL") or key == "URL":
            out["base_url"] = raw.rstrip("/")
        elif "API_KEY" in key or key.endswith("_KEY") or key == "KEY":
            out["api_key"] = raw
    if out and "base_url" in out:
        out["sdk"] = _guess_sdk(out["base_url"])
    return out or None


@app.post("/api/parse-paste", response_model=PasteParseResponse)
def parse_paste(req: PasteParseRequest) -> PasteParseResponse:
    blob = req.blob.strip()
    for name, fn in (("json", _parse_json), ("curl", _parse_curl),
                     ("dotenv", _parse_dotenv)):
        result = fn(blob)
        if result and ("base_url" in result or "api_key" in result):
            both = "base_url" in result and "api_key" in result
            return PasteParseResponse(
                suggested=result,
                confidence=1.0 if both else 0.6,
                parser=name,  # type: ignore[arg-type]
            )
    return PasteParseResponse(suggested={}, confidence=0.0, parser="none")


@app.get("/api/settings")
def get_settings() -> dict:
    s = load_settings()
    return {
        "concurrency": s.concurrency,
        "timeout_seconds": s.timeout_seconds,
        "max_tokens": s.max_tokens,
        "prompt": s.prompt,
        "retest_cooldown_hours": s.retest_cooldown_hours,
        "exclude_patterns": s.exclude_patterns,
    }


# ---------- static frontend (production / docker) ----------

_DIST = os.environ.get("LLM_MODEL_PROBE_DIST")
if _DIST and not DEV_MODE:
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path as _Path

    _dist_path = _Path(_DIST)
    if _dist_path.exists():
        app.mount("/", StaticFiles(directory=_dist_path, html=True), name="static")

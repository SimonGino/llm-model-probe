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

from .models import Endpoint
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
    return EndpointDetail(
        **summary.model_dump(),
        api_key_masked=mask_api_key(ep.api_key),
        models=ep.models,
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

    if not payload.no_probe:
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

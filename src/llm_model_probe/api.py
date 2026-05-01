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

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}

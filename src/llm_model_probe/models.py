"""Domain dataclasses."""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SdkType = Literal["openai", "anthropic"]
Mode = Literal["discover", "specified"]
Status = Literal["available", "failed"]
ResultSource = Literal["discovered", "specified"]


def new_endpoint_id() -> str:
    return f"ep_{secrets.token_hex(3)}"


@dataclass
class Endpoint:
    id: str
    name: str
    sdk: SdkType
    base_url: str
    api_key: str
    mode: Mode
    models: list[str] = field(default_factory=list)
    note: str = ""
    list_error: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ModelResult:
    endpoint_id: str
    model_id: str
    source: ResultSource
    status: Status
    latency_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_preview: str | None = None
    last_tested_at: datetime | None = None

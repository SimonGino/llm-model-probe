"""FastAPI app exposing /api/* for the local management UI."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

_STRIP_SUFFIXES = (
    "/v1/messages",
    "/chat/completions",
    "/messages",
    "/completions",
)

_CORE_FIELDS: frozenset[str] = frozenset({"sdk", "base_url", "api_key"})


def normalize_base_url(url: str) -> str:
    """Strip well-known completion-endpoint suffixes from a base URL.

    Iterates _STRIP_SUFFIXES which is ordered so that longer/more-specific
    suffixes come first — first match wins.
    """
    s = url.rstrip("/")
    lowered = s.lower()
    for suffix in _STRIP_SUFFIXES:
        if lowered.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.rstrip("/")


DEV_MODE = os.environ.get("LLM_MODEL_PROBE_DEV") == "1"

app = FastAPI(title="llm-model-probe")

if DEV_MODE:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Bearer token gate for /api/* (except /api/health).

    Reads LLM_MODEL_PROBE_TOKEN at request time so tests can monkeypatch it.
    Empty/unset = auth disabled (legacy local mode).
    """
    expected = os.environ.get("LLM_MODEL_PROBE_TOKEN", "")
    if not expected:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path == "/api/health":
        return await call_next(request)
    if request.method == "OPTIONS":
        # CORS preflight bypass
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "missing bearer token"},
        )
    if auth_header[len("Bearer ") :] != expected:
        return JSONResponse(
            status_code=401,
            content={"detail": "invalid token"},
        )

    return await call_next(request)


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
    tags: list[str]
    last_tested_at: datetime | None
    stale_since: datetime | None
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
    tags: list[str] = []
    no_probe: bool = False


class EndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    sdk: SdkType | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    note: str | None = None


class PasteParseRequest(BaseModel):
    blob: str


class ParserSettings(BaseModel):
    endpoint_id: str | None
    model_id: str | None


class PasteParseResponse(BaseModel):
    suggested: dict
    confidence: float
    parser: Literal["json", "dotenv", "curl", "none"]


class AiParseRequest(BaseModel):
    blob: str = Field(..., min_length=1)


class AiParseResponse(BaseModel):
    base_url: str | None
    api_key: str | None
    sdk: SdkType | None
    name: str | None
    confidence: float
    latency_ms: int
    raw_text: str | None = None


# ---------- routes ----------

from fastapi import HTTPException

from .models import Endpoint, ModelResult
from .report import mask_api_key
from .store import EndpointStore


def _store() -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _normalize_tags(raw: list[str]) -> list[str]:
    """Trim whitespace, drop empties, dedupe preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        s = t.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


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
        tags=ep.tags,
        last_tested_at=store.last_tested_at(ep.id),
        stale_since=ep.stale_since,
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


class AuthCheckResponse(BaseModel):
    ok: bool


@app.get("/api/auth/check", response_model=AuthCheckResponse)
def auth_check() -> AuthCheckResponse:
    # Middleware already validated token (or auth is disabled);
    # if execution reaches here, the caller is authorized.
    return AuthCheckResponse(ok=True)


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
    base_url = normalize_base_url(str(payload.base_url))
    ep = Endpoint(
        id=new_endpoint_id(),
        name=payload.name,
        sdk=payload.sdk,
        base_url=base_url,
        api_key=payload.api_key,
        mode=mode,  # type: ignore[arg-type]
        models=list(payload.models),
        note=payload.note,
        tags=_normalize_tags(payload.tags),
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


@app.patch(
    "/api/endpoints/{name_or_id}",
    response_model=EndpointDetail,
)
def update_endpoint_route(
    name_or_id: str, payload: EndpointUpdate
) -> EndpointDetail:
    store = _store()
    existing = store.get_endpoint(name_or_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="endpoint not found")

    new_name = payload.name
    new_sdk = payload.sdk
    new_base_url = (
        normalize_base_url(str(payload.base_url))
        if payload.base_url is not None
        else None
    )
    new_api_key = payload.api_key
    new_note = payload.note

    update_kwargs: dict[str, object] = {}

    # Name uniqueness — same name as self is fine
    if new_name is not None and new_name != existing.name:
        other = store.get_endpoint(new_name)
        if other is not None and other.id != existing.id:
            raise HTTPException(
                status_code=409,
                detail=f"name '{new_name}' already in use",
            )
        update_kwargs["name"] = new_name

    if new_sdk is not None and new_sdk != existing.sdk:
        update_kwargs["sdk"] = new_sdk
    if new_base_url is not None and new_base_url != existing.base_url:
        update_kwargs["base_url"] = new_base_url
    if new_api_key is not None and new_api_key != existing.api_key:
        update_kwargs["api_key"] = new_api_key
    if new_note is not None and new_note != existing.note:
        update_kwargs["note"] = new_note

    if update_kwargs.keys() & _CORE_FIELDS:
        update_kwargs["stale_since"] = datetime.now()

    if update_kwargs:
        try:
            store.update_endpoint(existing.id, **update_kwargs)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    fresh = store.get_endpoint(existing.id)
    assert fresh is not None
    return _detail(store, fresh)


class TagsUpdate(BaseModel):
    tags: list[str]


@app.put(
    "/api/endpoints/{name_or_id}/tags",
    response_model=EndpointSummary,
)
def set_tags(name_or_id: str, body: TagsUpdate) -> EndpointSummary:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    normalized = _normalize_tags(body.tags)
    store.set_tags(ep.id, normalized)
    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _summary(store, fresh)


class ApiKeyResponse(BaseModel):
    api_key: str


@app.get(
    "/api/endpoints/{name_or_id}/api-key",
    response_model=ApiKeyResponse,
)
def get_api_key(name_or_id: str) -> ApiKeyResponse:
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return ApiKeyResponse(api_key=ep.api_key)


def _apply_outcome(store: EndpointStore, ep: Endpoint, outcome) -> None:
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
    if outcome.new_results is not None:
        store.replace_model_results(ep.id, outcome.new_results)
    if not outcome.list_error:
        store.update_endpoint(ep.id, stale_since=None)


from .registry_io import dump_endpoints


@app.get("/api/registry/dump")
def dump_registry(include_keys: bool = False) -> JSONResponse:
    """Return the registry as a downloadable JSON file."""
    store = _store()
    payload = dump_endpoints(
        store.list_endpoints(),
        include_keys=include_keys,
    )
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"llm-model-probe-registry-{today}.json"
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.post(
    "/api/endpoints/{name_or_id}/rediscover",
    response_model=EndpointDetail,
)
def rediscover_endpoint(name_or_id: str) -> EndpointDetail:
    """Re-fetch /v1/models for a discover-mode endpoint without probing.

    Use case: user pasted a bad API key, fixed it, wants the model list
    refreshed; probing happens via the separate `Test all` button.
    """
    store = _store()
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    if ep.mode != "discover":
        raise HTTPException(
            status_code=400,
            detail="endpoint is in 'specified' mode; rediscover not applicable",
        )
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
        _persist_models(store, ep.id, discovered)
        # Drop results for models that are no longer listed; otherwise their
        # stale failed/available counts leak into the endpoint summary.
        store.delete_orphan_results(ep.id, discovered)
        store.set_list_error(ep.id, None)
        store.update_endpoint(ep.id, stale_since=None)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        store.set_list_error(ep.id, err)

    fresh = store.get_endpoint(ep.id)
    assert fresh is not None
    return _detail(store, fresh)


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


# ---------- parser settings ----------

def _read_parser_settings(store: EndpointStore) -> ParserSettings:
    """Read parser.endpoint_id + parser.model_id, auto-nulling on staleness."""
    ep_id = store.get_setting("parser.endpoint_id")
    m_id = store.get_setting("parser.model_id")
    if not ep_id or not m_id:
        return ParserSettings(endpoint_id=None, model_id=None)
    ep = store.get_endpoint(ep_id)
    if ep is None or m_id not in ep.models:
        return ParserSettings(endpoint_id=None, model_id=None)
    return ParserSettings(endpoint_id=ep_id, model_id=m_id)


def _extract_json_object(text: str) -> dict | None:
    """Try strict json.loads first, then fall back to the first {...} block."""
    import json as _j
    import re as _re

    text = text.strip()
    try:
        v = _j.loads(text)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    m = _re.search(r"\{.*?\}", text, flags=_re.DOTALL)
    if not m:
        return None
    try:
        v = _j.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except Exception:
        return None


@app.get("/api/settings/parser", response_model=ParserSettings)
def get_parser_settings() -> ParserSettings:
    return _read_parser_settings(_store())


@app.put("/api/settings/parser", response_model=ParserSettings)
def put_parser_settings(payload: ParserSettings) -> ParserSettings:
    store = _store()
    if not payload.endpoint_id or not payload.model_id:
        raise HTTPException(
            status_code=400, detail="endpoint_id and model_id are required"
        )
    ep = store.get_endpoint(payload.endpoint_id)
    if ep is None:
        raise HTTPException(status_code=400, detail="endpoint not found")
    if payload.model_id not in ep.models:
        raise HTTPException(
            status_code=400, detail="model_id not in endpoint.models"
        )
    store.set_setting("parser.endpoint_id", payload.endpoint_id)
    store.set_setting("parser.model_id", payload.model_id)
    return ParserSettings(
        endpoint_id=payload.endpoint_id, model_id=payload.model_id
    )


@app.post("/api/ai-parse", response_model=AiParseResponse)
def ai_parse(req: AiParseRequest) -> AiParseResponse:
    from .parser_prompt import build_parse_prompt
    from .providers import make_provider

    store = _store()
    settings = _read_parser_settings(store)
    if settings.endpoint_id is None or settings.model_id is None:
        raise HTTPException(
            status_code=412,
            detail="default parser not configured; set one in Settings",
        )
    ep = store.get_endpoint(settings.endpoint_id)
    assert ep is not None  # _read_parser_settings already nulled stale rows

    prompt = build_parse_prompt(req.blob)
    runtime = load_settings()
    provider = make_provider(ep, runtime.timeout_seconds)
    try:
        try:
            result = asyncio.run(
                provider.complete(settings.model_id, prompt, max_tokens=1500)
            )
        finally:
            asyncio.run(provider.aclose())
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"{type(e).__name__}: {str(e)[:200]}",
        )

    obj = _extract_json_object(result.text) or {}

    def _get(key: str) -> str | None:
        v = obj.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    base_url = _get("base_url")
    api_key = _get("api_key")
    sdk = _get("sdk")
    if sdk not in ("openai", "anthropic"):
        sdk = None
    name = _get("name")

    if base_url and api_key:
        confidence = 1.0
    elif base_url or api_key:
        confidence = 0.5
    else:
        confidence = 0.0

    return AiParseResponse(
        base_url=base_url,
        api_key=api_key,
        sdk=sdk,  # type: ignore[arg-type]
        name=name,
        confidence=confidence,
        latency_ms=result.latency_ms,
        raw_text=(result.text or "")[:600],
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
        url = normalize_base_url(url)
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

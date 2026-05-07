"""Cross-machine registry serialization (dump / load).

Pure-ish module: functions accept an EndpointStore for load, but JSON
serialization and file IO live in the callers (cli, api). This keeps unit
tests simple and the surface narrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .models import Endpoint

SCHEMA_KIND = "llm-model-probe-registry"
SCHEMA_VERSION = 1


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def dump_endpoints(
    endpoints: list[Endpoint],
    *,
    include_keys: bool,
    now: datetime | None = None,
) -> dict:
    """Build a JSON-serializable envelope for the registry.

    `include_keys=False` writes `api_key: null`; True writes the plaintext key.
    `now` is overridable for deterministic tests.
    """
    when = now or datetime.now()
    return {
        "kind": SCHEMA_KIND,
        "version": SCHEMA_VERSION,
        "exported_at": _iso(when),
        "endpoints": [
            {
                "id": ep.id,
                "name": ep.name,
                "sdk": ep.sdk,
                "base_url": ep.base_url,
                "api_key": ep.api_key if include_keys else None,
                "mode": ep.mode,
                "models": list(ep.models),
                "tags": list(ep.tags),
                "note": ep.note,
                "created_at": _iso(ep.created_at),
                "updated_at": _iso(ep.updated_at),
            }
            for ep in endpoints
        ],
    }


@dataclass
class LoadReport:
    imported: list[str] = field(default_factory=list)   # newly inserted names
    replaced: list[str] = field(default_factory=list)   # existing names overwritten
    skipped: list[str] = field(default_factory=list)    # conflict, on_conflict=skip
    missing_keys: list[str] = field(default_factory=list)  # api_key empty after load


class LoadFormatError(ValueError):
    """The payload doesn't match the v1 registry envelope schema."""


class LoadConflict(Exception):
    """on_conflict='error' and a name conflict was found."""


def load_endpoints(
    payload: dict,
    store,  # EndpointStore — type-annotated softly to avoid circular imports
    *,
    on_conflict: Literal["skip", "replace", "error"],
) -> LoadReport:
    """Stub — implemented in later tasks."""
    raise NotImplementedError

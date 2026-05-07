"""Cross-machine registry serialization (dump / load).

Pure-ish module: functions accept an EndpointStore for load, but JSON
serialization and file IO live in the callers (cli, api). This keeps unit
tests simple and the surface narrow.
"""
from __future__ import annotations

import json
import sqlite3
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


_VALID_SDKS = {"openai", "anthropic"}
_VALID_MODES = {"discover", "specified"}
_REQUIRED_FIELDS = (
    "id", "name", "sdk", "base_url", "api_key", "mode",
    "models", "tags", "note",
)


@dataclass
class _Row:
    id: str
    name: str
    sdk: str
    base_url: str
    api_key: str | None
    mode: str
    models: list[str]
    tags: list[str]
    note: str
    created_at: str | None
    updated_at: str | None


def _parse_row(raw: dict, idx: int) -> _Row:
    """Validate one endpoint dict and return a typed _Row.

    `idx` is the position in the file for nicer error messages.
    """
    if not isinstance(raw, dict):
        raise LoadFormatError(f"endpoints[{idx}] is not an object")
    for field_name in _REQUIRED_FIELDS:
        if field_name not in raw:
            raise LoadFormatError(
                f"endpoints[{idx}] missing required field '{field_name}'"
            )
    name = raw["name"]
    if not isinstance(name, str) or not name:
        raise LoadFormatError(
            f"endpoints[{idx}] has invalid name {raw['name']!r}"
        )
    if raw["sdk"] not in _VALID_SDKS:
        raise LoadFormatError(
            f"endpoint '{name}' has invalid sdk={raw['sdk']!r}"
        )
    if raw["mode"] not in _VALID_MODES:
        raise LoadFormatError(
            f"endpoint '{name}' has invalid mode={raw['mode']!r}"
        )
    if not isinstance(raw["models"], list) or not all(
        isinstance(m, str) for m in raw["models"]
    ):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string-list models"
        )
    if not isinstance(raw["tags"], list) or not all(
        isinstance(t, str) for t in raw["tags"]
    ):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string-list tags"
        )
    api_key = raw["api_key"]
    if api_key is not None and not isinstance(api_key, str):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string api_key"
        )
    return _Row(
        id=str(raw["id"]),
        name=name,
        sdk=raw["sdk"],
        base_url=str(raw["base_url"]),
        api_key=api_key,
        mode=raw["mode"],
        models=list(raw["models"]),
        tags=list(raw["tags"]),
        note=str(raw["note"]),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def _validate_envelope(payload: dict) -> list[_Row]:
    if not isinstance(payload, dict):
        raise LoadFormatError("file is not a JSON object")
    if payload.get("kind") != SCHEMA_KIND:
        raise LoadFormatError(
            f"file kind={payload.get('kind')!r}; expected {SCHEMA_KIND!r}"
        )
    version = payload.get("version")
    if not isinstance(version, int):
        raise LoadFormatError("file version missing or not an integer")
    if version > SCHEMA_VERSION:
        raise LoadFormatError(
            f"file version {version} not supported; please upgrade probe"
        )
    if version < 1:
        raise LoadFormatError(f"file version {version} not supported")
    rows_raw = payload.get("endpoints")
    if not isinstance(rows_raw, list):
        raise LoadFormatError("file 'endpoints' must be an array")
    rows = [_parse_row(r, i) for i, r in enumerate(rows_raw)]
    # Same name twice in the file — corrupted.
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for r in rows:
        if r.name in seen_names:
            raise LoadFormatError(
                f"duplicate name {r.name!r} in file"
            )
        seen_names.add(r.name)
        if r.id in seen_ids:
            raise LoadFormatError(f"duplicate id {r.id!r} in file")
        seen_ids.add(r.id)
    return rows


def load_endpoints(
    payload: dict,
    store,  # EndpointStore — type-annotated softly to avoid circular imports
    *,
    on_conflict: Literal["skip", "replace", "error"],
) -> LoadReport:
    """Validate envelope, then apply to the store inside a single transaction.

    Conflict matching is by `name` (the DB UNIQUE column). File `id` is used
    on insert (round-trip stability); on replace, the existing local id is
    kept so model_results FK rows survive.
    """
    if on_conflict not in ("skip", "replace", "error"):
        raise ValueError(
            f"on_conflict must be skip|replace|error, got {on_conflict!r}"
        )
    rows = _validate_envelope(payload)

    existing_by_name = {ep.name: ep for ep in store.list_endpoints()}
    report = LoadReport()
    plan: list[tuple[str, _Row, str | None]] = []  # (action, row, existing_id)

    for r in rows:
        existing = existing_by_name.get(r.name)
        if existing is None:
            plan.append(("insert", r, None))
            report.imported.append(r.name)
        else:
            if on_conflict == "skip":
                report.skipped.append(r.name)
            elif on_conflict == "replace":
                plan.append(("update", r, existing.id))
                report.replaced.append(r.name)
            else:  # "error"
                raise LoadConflict(
                    f"endpoint {r.name!r} already exists "
                    "(use --on-conflict=replace to override)"
                )

    now_iso = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(store._path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            for action, r, existing_id in plan:
                key = r.api_key if r.api_key is not None else ""
                if not key:
                    report.missing_keys.append(r.name)
                if action == "insert":
                    conn.execute(
                        """INSERT INTO endpoints
                           (id, name, sdk, base_url, api_key, mode,
                            models_json, note, list_error, tags_json,
                            stale_since, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            r.id, r.name, r.sdk, r.base_url, key, r.mode,
                            json.dumps(r.models), r.note, None,
                            json.dumps(r.tags), None,
                            r.created_at or now_iso,
                            r.updated_at or now_iso,
                        ),
                    )
                else:  # "update" — replace path
                    conn.execute(
                        """UPDATE endpoints SET
                              name = ?, sdk = ?, base_url = ?,
                              api_key = ?, mode = ?, models_json = ?,
                              note = ?, tags_json = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            r.name, r.sdk, r.base_url, key, r.mode,
                            json.dumps(r.models), r.note,
                            json.dumps(r.tags), now_iso, existing_id,
                        ),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return report

"""SQLite-backed registry for endpoints and per-model probe results."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Endpoint, ModelResult
from .paths import db_path, ensure_home

class _Unset:
    """Sentinel type for update_endpoint: field not supplied (vs explicit None)."""

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET: _Unset = _Unset()

SCHEMA = """
CREATE TABLE IF NOT EXISTS endpoints (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sdk         TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    models_json TEXT NOT NULL DEFAULT '[]',
    note        TEXT NOT NULL DEFAULT '',
    list_error  TEXT,
    tags_json   TEXT NOT NULL DEFAULT '[]',
    stale_since TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_results (
    endpoint_id      TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    source           TEXT NOT NULL,
    status           TEXT NOT NULL,
    latency_ms       INTEGER,
    error_type       TEXT,
    error_message    TEXT,
    response_preview TEXT,
    last_tested_at   TEXT NOT NULL,
    PRIMARY KEY (endpoint_id, model_id),
    FOREIGN KEY (endpoint_id) REFERENCES endpoints(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_model_results_endpoint
    ON model_results(endpoint_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _from_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class EndpointStore:
    def __init__(self, path: Path | None = None) -> None:
        ensure_home()
        self._path = path or db_path()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate_tags(c)
            self._migrate_stale_since(c)
            self._backfill_models_from_results(c)
        try:
            self._path.chmod(0o600)
        except FileNotFoundError:
            pass

    @staticmethod
    def _migrate_tags(c: sqlite3.Connection) -> None:
        """Old DB without tags_json column - idempotently add it."""
        cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
        if "tags_json" not in cols:
            c.execute(
                "ALTER TABLE endpoints "
                "ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
            )

    @staticmethod
    def _migrate_stale_since(c: sqlite3.Connection) -> None:
        """Old DB without stale_since column - idempotently add it."""
        cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
        if "stale_since" not in cols:
            c.execute(
                "ALTER TABLE endpoints ADD COLUMN stale_since TEXT"
            )

    @staticmethod
    def _backfill_models_from_results(c: sqlite3.Connection) -> None:
        """Pre-redesign discover-mode endpoints had empty models_json but
        their probed model_ids live in model_results. Reconstruct the list
        so the new UI (which renders from endpoints.models) can show them.

        Idempotent: only touches rows where models_json == '[]' AND there
        are matching model_results.
        """
        rows = c.execute(
            """SELECT id FROM endpoints
               WHERE models_json = '[]'
                 AND id IN (SELECT DISTINCT endpoint_id FROM model_results)"""
        ).fetchall()
        for row in rows:
            ep_id = row["id"]
            model_rows = c.execute(
                "SELECT DISTINCT model_id FROM model_results "
                "WHERE endpoint_id = ? ORDER BY model_id",
                (ep_id,),
            ).fetchall()
            models = [m["model_id"] for m in model_rows]
            c.execute(
                "UPDATE endpoints SET models_json = ? WHERE id = ?",
                (json.dumps(models), ep_id),
            )

    # --- endpoints --------------------------------------------------

    def insert_endpoint(self, ep: Endpoint) -> None:
        now = datetime.now()
        ep.created_at = ep.created_at or now
        ep.updated_at = now
        try:
            with self._conn() as c:
                c.execute(
                    """INSERT INTO endpoints
                       (id, name, sdk, base_url, api_key, mode, models_json,
                        note, list_error, tags_json, stale_since,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ep.id, ep.name, ep.sdk, ep.base_url, ep.api_key,
                        ep.mode, json.dumps(ep.models), ep.note,
                        ep.list_error, json.dumps(ep.tags),
                        _iso(ep.stale_since),
                        _iso(ep.created_at), _iso(ep.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"endpoint name '{ep.name}' already exists") from e

    def get_endpoint(self, name_or_id: str) -> Endpoint | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM endpoints WHERE id = ? OR name = ?",
                (name_or_id, name_or_id),
            ).fetchone()
        return self._row_to_endpoint(row) if row else None

    def list_endpoints(self) -> list[Endpoint]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM endpoints ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_endpoint(r) for r in rows]

    def delete_endpoint(self, ep_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM endpoints WHERE id = ?", (ep_id,))

    def set_list_error(self, ep_id: str, error: str | None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE endpoints SET list_error = ?, updated_at = ? WHERE id = ?",
                (error, _iso(datetime.now()), ep_id),
            )

    def set_tags(self, ep_id: str, tags: list[str]) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE endpoints SET tags_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(tags), _iso(datetime.now()), ep_id),
            )

    def update_endpoint(
        self,
        ep_id: str,
        *,
        name: str | None = None,
        sdk: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        note: str | None = None,
        stale_since: datetime | None | _Unset = _UNSET,
    ) -> None:
        """Partial update.

        For str fields, None means "leave unchanged".
        For stale_since, the default sentinel means "leave unchanged"; pass
        a datetime to set, or None to explicitly clear.
        """
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if sdk is not None:
            sets.append("sdk = ?")
            params.append(sdk)
        if base_url is not None:
            sets.append("base_url = ?")
            params.append(base_url)
        if api_key is not None:
            sets.append("api_key = ?")
            params.append(api_key)
        if note is not None:
            sets.append("note = ?")
            params.append(note)
        if stale_since is not _UNSET:
            sets.append("stale_since = ?")
            params.append(_iso(stale_since) if stale_since is not None else None)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(_iso(datetime.now()))
        params.append(ep_id)
        sql = f"UPDATE endpoints SET {', '.join(sets)} WHERE id = ?"
        try:
            with self._conn() as c:
                c.execute(sql, params)
        except sqlite3.IntegrityError as e:
            raise ValueError(
                f"endpoint name '{name}' already exists"
            ) from e

    # --- model_results ---------------------------------------------

    def replace_model_results(
        self, ep_id: str, results: list[ModelResult]
    ) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM model_results WHERE endpoint_id = ?", (ep_id,))
            c.executemany(
                """INSERT INTO model_results
                   (endpoint_id, model_id, source, status, latency_ms,
                    error_type, error_message, response_preview, last_tested_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        r.endpoint_id, r.model_id, r.source, r.status,
                        r.latency_ms, r.error_type, r.error_message,
                        r.response_preview, _iso(r.last_tested_at),
                    )
                    for r in results
                ],
            )
            c.execute(
                "UPDATE endpoints SET updated_at = ? WHERE id = ?",
                (_iso(datetime.now()), ep_id),
            )

    def delete_orphan_results(self, ep_id: str, keep: list[str]) -> int:
        """Delete model_results rows whose model_id is not in `keep`.

        Returns count of rows removed. Used after rediscover to drop stale
        results for models the provider no longer lists.
        """
        with self._conn() as c:
            if not keep:
                cur = c.execute(
                    "DELETE FROM model_results WHERE endpoint_id = ?", (ep_id,)
                )
                return cur.rowcount or 0
            placeholders = ",".join("?" for _ in keep)
            cur = c.execute(
                f"DELETE FROM model_results WHERE endpoint_id = ? "
                f"AND model_id NOT IN ({placeholders})",
                (ep_id, *keep),
            )
            return cur.rowcount or 0

    # --- app_settings (single-row K/V) -----------------------------

    def get_setting(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        now = _iso(datetime.now())
        with self._conn() as c:
            c.execute(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at""",
                (key, value, now),
            )

    def delete_setting(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    def list_model_results(self, ep_id: str) -> list[ModelResult]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM model_results WHERE endpoint_id = ? ORDER BY model_id",
                (ep_id,),
            ).fetchall()
        return [
            ModelResult(
                endpoint_id=r["endpoint_id"],
                model_id=r["model_id"],
                source=r["source"],
                status=r["status"],
                latency_ms=r["latency_ms"],
                error_type=r["error_type"],
                error_message=r["error_message"],
                response_preview=r["response_preview"],
                last_tested_at=_from_iso(r["last_tested_at"]),
            )
            for r in rows
        ]

    def last_tested_at(self, ep_id: str) -> datetime | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(last_tested_at) AS m FROM model_results WHERE endpoint_id = ?",
                (ep_id,),
            ).fetchone()
        return _from_iso(row["m"]) if row and row["m"] else None

    def summary(self, ep_id: str) -> tuple[int, int]:
        """Return (available_count, failed_count)."""
        with self._conn() as c:
            row = c.execute(
                """SELECT
                       SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) AS bad
                   FROM model_results WHERE endpoint_id = ?""",
                (ep_id,),
            ).fetchone()
        return (int(row["ok"] or 0), int(row["bad"] or 0))

    # --- mapping ----------------------------------------------------

    @staticmethod
    def _row_to_endpoint(row: sqlite3.Row) -> Endpoint:
        return Endpoint(
            id=row["id"],
            name=row["name"],
            sdk=row["sdk"],
            base_url=row["base_url"],
            api_key=row["api_key"],
            mode=row["mode"],
            models=json.loads(row["models_json"]),
            note=row["note"],
            list_error=row["list_error"],
            tags=json.loads(row["tags_json"]),
            stale_since=_from_iso(row["stale_since"]),
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )

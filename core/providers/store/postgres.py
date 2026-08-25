"""Postgres store per the DDL in spec 4.3. Used when DATABASE_URL is set.

Requires the optional `asyncpg` dependency (`pip install intakepilot[postgres]`).
Append-only versioning is enforced by the (req_id, version) primary key.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from core.models import RequirementObject
from core.providers.store.base import AppendOnlyViolation

DDL = """
CREATE TABLE IF NOT EXISTS requirements (
  req_id TEXT, version INT, obj JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (req_id, version));

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, req_id TEXT,
  turns JSONB, pending_questions JSONB, budget_spent INT DEFAULT 0,
  requester JSONB, decisions JSONB, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS edit_diffs (
  id BIGSERIAL PRIMARY KEY,
  req_id TEXT, version INT, slot_key TEXT,
  proposed JSONB, corrected JSONB,
  provenance TEXT,
  context_bucket TEXT,
  ask_embedding JSONB,
  created_at TIMESTAMPTZ DEFAULT now());
ALTER TABLE edit_diffs ADD COLUMN IF NOT EXISTS provenance TEXT;

CREATE TABLE IF NOT EXISTS question_ledger (
  id BIGSERIAL PRIMARY KEY, req_id TEXT, slot_key TEXT,
  question TEXT, outcome TEXT,
  changed_routing BOOL, changed_slots INT,
  created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE IF NOT EXISTS outcome_ledger (
  id BIGSERIAL PRIMARY KEY, req_id TEXT,
  stage TEXT, verdict TEXT, detail JSONB,
  created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE IF NOT EXISTS glossary (
  term TEXT PRIMARY KEY, maps_to JSONB,
  evidence_count INT DEFAULT 1, last_confirmed TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS system_kb (
  system TEXT, entity TEXT, label TEXT, schema JSONB,
  evidence_count INT DEFAULT 1, verified BOOL DEFAULT FALSE,
  last_refreshed TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (system, entity));

CREATE TABLE IF NOT EXISTS shares (
  id BIGSERIAL PRIMARY KEY,
  token TEXT UNIQUE,
  req_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ,
  payload JSONB);

CREATE TABLE IF NOT EXISTS manas_outbox (
  id BIGSERIAL PRIMARY KEY,
  outbox_id TEXT, req_id TEXT, event_type TEXT,
  content_hash TEXT, envelope_json TEXT,
  state TEXT, reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE IF NOT EXISTS analyst_signals (
  id BIGSERIAL PRIMARY KEY,
  process TEXT, signal TEXT, accepted_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE IF NOT EXISTS seq (year INT PRIMARY KEY, n INT);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS decisions JSONB;
"""

LEDGER_COLS = {
    "edit_diffs": ["req_id", "version", "slot_key", "proposed", "corrected",
                   "provenance", "context_bucket", "ask_embedding"],
    "question_ledger": ["req_id", "slot_key", "question", "outcome",
                        "changed_routing", "changed_slots"],
    "outcome_ledger": ["req_id", "stage", "verdict", "detail"],
    "glossary": ["term", "maps_to", "evidence_count", "last_confirmed"],
    "system_kb": ["system", "entity", "label", "schema", "evidence_count",
                  "verified", "last_refreshed"],
    "shares": ["token", "req_id", "created_at", "expires_at", "payload"],
    "manas_outbox": ["outbox_id", "req_id", "event_type", "content_hash",
                     "envelope_json", "state", "reason"],
    "analyst_signals": ["process", "signal", "accepted_by"],
}
_JSON_COLS = {"proposed", "corrected", "ask_embedding", "detail", "maps_to",
              "schema", "payload"}
# Callers pass ISO strings / 0-1 ints (SQLite-friendly); asyncpg needs
# real datetime / bool for TIMESTAMPTZ / BOOL columns.
_TS_COLS = {"last_confirmed", "last_refreshed", "created_at", "expires_at"}
_BOOL_COLS = {"changed_routing", "verified"}


def _coerce(col: str, value):
    if col in _JSON_COLS:
        return json.dumps(value)
    if col in _TS_COLS and isinstance(value, str):
        return datetime.fromisoformat(value)
    if col in _BOOL_COLS and value is not None and not isinstance(value, bool):
        return bool(value)
    return value


class PostgresStore:
    name = "postgres"

    def __init__(self, config: dict | None = None):
        self.dsn = os.environ.get("DATABASE_URL") or (config or {}).get("dsn")
        if not self.dsn:
            raise RuntimeError("PostgresStore requires DATABASE_URL")
        self._pool = None

    async def _p(self):
        if self._pool is None:
            import asyncpg  # optional dependency, imported lazily
            self._pool = await asyncpg.create_pool(self.dsn)
            async with self._pool.acquire() as conn:
                await conn.execute(DDL)
        return self._pool

    async def put_version(self, obj: RequirementObject) -> None:
        import asyncpg
        pool = await self._p()
        try:
            await pool.execute(
                "INSERT INTO requirements (req_id, version, obj) VALUES ($1,$2,$3::jsonb)",
                obj.req_id, obj.version, obj.model_dump_json())
        except asyncpg.UniqueViolationError as exc:
            raise AppendOnlyViolation(f"{obj.req_id} v{obj.version} already exists") from exc

    async def put_version_with_outbox(self, obj: RequirementObject,
                                      outbox_row: dict) -> None:
        """Requirement version + MANAS outbox row in one transaction."""
        import asyncpg
        pool = await self._p()
        cols = [c for c in LEDGER_COLS["manas_outbox"] if c in outbox_row]
        vals = [outbox_row[c] for c in cols]
        async with pool.acquire() as conn:
            async with conn.transaction():
                try:
                    await conn.execute(
                        "INSERT INTO requirements (req_id, version, obj) "
                        "VALUES ($1,$2,$3::jsonb)",
                        obj.req_id, obj.version, obj.model_dump_json())
                except asyncpg.UniqueViolationError as exc:
                    raise AppendOnlyViolation(
                        f"{obj.req_id} v{obj.version} already exists") from exc
                await conn.execute(
                    f"INSERT INTO manas_outbox ({','.join(cols)}) "
                    f"VALUES ({','.join(f'${i + 1}' for i in range(len(cols)))})",
                    *vals)

    async def latest(self, req_id: str) -> RequirementObject:
        pool = await self._p()
        row = await pool.fetchrow(
            "SELECT obj FROM requirements WHERE req_id=$1 ORDER BY version DESC LIMIT 1", req_id)
        if row is None:
            raise KeyError(req_id)
        return RequirementObject.model_validate_json(row["obj"])

    async def history(self, req_id: str) -> list[RequirementObject]:
        pool = await self._p()
        rows = await pool.fetch(
            "SELECT obj FROM requirements WHERE req_id=$1 ORDER BY version", req_id)
        return [RequirementObject.model_validate_json(r["obj"]) for r in rows]

    async def version_timestamps(self, req_id: str) -> list[tuple[int, str]]:
        pool = await self._p()
        rows = await pool.fetch(
            "SELECT version, created_at FROM requirements WHERE req_id=$1 ORDER BY version", req_id)
        return [(r["version"], r["created_at"].isoformat()) for r in rows]

    async def log(self, table: str, row: dict) -> None:
        if table not in LEDGER_COLS:
            raise ValueError(f"unknown ledger table: {table}")
        pool = await self._p()
        cols = [c for c in LEDGER_COLS[table] if c in row]
        vals = [_coerce(c, row[c]) for c in cols]
        casts = [f"${i + 1}::jsonb" if c in _JSON_COLS else f"${i + 1}"
                 for i, c in enumerate(cols)]
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(casts)})"
        if table == "glossary":
            sql += (" ON CONFLICT (term) DO UPDATE SET maps_to=EXCLUDED.maps_to,"
                    " evidence_count=EXCLUDED.evidence_count, last_confirmed=now()")
        elif table == "system_kb":
            sql += (" ON CONFLICT (system, entity) DO UPDATE SET"
                    " label=EXCLUDED.label, schema=EXCLUDED.schema,"
                    " evidence_count=EXCLUDED.evidence_count,"
                    " verified=EXCLUDED.verified, last_refreshed=now()")
        await pool.execute(sql, *vals)

    async def query_ledger(self, table: str, **filters) -> list[dict]:
        if table not in LEDGER_COLS:
            raise ValueError(f"unknown ledger table: {table}")
        pool = await self._p()
        sql, vals = f"SELECT * FROM {table}", []
        if filters:
            sql += " WHERE " + " AND ".join(
                f"{k}=${i + 1}" for i, k in enumerate(filters))
            vals = list(filters.values())
        rows = await pool.fetch(sql, *vals)
        out = []
        for r in rows:
            d = dict(r)
            for c in _JSON_COLS:
                if isinstance(d.get(c), str):
                    try:
                        d[c] = json.loads(d[c])
                    except (json.JSONDecodeError, ValueError):
                        pass
            out.append(d)
        return out

    async def put_session(self, session: dict) -> None:
        pool = await self._p()
        now = datetime.now(timezone.utc)
        await pool.execute(
            """INSERT INTO sessions (session_id, req_id, turns, pending_questions,
                 budget_spent, requester, decisions, created_at, updated_at)
               VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6::jsonb,$7::jsonb,$8,$9)
               ON CONFLICT (session_id) DO UPDATE SET
                 turns=EXCLUDED.turns, pending_questions=EXCLUDED.pending_questions,
                 budget_spent=EXCLUDED.budget_spent, decisions=EXCLUDED.decisions,
                 updated_at=EXCLUDED.updated_at""",
            session["session_id"], session["req_id"],
            json.dumps(session.get("turns", [])),
            json.dumps(session.get("pending_questions", [])),
            session.get("budget_spent", 0),
            json.dumps(session.get("requester", {})),
            json.dumps(session.get("decisions", [])),
            datetime.fromisoformat(session["created_at"]) if session.get("created_at") else now,
            now)

    async def get_session(self, session_id: str) -> dict | None:
        pool = await self._p()
        row = await pool.fetchrow("SELECT * FROM sessions WHERE session_id=$1", session_id)
        return self._session_dict(row) if row else None

    async def list_sessions(self) -> list[dict]:
        pool = await self._p()
        return [self._session_dict(r) for r in await pool.fetch("SELECT * FROM sessions")]

    @staticmethod
    def _session_dict(row) -> dict:
        d = dict(row)
        for c in ("turns", "pending_questions", "requester", "decisions"):
            if isinstance(d.get(c), str):
                d[c] = json.loads(d[c])
            elif d.get(c) is None:
                d[c] = {} if c == "requester" else []
        for c in ("created_at", "updated_at"):
            if d.get(c) is not None and not isinstance(d[c], str):
                d[c] = d[c].isoformat()
        return d

    async def next_seq(self, year: int) -> int:
        pool = await self._p()
        return await pool.fetchval(
            "INSERT INTO seq (year, n) VALUES ($1, 1) "
            "ON CONFLICT (year) DO UPDATE SET n = seq.n + 1 RETURNING n", year)

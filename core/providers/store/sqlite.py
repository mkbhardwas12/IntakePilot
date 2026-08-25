"""SQLite JSON store — the zero-dependency default. Mirrors the Postgres DDL (4.3).

Append-only versioning is enforced by the (req_id, version) primary key:
put_version can only INSERT, never UPDATE.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.models import RequirementObject
from core.providers.store.base import AppendOnlyViolation

LEDGER_TABLES = {
    "edit_diffs": ["req_id", "version", "slot_key", "proposed", "corrected",
                   "provenance", "context_bucket", "ask_embedding", "created_at"],
    "question_ledger": ["req_id", "slot_key", "question", "outcome",
                        "changed_routing", "changed_slots", "created_at"],
    "outcome_ledger": ["req_id", "stage", "verdict", "detail", "created_at"],
    "glossary": ["term", "maps_to", "evidence_count", "last_confirmed"],
    # ADDENDUM-01 knowledge base: discovered backend entities + customizations.
    # Keyed upsert on (system, entity); embedding lives in the vector index.
    "system_kb": ["system", "entity", "label", "schema", "evidence_count",
                  "verified", "last_refreshed"],
    "shares": ["token", "req_id", "created_at", "expires_at", "payload"],
    # MANAS transactional outbox: envelopes committed alongside the domain
    # write; an external relay ships state=pending rows and acknowledges them.
    "manas_outbox": ["outbox_id", "req_id", "event_type", "content_hash",
                     "envelope_json", "state", "reason", "created_at"],
    # Human-accepted process signals mined from production asks — the
    # analyst's taxonomy learning loop (proposals are never auto-applied).
    "analyst_signals": ["process", "signal", "accepted_by", "created_at"],
}

_JSON_COLS = {"proposed", "corrected", "ask_embedding", "detail", "maps_to",
              "schema", "payload"}
_UPSERT_TABLES = {"glossary", "system_kb"}


class SqliteStore:
    name = "sqlite"

    def __init__(self, config: dict | None = None):
        path = (config or {}).get("path", "data/intakepilot.db")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self) -> None:
        cur = self._conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS requirements (
            req_id TEXT, version INTEGER, obj TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (req_id, version))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, req_id TEXT,
            turns TEXT, pending_questions TEXT, budget_spent INTEGER DEFAULT 0,
            requester TEXT, decisions TEXT, created_at TEXT, updated_at TEXT)""")
        for table, cols in LEDGER_TABLES.items():
            if table == "glossary":
                cur.execute("""CREATE TABLE IF NOT EXISTS glossary (
                    term TEXT PRIMARY KEY, maps_to TEXT,
                    evidence_count INTEGER DEFAULT 1, last_confirmed TEXT)""")
            elif table == "system_kb":
                cur.execute("""CREATE TABLE IF NOT EXISTS system_kb (
                    system TEXT, entity TEXT, label TEXT, schema TEXT,
                    evidence_count INTEGER DEFAULT 1,
                    verified INTEGER DEFAULT 0, last_refreshed TEXT,
                    PRIMARY KEY (system, entity))""")
            else:
                col_sql = ", ".join(f"{c} TEXT" for c in cols)
                cur.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, {col_sql})""")
        cur.execute("CREATE TABLE IF NOT EXISTS seq (year INTEGER PRIMARY KEY, n INTEGER)")
        # Migration for databases created before the provenance column existed.
        try:
            cur.execute("ALTER TABLE edit_diffs ADD COLUMN provenance TEXT")
        except sqlite3.OperationalError:
            pass  # column already present
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN decisions TEXT")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    async def put_version(self, obj: RequirementObject) -> None:
        def _():
            with self._lock:
                try:
                    self._conn.execute(
                        "INSERT INTO requirements (req_id, version, obj, created_at) "
                        "VALUES (?,?,?,?)",
                        (obj.req_id, obj.version, obj.model_dump_json(),
                         datetime.now(timezone.utc).isoformat()))
                    self._conn.commit()
                except sqlite3.IntegrityError as exc:
                    raise AppendOnlyViolation(
                        f"{obj.req_id} v{obj.version} already exists") from exc
        await asyncio.to_thread(_)

    async def put_version_with_outbox(self, obj: RequirementObject,
                                      outbox_row: dict) -> None:
        """The transactional outbox, honestly transactional: the requirement
        version and its MANAS outbox row commit or roll back together, so a
        crash can never leave a routed version with no event (or an event
        for a version that never landed)."""
        def _():
            data = dict(outbox_row)
            data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            cols = [c for c in LEDGER_TABLES["manas_outbox"] if c in data]
            vals = [data[c] for c in cols]
            with self._lock:
                try:
                    self._conn.execute(
                        "INSERT INTO requirements (req_id, version, obj, created_at) "
                        "VALUES (?,?,?,?)",
                        (obj.req_id, obj.version, obj.model_dump_json(),
                         datetime.now(timezone.utc).isoformat()))
                    self._conn.execute(
                        f"INSERT INTO manas_outbox ({','.join(cols)}) "
                        f"VALUES ({','.join('?' * len(cols))})", vals)
                    self._conn.commit()
                except sqlite3.IntegrityError as exc:
                    self._conn.rollback()
                    raise AppendOnlyViolation(
                        f"{obj.req_id} v{obj.version} already exists") from exc
                except Exception:
                    self._conn.rollback()
                    raise
        await asyncio.to_thread(_)

    async def latest(self, req_id: str) -> RequirementObject:
        def _():
            row = self._conn.execute(
                "SELECT obj FROM requirements WHERE req_id=? "
                "ORDER BY version DESC LIMIT 1",
                (req_id,)).fetchone()
            if row is None:
                raise KeyError(req_id)
            return RequirementObject.model_validate_json(row["obj"])
        return await asyncio.to_thread(_)

    async def history(self, req_id: str) -> list[RequirementObject]:
        def _():
            rows = self._conn.execute(
                "SELECT obj FROM requirements WHERE req_id=? ORDER BY version",
                (req_id,)).fetchall()
            return [RequirementObject.model_validate_json(r["obj"]) for r in rows]
        return await asyncio.to_thread(_)

    async def version_timestamps(self, req_id: str) -> list[tuple[int, str]]:
        def _():
            rows = self._conn.execute(
                "SELECT version, created_at FROM requirements WHERE req_id=? "
                "ORDER BY version",
                (req_id,)).fetchall()
            return [(r["version"], r["created_at"]) for r in rows]
        return await asyncio.to_thread(_)

    async def log(self, table: str, row: dict) -> None:
        if table not in LEDGER_TABLES:
            raise ValueError(f"unknown ledger table: {table}")

        def _():
            data = dict(row)
            ts_col = {"glossary": "last_confirmed",
                      "system_kb": "last_refreshed"}.get(table, "created_at")
            data.setdefault(ts_col, datetime.now(timezone.utc).isoformat())
            cols = [c for c in LEDGER_TABLES[table] if c in data]
            vals = [json.dumps(data[c]) if c in _JSON_COLS else data[c]
                    for c in cols]
            with self._lock:
                if table in _UPSERT_TABLES:
                    self._conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) "
                        f"VALUES ({','.join('?' * len(cols))})", vals)
                else:
                    self._conn.execute(
                        f"INSERT INTO {table} ({','.join(cols)}) "
                        f"VALUES ({','.join('?' * len(cols))})", vals)
                self._conn.commit()
        await asyncio.to_thread(_)

    async def query_ledger(self, table: str, **filters) -> list[dict]:
        if table not in LEDGER_TABLES:
            raise ValueError(f"unknown ledger table: {table}")

        def _():
            sql, vals = f"SELECT * FROM {table}", []
            if filters:
                sql += " WHERE " + " AND ".join(f"{k}=?" for k in filters)
                vals = list(filters.values())
            out = []
            for r in self._conn.execute(sql, vals).fetchall():
                d = dict(r)
                for c in _JSON_COLS:
                    if d.get(c) is not None and isinstance(d[c], str):
                        try:
                            d[c] = json.loads(d[c])
                        except (json.JSONDecodeError, ValueError):
                            pass
                out.append(d)
            return out
        return await asyncio.to_thread(_)

    async def put_session(self, session: dict) -> None:
        def _():
            with self._lock:
                self._conn.execute(
                    """INSERT OR REPLACE INTO sessions
                       (session_id, req_id, turns, pending_questions, budget_spent,
                        requester, decisions, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (session["session_id"], session["req_id"],
                     json.dumps(session.get("turns", [])),
                     json.dumps(session.get("pending_questions", [])),
                     session.get("budget_spent", 0),
                     json.dumps(session.get("requester", {})),
                     json.dumps(session.get("decisions", [])),
                     session.get("created_at",
                                 datetime.now(timezone.utc).isoformat()),
                     datetime.now(timezone.utc).isoformat()))
                self._conn.commit()
        await asyncio.to_thread(_)

    async def get_session(self, session_id: str) -> dict | None:
        def _():
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id=?",
                (session_id,)).fetchone()
            return self._session_dict(row) if row else None
        return await asyncio.to_thread(_)

    async def list_sessions(self) -> list[dict]:
        def _():
            rows = self._conn.execute("SELECT * FROM sessions").fetchall()
            return [self._session_dict(r) for r in rows]
        return await asyncio.to_thread(_)

    @staticmethod
    def _session_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for c in ("turns", "pending_questions", "requester", "decisions"):
            raw = d.get(c)
            if c == "requester":
                d[c] = json.loads(raw) if raw else {}
            else:
                d[c] = json.loads(raw) if raw else []
        return d

    async def next_seq(self, year: int) -> int:
        def _():
            with self._lock:
                self._conn.execute(
                    "INSERT INTO seq (year, n) VALUES (?, 1) "
                    "ON CONFLICT(year) DO UPDATE SET n = n + 1", (year,))
                self._conn.commit()
                return self._conn.execute(
                    "SELECT n FROM seq WHERE year=?", (year,)).fetchone()["n"]
        return await asyncio.to_thread(_)

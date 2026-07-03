"""pgvector index — optional, used with the Postgres store (requires asyncpg +
the pgvector extension, e.g. the pgvector/pgvector docker image)."""
from __future__ import annotations

import json
import os


class PgVectorIndex:
    name = "pgvector"

    def __init__(self, embedder, config: dict | None = None):
        self._embedder = embedder
        self.dsn = os.environ.get("DATABASE_URL") or (config or {}).get("dsn")
        self.dim = int((config or {}).get("dim", 768))
        if not self.dsn:
            raise RuntimeError("PgVectorIndex requires DATABASE_URL")
        self._pool = None

    async def _p(self):
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self.dsn)
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.execute(f"""CREATE TABLE IF NOT EXISTS vector_index (
                    id TEXT PRIMARY KEY, text TEXT, meta JSONB,
                    embedding VECTOR({self.dim}))""")
        return self._pool

    async def upsert(self, id: str, text: str, meta: dict) -> None:
        pool = await self._p()
        vec = (await self._embedder.embed([text]))[0]
        await pool.execute(
            """INSERT INTO vector_index (id, text, meta, embedding)
               VALUES ($1,$2,$3::jsonb,$4::vector)
               ON CONFLICT (id) DO UPDATE SET text=EXCLUDED.text,
                 meta=EXCLUDED.meta, embedding=EXCLUDED.embedding""",
            id, text, json.dumps(meta), str(vec))

    async def search(self, text: str, k: int = 5, filter: dict | None = None):
        from core.providers.vector.base import Hit
        pool = await self._p()
        vec = (await self._embedder.embed([text]))[0]
        where, vals = "", []
        if filter:
            clauses = []
            for i, (fk, fv) in enumerate(filter.items()):
                clauses.append(f"meta->>'{fk}' = ${i + 3}")
                vals.append(str(fv))
            where = "WHERE " + " AND ".join(clauses)
        rows = await pool.fetch(
            f"""SELECT id, text, meta, 1 - (embedding <=> $1::vector) AS score
                FROM vector_index {where} ORDER BY embedding <=> $1::vector LIMIT $2""",
            str(vec), k, *vals)
        return [Hit(id=r["id"], score=float(r["score"]), text=r["text"],
                    meta=json.loads(r["meta"]) if isinstance(r["meta"], str) else r["meta"])
                for r in rows]

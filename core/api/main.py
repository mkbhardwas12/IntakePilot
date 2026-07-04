"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core.api.context import AppContext
from core.api import (channels, evals, glossary, graph, kb, metrics,
                      requirements, sessions, webhooks)


def create_app(ctx: AppContext | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.ctx.seed_glossary()
        yield

    app = FastAPI(title="IntakePilot", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx or AppContext()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health(request: Request):
        c = request.app.state.ctx
        return {"status": "ok", "provider": c.llm.name, "store": c.store.name}

    @app.get("/api/schema")
    async def schema(request: Request, type: str = "default"):
        c = request.app.state.ctx
        chosen = c.schema_for(type)
        return {"request_type": type if type in c.schemas else "default",
                "available_types": sorted(c.schemas),
                "slots": {
                    k: {"required": s.required, "askable": s.askable, "label": s.label,
                        "ask_hint": s.ask_hint, "default": s.default,
                        "default_reason": s.default_reason}
                    for k, s in chosen.slots.items()}}

    app.include_router(sessions.router)
    app.include_router(requirements.router)
    app.include_router(metrics.router)
    app.include_router(kb.router)
    app.include_router(evals.router)
    app.include_router(glossary.router)
    app.include_router(webhooks.router)
    app.include_router(channels.router)
    app.include_router(graph.router)
    return app


app = create_app()

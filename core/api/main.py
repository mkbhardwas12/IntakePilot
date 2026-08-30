"""FastAPI application factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core.api.context import AppContext
from core.api.middleware import RateLimitMiddleware, RequestLogMiddleware
from core.api import (analyst, channels, evals, export, glossary, graph, kb,
                      metrics, requirements, sessions, share, triage, webhooks)
from core.api import attachments


def _cors_origins() -> list[str]:
    raw = os.environ.get("INTAKEPILOT_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


def create_app(ctx: AppContext | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.ctx.seed_glossary()
        yield

    app = FastAPI(title="IntakePilot", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx or AppContext()
    # Last-added middleware runs first on the request path.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestLogMiddleware)

    @app.get("/health")
    async def health(request: Request):
        c = request.app.state.ctx
        # `model` makes bring-your-own-AI verifiable at a glance: set the env
        # vars, restart, curl /health — you should see YOUR model here.
        llm = c.llm
        model = (getattr(llm, "model", None)
                 or getattr(getattr(llm, "primary", None), "model", None))
        return {"status": "ok", "provider": llm.name, "model": model,
                "store": c.store.name}

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
    app.include_router(attachments.router)
    app.include_router(share.router)
    app.include_router(triage.router)
    app.include_router(metrics.router)
    app.include_router(kb.router)
    app.include_router(evals.router)
    app.include_router(glossary.router)
    app.include_router(webhooks.router)
    app.include_router(channels.router)
    app.include_router(graph.router)
    app.include_router(analyst.router)
    app.include_router(export.router)
    return app


app = create_app()

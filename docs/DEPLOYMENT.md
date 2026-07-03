# Deploying IntakePilot

IntakePilot is provider-agnostic by design: the same codebase runs on a laptop with zero external dependencies, on an on-premises host (including fully air-gapped), or in any cloud. You pick where the LLM, the database, and the vector index live — nothing in the business logic changes.

## Choose your path

| Scenario | LLM | Store/Vector | How |
|---|---|---|---|
| Laptop demo (zero deps) | mock | SQLite + local index | `make dev` |
| Full stack, dev | Ollama in Docker | Postgres/pgvector | `docker compose up` |
| On-prem production | Ollama (`--profile local-llm`) or internal endpoint | Postgres/pgvector | `docker compose -f docker-compose.prod.yml up -d` |
| Air-gapped | Ollama with pre-loaded model | Postgres/pgvector | prod compose, images + model transferred offline |
| Cloud VM (EC2 / Azure VM / GCE / Hetzner…) | any | Postgres/pgvector | same prod compose on the VM |
| Managed cloud services | Azure OpenAI / Bedrock gateway / hosted vLLM via `openai_compat` | managed Postgres (`DATABASE_URL`) | api + web containers on ECS/App Service/Cloud Run |

## 1. Local development

```bash
make dev            # installs, then runs api :8000 (bound to 127.0.0.1) + web :3000
```

## 2. Dev stack in Docker

```bash
cd deploy && docker compose up
docker compose exec ollama ollama pull llama3.1   # first start only
```

Vite dev server on :3000 proxies to the api container (`INTAKEPILOT_API_URL=http://api:8000`). Note: the api image runs as UID 10001; on a Linux host, `chown -R 10001 examples/demo-repo` once so routed tickets can be written to the bind mount (macOS/Windows Docker Desktop needs nothing).

## 3. Production (on-prem or any cloud VM)

```bash
cd deploy
cp .env.example .env         # set POSTGRES_PASSWORD, pick the LLM
docker compose -f docker-compose.prod.yml up -d --build
# with the bundled local LLM:
docker compose -f docker-compose.prod.yml --profile local-llm up -d --build
docker compose -f docker-compose.prod.yml exec ollama ollama pull llama3.1
```

What you get versus the dev stack: the web tier is a real build served by nginx (SSE-aware proxy config in `deploy/nginx.conf`), the API runs non-root with healthchecks and restart policies, Postgres takes its password from `.env` and is not exposed on the host, and tickets go to a named volume.

**Bring your own LLM.** Any OpenAI-compatible server works — vLLM, LiteLLM, llama.cpp, TGI, Azure OpenAI, or an internal gateway. In `.env`:

```
INTAKEPILOT_LLM=openai_compat
OPENAI_BASE_URL=http://your-gateway:8001/v1
OPENAI_MODEL=qwen3-32b
OPENAI_API_KEY=            # if your gateway requires one
```

**Managed Postgres.** Remove the `db` service and set `DATABASE_URL=postgresql://user:pass@host:5432/db` on the api service (setting `DATABASE_URL` switches the store to Postgres automatically; keep `INTAKEPILOT_VECTOR=pgvector` and enable the pgvector extension on the instance).

## 4. Air-gapped

On a connected machine: `docker compose -f docker-compose.prod.yml --profile local-llm build`, then `docker save` the api/web images plus `pgvector/pgvector:pg16` and `ollama/ollama`, and pull the model once so the `ollama` named volume contains it (or download a GGUF and `ollama create` inside the network). Transfer the image tarballs and the Ollama model directory, `docker load` on the target, and run the same compose file. No step of the pipeline calls out: extraction, gates, routing, learning, and enrichment all run against your local model and database.

## 5. Kubernetes / container platforms

`deploy/Dockerfile.api` and `deploy/Dockerfile.web.prod` produce standard stateless images (state lives in Postgres), so they run as-is on ECS, Cloud Run, App Service, or any K8s cluster — service names `api`/`db`/`ollama` become your service discovery names (`OLLAMA_BASE_URL`, `DATABASE_URL`, and nginx's `proxy_pass http://api:8000` are the only places they appear). First-class manifests/Helm are on the roadmap.

## Configuration reference

Everything is selectable in `intakepilot.yaml` and overridable by environment:

| Variable | Values | Notes |
|---|---|---|
| `INTAKEPILOT_LLM` | `mock` \| `ollama` \| `openai_compat` | mock is deterministic/offline |
| `INTAKEPILOT_STORE` | `sqlite` \| `postgres` | `DATABASE_URL` implies postgres |
| `INTAKEPILOT_VECTOR` | `local` \| `pgvector` | |
| `INTAKEPILOT_CONNECTOR` | `fixture` \| your own | ADDENDUM-01 system connector |
| `DATABASE_URL` | DSN | switches store to Postgres |
| `OLLAMA_BASE_URL` | URL | default `http://localhost:11434` |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY` | | any OpenAI-compatible server |
| `INTAKEPILOT_API_URL` | URL | web dev-server proxy target only |

## Security checklist before exposing beyond localhost

IntakePilot has **no built-in authentication yet** (see PROJECT-REVIEW.md). Front the web port with your SSO/reverse proxy (oauth2-proxy, Authelia, an ALB/App Gateway with OIDC) or keep it on an internal network; terminate TLS at that proxy. Keep Postgres unexposed (the prod compose already does). Back up the `pgdata` volume. Rotate `POSTGRES_PASSWORD` via `.env` — it is deliberately not baked into any image.

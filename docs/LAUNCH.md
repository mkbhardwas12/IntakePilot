# Launch notes — overnight-viral IntakePilot

## Angle (HN / Launch / LinkedIn)

**The LLM never controls intake — here's the gap ladder live.**

Most “AI for requirements” products are chat wrappers. IntakePilot’s
orchestrator is deterministic Python: extract → infer → retrieve → ask
(budgeted). The new **X-ray** Decision Rail streams those real decisions
over SSE. After confirm you get a **shareable cinematic replay** with an
OG card — see → try → share → see.

## Demo script (30 seconds)

1. Open `/intake`
2. Click **Play the 23-second demo**
3. Watch slots + X-ray decisions light up
4. Confirm → gates → ticket
5. **Share this intake** → paste the `/r/{token}` link (unfurls OG card)

## Seed cold-start replays

With the API up on mock LLM:

```bash
python -m scripts.seed_shares
```

Pin the three printed `/r/…` URLs in the README / landing post.

## Public demo host

```bash
cp deploy/.env.demo.example deploy/.env.demo
# set INTAKEPILOT_ADMIN_TOKEN + INTAKEPILOT_WEBHOOK_SECRET + DEMO_ORIGIN
docker compose -f deploy/docker-compose.demo.yml --env-file deploy/.env.demo up --build
python -m scripts.seed_shares   # against the public API URL
```

Go/no-go: `python scripts/ops_check.py` must stay green.

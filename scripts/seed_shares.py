#!/usr/bin/env python3
"""Seed three shareable demo replays (finance / bug / data) for a cold public demo.

Usage (API must be running with mock LLM):
  python -m scripts.seed_shares
  # prints /r/{token} URLs
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("INTAKEPILOT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

SCENARIOS = [
    {
        "name": "finance",
        "requester": {"name": "Demo User", "dept": "Finance Ops", "role": "Analyst"},
        "message": (
            "our monthly vendor spend report takes 3 days to compile by hand "
            "from SAP and spreadsheets — finance needs it by month-end"
        ),
    },
    {
        "name": "bug",
        "requester": {"name": "Demo User", "dept": "Customer Support", "role": "Lead"},
        "message": (
            "customers see a blank screen when opening the invoice PDF export "
            "in Chrome since Tuesday — happens for about 30% of EU accounts"
        ),
    },
    {
        "name": "data",
        "requester": {"name": "Demo User", "dept": "Revenue Ops", "role": "Manager"},
        "message": (
            "need a weekly export of open opportunities by region for the "
            "board pack — currently someone copy-pastes from Salesforce"
        ),
    },
]


def _json(method: str, path: str, body: dict | None = None,
          headers: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _run_one(scenario: dict) -> str:
    sess = _json("POST", "/api/sessions", {"requester": scenario["requester"]})
    sid, req_id = sess["session_id"], sess["req_id"]
    turn = _json("POST", f"/api/sessions/{sid}/turns?stream=false",
                 {"message": scenario["message"]})
    # Answer any pending questions with first option / placeholder.
    questions = turn.get("questions") or []
    answers = []
    for q in questions:
        opts = q.get("options") or []
        answers.append({
            "question_id": q["id"],
            "slot_key": q["slot_key"],
            "value": opts[0] if opts else "this quarter",
        })
    if answers:
        turn = _json("POST", f"/api/sessions/{sid}/turns?stream=false",
                     {"message": " · ".join(str(a["value"]) for a in answers),
                      "answers": answers})
    # Keep answering until confirm unlocked or no questions (cap 4).
    for _ in range(4):
        if turn.get("confirm_unlocked"):
            break
        qs = turn.get("questions") or []
        if not qs:
            break
        answers = [{
            "question_id": q["id"], "slot_key": q["slot_key"],
            "value": (q.get("options") or ["ok"])[0],
        } for q in qs]
        turn = _json("POST", f"/api/sessions/{sid}/turns?stream=false",
                     {"message": " · ".join(str(a["value"]) for a in answers),
                      "answers": answers})

    confirm = _json("POST", f"/api/requirements/{req_id}/confirm",
                    {"edits": {}, "confirmed_by": "Demo User"},
                    headers={"X-Session-Id": sid})
    decisions = []
    try:
        detail = _json("GET", f"/api/sessions/{sid}")
        decisions = detail.get("decisions") or []
    except Exception:
        pass
    share = _json("POST", f"/api/requirements/{req_id}/share",
                  {"decisions": decisions,
                   "gates": confirm.get("gates"),
                   "routing": confirm.get("routing"),
                   "ticket": confirm.get("ticket"),
                   "collisions": confirm.get("collisions")},
                  headers={"X-Session-Id": sid})
    return share["url"]


def main() -> int:
    print(f"Seeding shares against {BASE} …", file=sys.stderr)
    urls = []
    for sc in SCENARIOS:
        try:
            url = _run_one(sc)
            print(f"{sc['name']}: {url}")
            urls.append(url)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()[:300]
            print(f"{sc['name']}: FAILED {exc.code} {body}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"{sc['name']}: FAILED {exc}", file=sys.stderr)
            return 1
    print(json.dumps({"seeded": urls}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

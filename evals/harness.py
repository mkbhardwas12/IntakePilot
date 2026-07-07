"""Golden-set eval harness (Milestone 7).

Runs every scenario in evals/golden/ end-to-end through the real HTTP API —
session, budgeted turn loop, confirmation, gates, routing — against whichever
LLM provider the environment selects (mock by default; set INTAKEPILOT_LLM to
benchmark Ollama or any OpenAI-compatible endpoint). Two kinds of checks:

* invariants — question budget, the askable:false rule, no 5xx. These must
  hold for EVERY scenario with EVERY model; the pytest wrapper hard-fails
  on any violation.
* gold checks — slot provenance/values, request-type classification, routing
  queue, readiness. Scored, not asserted: they are the model-quality
  benchmark ("is this local model good enough?").

Usage:
    python -m evals.harness            # table
    python -m evals.harness --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
import yaml

from core.api.context import AppContext
from core.api.main import create_app
from core.config import load_config, load_slot_schema
from core.learning.replay import matches

GOLDEN_DIR = Path(__file__).parent / "golden"
FALLBACK_ANSWER = "n/a - to be refined with the team"
MAX_TURNS = 5


def _memory_config():
    cfg = load_config()   # llm stays env-selected: benchmark any provider
    cfg.store_provider = "sqlite"
    cfg.store = {"sqlite": {"path": ":memory:"}}
    cfg.vector_provider = "local"
    cfg.vector = {"local": {"path": ":memory:"}}
    cfg.target_provider = "local"
    cfg.demo_repo = str(Path(tempfile.mkdtemp(prefix="ip-goldens-")) / "repo")
    return cfg


def load_scenarios() -> list[dict]:
    return [yaml.safe_load(p.read_text())
            for p in sorted(GOLDEN_DIR.glob("scenario_*.yaml"))]


def _unaskable(request_type: str) -> set[str]:
    schema = load_slot_schema(request_type=request_type)
    return {k for k, s in schema.slots.items() if not s.askable}


async def run_scenario(scenario: dict) -> dict:
    ctx = AppContext(_memory_config())
    app = create_app(ctx)
    result = {"id": scenario["id"], "strict": scenario.get("strict", True),
              "invariants": {}, "checks": {}, "errors": []}
    asked_total, per_turn_max, asked_keys = 0, 0, set()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://eval") as client:
        await ctx.seed_glossary()
        r = await client.post("/api/sessions",
                              json={"requester": scenario["requester"]})
        if r.status_code >= 400:
            result["errors"].append(f"session: {r.status_code}")
            return result
        sid, req_id = r.json()["session_id"], r.json()["req_id"]

        message, answers = scenario["ask"], []
        draft, confirm_unlocked = None, False
        scripted = scenario.get("scripted_answers") or {}
        for _ in range(MAX_TURNS):
            r = await client.post(f"/api/sessions/{sid}/turns?stream=false",
                                  json={"message": message, "answers": answers})
            if r.status_code >= 500:
                result["errors"].append(f"turn: {r.status_code}")
                return result
            turn = r.json()
            draft = turn["draft"]
            questions = turn.get("questions") or []
            asked_total += len(questions)
            per_turn_max = max(per_turn_max, len(questions))
            asked_keys |= {q["slot_key"] for q in questions}
            confirm_unlocked = bool(turn.get("confirm_unlocked"))
            if not questions:
                break
            answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                        "value": scripted.get(q["slot_key"], FALLBACK_ANSWER)}
                       for q in questions]
            message = ""

        confirm = None
        r = await client.post(f"/api/requirements/{req_id}/confirm",
                              json={"edits": {}, "confirmed_by": "Golden User"},
                              headers={"X-Session-Id": sid})
        if r.status_code >= 500:
            result["errors"].append(f"confirm: {r.status_code}")
        elif r.status_code < 400:
            confirm = r.json()

    # ---- invariants (model-independent; must always hold) -----------------
    request_type = (draft or {}).get("request_type", "default")
    result["invariants"] = {
        "budget_total": asked_total <= 7,
        "budget_per_turn": per_turn_max <= 3,
        "askable_false_never_asked": not (asked_keys & _unaskable(request_type)),
        "no_server_error": not result["errors"],
    }
    result["questions_asked"] = asked_total

    # ---- gold checks (the model-quality benchmark) -------------------------
    gold = scenario.get("gold") or {}
    checks: dict[str, bool] = {}
    if scenario.get("strict", True) and draft:
        if "request_type" in gold:
            expected = gold["request_type"]
            checks["request_type"] = (request_type == expected
                                      or expected == "default")
        for key, want in (gold.get("slots") or {}).items():
            slot = (draft.get("slots") or {}).get(key) or {}
            ok = True
            if "provenance" in want:
                ok &= slot.get("provenance") == want["provenance"]
            if "value" in want:
                ok &= matches(slot.get("value"), want["value"])
            if "contains" in want:
                ok &= want["contains"].lower() in str(slot.get("value", "")).lower()
            checks[f"slot:{key}"] = bool(ok)
        if "questions_asked_max" in gold:
            checks["questions_within_gold"] = asked_total <= gold["questions_asked_max"]
        if "readiness_at_confirm_min" in gold:
            checks["readiness"] = (draft.get("readiness_score") or 0) >= \
                gold["readiness_at_confirm_min"]
        routing = (confirm or {}).get("routing") or {}
        if "routing_queue" in gold and routing.get("queue"):
            # gated-before-routing is judged by the gate checks, not here
            checks["routing"] = routing["queue"] == gold["routing_queue"]
        checks["confirmed_and_routed"] = bool(
            confirm and confirm.get("draft", {}).get("status") in ("routed", "gated"))
        # only demand a clean route when the ask names a resolvable system —
        # a systems-less requirement being parked as GATED is correct behavior
        if "affected_systems" in (gold.get("slots") or {}):
            checks["routed_clean"] = bool(
                confirm and confirm.get("draft", {}).get("status") == "routed")
    result["checks"] = checks
    return result


async def run_all() -> dict:
    scenarios = load_scenarios()
    results = [await run_scenario(s) for s in scenarios]

    inv_fail = [r["id"] for r in results
                if not all(r["invariants"].values())]
    strict = [r for r in results if r["strict"]]
    slot_checks = [(k, v) for r in strict for k, v in r["checks"].items()
                   if k.startswith("slot:")]
    routing = [r["checks"]["routing"] for r in strict if "routing" in r["checks"]]
    rtypes = [r["checks"]["request_type"] for r in strict
              if "request_type" in r["checks"]]
    routed = [r["checks"].get("routed_clean", False) for r in strict]

    cfg = load_config()
    ctx_probe = AppContext(_memory_config())
    llm = ctx_probe.llm
    model = getattr(llm, "model", None) or getattr(
        getattr(llm, "primary", None), "model", None)

    def rate(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "provider": llm.name, "model": model,
        "scenarios": len(results), "strict_scenarios": len(strict),
        "invariant_failures": inv_fail,
        "slot_accuracy": rate([v for _, v in slot_checks]),
        "slot_checks": len(slot_checks),
        "routing_accuracy": rate(routing),
        "request_type_accuracy": rate(rtypes),
        "routed_clean_rate": rate(routed),
        "mean_questions": rate([r["questions_asked"] for r in results]),
        "results": results,
    }


def main() -> None:  # pragma: no cover — thin CLI
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="write full report to this path")
    args = parser.parse_args()
    report = asyncio.run(run_all())
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str))
    failing = [r for r in report["results"]
               if not all(r["invariants"].values())
               or (r["strict"] and not all(r["checks"].values()))]
    print(f"model: {report['provider']} ({report['model']})  "
          f"scenarios: {report['scenarios']}")
    print(f"invariants: {'OK' if not report['invariant_failures'] else 'FAIL ' + str(report['invariant_failures'])}")
    print(f"slot accuracy:        {report['slot_accuracy']} ({report['slot_checks']} checks)")
    print(f"routing accuracy:     {report['routing_accuracy']}")
    print(f"request-type accuracy: {report['request_type_accuracy']}")
    print(f"routed clean rate:    {report['routed_clean_rate']}")
    print(f"mean questions/intake: {report['mean_questions']}")
    for r in failing:
        misses = ([k for k, v in r["invariants"].items() if not v]
                  + [k for k, v in r["checks"].items() if not v])
        print(f"  {r['id']}: {', '.join(misses)}")
    sys.exit(1 if report["invariant_failures"] else 0)


if __name__ == "__main__":  # pragma: no cover
    main()

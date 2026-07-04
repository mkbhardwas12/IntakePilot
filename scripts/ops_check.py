"""Operational-readiness probe: multi-scenario integration sweep against a
running IntakePilot API on :8000. Prints PASS/FAIL per check; exits 1 on any FAIL."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("INTAKEPILOT_BASE_URL", "http://localhost:8000")
c = httpx.Client(base_url=BASE, timeout=60)
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))


def new_session(dept: str = "Finance Ops"):
    r = c.post("/api/sessions", json={"requester": {"name": "OpsCheck", "dept": dept, "role": "Analyst"}})
    d = r.json()
    return d["session_id"], d["req_id"]


def turn(sid: str, msg: str = "", answers=None, revisions=None) -> httpx.Response:
    body: dict = {"message": msg}
    if answers:
        body["answers"] = answers
    if revisions:
        body["revisions"] = revisions
    return c.post(f"/api/sessions/{sid}/turns", params={"stream": "false"}, json=body)


def answer_all(sid: str, turn_json: dict, value_for: dict | None = None) -> dict:
    qs = turn_json.get("questions", [])
    if not qs:
        return turn_json
    answers = []
    for q in qs:
        v = (value_for or {}).get(q["slot_key"], "skip")
        answers.append({"question_id": q["id"], "slot_key": q["slot_key"], "value": v})
    return turn(sid, "", answers=answers).json()


# ---------- S3: request-type matrix ----------
sid, rid = new_session()
d = turn(sid, "the nightly sync to Salesforce crashes with an error since tuesday").json()
check("S3a bug ask -> bug_report", d["draft"]["request_type"] == "bug_report",
      d["draft"]["request_type"])

sid, rid = new_session()
d = turn(sid, "we need a list of open invoices by region exported weekly").json()
check("S3b data ask -> data_request", d["draft"]["request_type"] == "data_request",
      d["draft"]["request_type"])

sid, rid = new_session()
d = turn(sid, "please build a portal to sync new-hire accounts").json()
check("S3c capability ask -> new_capability", d["draft"]["request_type"] == "new_capability",
      d["draft"]["request_type"])

sid, rid = new_session()
d = turn(sid, "hello there").json()
check("S3d gibberish -> default + asks questions",
      d["draft"]["request_type"] == "default" and len(d["questions"]) > 0,
      f"type={d['draft']['request_type']} q={len(d['questions'])}")

# ---------- S4: budget exhaustion via skips ----------
sid, rid = new_session()
d = turn(sid, "hello there").json()
for _ in range(8):  # more turns than the budget allows
    if not d.get("questions"):
        break
    d = answer_all(sid, d)  # all "skip"
budget = d["draft"]["question_budget"]
check("S4a budget hard cap respected", budget["spent"] <= budget["max"],
      f"{budget['spent']}/{budget['max']}")
check("S4b questioning terminates", not d.get("questions"), f"left={len(d.get('questions', []))}")
# After questioning ends, no required slot may remain open: either a schema
# default became a stated assumption, or precedent/retrieval filled it (the
# index learns across runs, so a warm system may legitimately have 0 assumptions).
slots = d["draft"]["slots"]
open_required = [k for k in ("data_sensitivity",)
                 if not slots.get(k) or slots[k]["value"] in (None, "", [])]
check("S4c no required slot left silently open",
      not open_required and (d["draft"]["assumptions"]
                             or any(s.get("provenance") == "retrieved" for s in slots.values())),
      f"assumptions={d['draft']['assumptions']} open={open_required}")

# ---------- S5: duplicate -> gated -> attach ----------
# Nonce keeps re-runs of this probe from colliding with earlier runs' data
# (the dedup gate would otherwise catch our own previous "novel" ask).
import uuid
NONCE = uuid.uuid4().hex[:6]
DUP_ASK = (f"reconciling the {NONCE} pallet counts takes 4 hours to complete "
           "by hand every shift in SAP")
VALUES = {"urgency": "this month",
          "success_criteria": f"{NONCE} pallet counts reconcile in under 15 minutes",
          "business_outcome": f"automate {NONCE} pallet count reconciliation in SAP"}

sidA, ridA = new_session()
d = turn(sidA, DUP_ASK).json()
for _ in range(4):
    if not d.get("questions"):
        break
    d = answer_all(sidA, d, VALUES)
rA = c.post(f"/api/requirements/{ridA}/confirm", json={"edits": {}},
            headers={"X-Session-Id": sidA})
routedA = rA.json()
check("S5a novel ask routes clean", rA.status_code == 200
      and routedA["draft"]["status"] == "routed", routedA["draft"]["status"])

sidB, ridB = new_session()
d = turn(sidB, DUP_ASK).json()
for _ in range(4):
    if not d.get("questions"):
        break
    d = answer_all(sidB, d, VALUES)
rB = c.post(f"/api/requirements/{ridB}/confirm", json={"edits": {}},
            headers={"X-Session-Id": sidB})
gatedB = rB.json()
gate4 = next(g for g in gatedB["gates"] if g["gate"] == 4)
check("S5b exact duplicate gated by gate 4",
      gatedB["draft"]["status"] == "gated" and not gate4["passed"],
      f"status={gatedB['draft']['status']} reason={str(gate4.get('reason'))[:60]}")
dup_of = (gate4.get("meta") or {}).get("duplicate_of")
check("S5c gate 4 names the duplicate", dup_of == ridA, f"duplicate_of={dup_of}")
rAtt = c.post(f"/api/requirements/{ridB}/attach",
              json={"target_req_id": dup_of or ridA},
              headers={"X-Session-Id": sidB})
check("S5d attach closes duplicate as done", rAtt.status_code == 200
      and rAtt.json()["draft"]["status"] == "done",
      f"{rAtt.status_code}")
rAtt2 = c.post(f"/api/requirements/{ridB}/attach", json={"target_req_id": ridA},
               headers={"X-Session-Id": sidB})
check("S5e re-attach rejected (409)", rAtt2.status_code == 409, str(rAtt2.status_code))

# ---------- S6: security & malformed input ----------
r = c.get(f"/api/requirements/{ridA}")
check("S6a no session header -> 401", r.status_code == 401, str(r.status_code))
r = c.get(f"/api/requirements/{ridA}", headers={"X-Session-Id": "bogus"})
check("S6b wrong session -> 404 (anti-enumeration)", r.status_code == 404, str(r.status_code))
r = turn("nonexistent-session", "hi")
check("S6c unknown session turn -> 404", r.status_code == 404, str(r.status_code))

sid, rid = new_session()
turn(sid, "our expense audit takes 2 days to check by hand")
d = turn(sid, "", answers=[{"question_id": "forged-id", "slot_key": "data_sensitivity",
                            "value": "public"}]).json()
sens = d["draft"]["slots"].get("data_sensitivity")
check("S6d forged question_id ignored",
      sens is None or sens.get("value") != "public" or sens.get("provenance") != "answered",
      str(sens and sens.get("provenance")))

d = turn(sid, "", revisions={"backend_context": "hacked", "not_a_slot": "x"}).json()
check("S6e backend_context/unknown revision ignored", d.get("revised", 0) == 0,
      f"revised={d.get('revised')}")

r = c.post("/api/sessions", json={"requester": {"name": 123}})
check("S6f malformed requester -> 4xx (not 500)", 400 <= r.status_code < 500,
      str(r.status_code))

r = turn(sid, "x" * 20000)
check("S6g 20k-char message survives", r.status_code == 200, str(r.status_code))

# ---------- S7: confirm edits, double confirm, hostile strings ----------
sid, rid = new_session()
d = turn(sid, f"<script>alert(1)</script> our {NONCE} quarterly tax filing takes 5 days "
              "to prepare by hand").json()
for _ in range(4):
    if not d.get("questions"):
        break
    d = answer_all(sid, d, {"urgency": "this quarter",
                            "success_criteria": f"{NONCE} filing prepared in under 4 hours"})
r = c.post(f"/api/requirements/{rid}/confirm",
           json={"edits": {"scope_boundaries": "exclude <img src=x onerror=alert(2)> legacy years"}},
           headers={"X-Session-Id": sid})
confirmed = r.json()
check("S7a hostile-string confirm doesn't 500", r.status_code == 200, str(r.status_code))
sb = confirmed["draft"]["slots"].get("scope_boundaries", {})
check("S7b edit captured with edited provenance", sb.get("provenance") == "edited",
      str(sb.get("provenance")))
first_status = confirmed["draft"]["status"]
r2 = c.post(f"/api/requirements/{rid}/confirm", json={"edits": {}},
            headers={"X-Session-Id": sid})
if first_status == "routed":
    check("S7c confirm after routed -> 409", r2.status_code == 409, str(r2.status_code))
else:
    check("S7c gated re-confirm allowed (fix-and-retry path)", r2.status_code == 200,
          f"first={first_status} second={r2.status_code}")
# deterministic 409: ridA routed in S5a (reroute in S8g runs later)
r3 = c.post(f"/api/requirements/{ridA}/confirm", json={"edits": {}},
            headers={"X-Session-Id": sidA})
check("S7d confirm of a routed requirement -> 409", r3.status_code == 409, str(r3.status_code))

# ---------- S8: ops endpoints ----------
r = c.get("/health")
check("S8a health", r.status_code == 200 and r.json()["status"] == "ok", str(r.status_code))
m = c.get("/api/metrics").json()
t = m["totals"]
check("S8b metrics coherent (intakes>=confirmed>=routed)",
      t["intakes"] >= t["confirmed"] >= t["routed"],
      f"{t['intakes']}/{t['confirmed']}/{t['routed']}")
check("S8c edit ledger grew", t["edits"] > 0, str(t["edits"]))
r = c.get("/api/kb")
check("S8d kb endpoint", r.status_code == 200, str(r.status_code))
r = c.get("/api/evals/replay", params={"limit": 5})
check("S8e evals replay", r.status_code == 200 and "accuracy" in r.json(), str(r.status_code))
r = c.get("/api/glossary/proposals")
check("S8f glossary proposals", r.status_code == 200, str(r.status_code))
current_queue = routedA["routing"]["queue"]
target_queue = "integrations" if current_queue != "integrations" else "data-platform"
r = c.post(f"/api/requirements/{ridA}/reroute", json={"queue": target_queue})
check("S8g reroute feedback", r.status_code == 200 and r.json().get("changed") is True,
      f"{r.status_code} {current_queue}->{target_queue}")
r = c.get("/api/schema", params={"type": "bug_report"})
check("S8h schema fork endpoint", r.status_code == 200
      and "current_behavior" in r.json()["slots"], str(r.status_code))

# ---------- report ----------
fails = [x for x in results if not x[1]]
width = max(len(n) for n, _, _ in results)
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
sys.exit(1 if fails else 0)

"""The 40-scenario golden set (Milestone 7) runs on every test pass.

Invariants must hold for every scenario — they are product guarantees, not
model quality. The accuracy floors are calibrated against the deterministic
mock (1.0 across the board at authoring time); a small slack absorbs benign
future schema/prompt shifts without letting a real regression through.
"""
from __future__ import annotations

import pytest

from evals.harness import load_scenarios, run_all


def test_golden_set_is_complete():
    scenarios = load_scenarios()
    assert len(scenarios) == 40
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == 40
    # the set must keep covering every request-type fork and the hard cases
    non_strict = [s for s in scenarios if not s.get("strict", True)]
    assert len(non_strict) >= 3          # vague + non-English asks stay in


@pytest.mark.anyio
async def test_golden_invariants_and_floors():
    report = await run_all()
    assert report["invariant_failures"] == [], report["invariant_failures"]
    assert report["slot_accuracy"] >= 0.95, report
    assert report["routing_accuracy"] >= 0.95, report
    assert report["request_type_accuracy"] >= 0.95, report
    assert report["mean_questions"] <= 4.0, report

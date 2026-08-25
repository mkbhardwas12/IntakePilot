"""IntakePilot MANAS outbox — the two Demand contracts, and nothing invented.

The drift this replaces: an exploratory branch emitting io.manas.demand.asked / .corrected /
.observed, none of which MANAS defines.
"""
from __future__ import annotations

import json

import pytest

from core.export.manas_outbox import (
    Emitted,
    OutboxBinding,
    OutboxContractError,
    Rejected,
    commitment,
    emit_outcome_adjudicated,
    emit_requirement_versioned,
    load_pack,
    outbox_enabled,
)

PEPPER = b"tenant-pepper-0123456789abcdef"
INTENT = "Add a rush-order flag to sales orders for expedited fulfilment."
CRITERIA = "Flag visible on VA01 and reportable in the nightly extract."


def binding(**over):
    kw = dict(tenant_id="t-intake", source_instance_id="intake-prod-1",
              source_binding="sha256:" + "a" * 64)
    kw.update(over)
    return OutboxBinding(**kw)


def requirement(b=None, **over):
    kw = dict(requirement_id="IPR-2026-000014", requirement_version=3, change_id="CHG-000014",
              request_type="enhancement", intent_text=INTENT, acceptance_criteria_text=CRITERIA,
              pepper=PEPPER, registered_at="2026-08-20T09:00:00.000Z")
    kw.update(over)
    return emit_requirement_versioned(b or binding(), **kw)


def outcome(b=None, **over):
    kw = dict(outcome_id="OC-000014", deployment_ref="deployment:basis-prod-1:PR1:100:DPL-9",
              deployment_source_binding="sha256:" + "b" * 64,
              requirement_id="IPR-2026-000014", requirement_version=3,
              requirement_source_binding="sha256:" + "a" * 64, change_id="CHG-000014",
              change_source_binding="sha256:" + "c" * 64, verdict="achieved",
              adjudicated_by_role="product_owner",
              outcome_evidence_hash="sha256:" + "d" * 64, receipt_text="PO confirmed on 2026-08-30",
              pepper=PEPPER, adjudicated_at="2026-08-30T09:00:00.000Z")
    kw.update(over)
    return emit_outcome_adjudicated(b or binding(), **kw)


# ------------------------------------------------------- only real contracts

def test_only_the_two_contracts_intakepilot_owns_are_exported():
    pack = load_pack()
    assert set(pack["schemas"]) == {
        "io.manas.demand.requirement.versioned.v2",
        "io.manas.demand.outcome.adjudicated.v1",
    }


def test_the_invented_names_from_the_exploratory_branch_are_absent():
    pack = load_pack()
    for invented in ("io.manas.demand.asked", "io.manas.demand.corrected",
                     "io.manas.demand.observed"):
        assert invented not in pack["schemas"]
        assert invented not in (pack.get("wire") or {})


def test_the_pack_carries_the_wire_specification():
    wire = load_pack()["wire"]["io.manas.demand.requirement.versioned.v2"]
    assert wire["source"] == "//manas/demand/intakepilot"
    assert wire["subject_field"] == "requirement_ref"
    assert wire["partition_field"] == "change_ref"


def test_both_pack_digests_are_checked(tmp_path):
    pack = json.loads(json.dumps(load_pack()))
    pack["wire"]["io.manas.demand.requirement.versioned.v2"]["source"] = "//manas/demand/rogue"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(pack))
    with pytest.raises(OutboxContractError, match="wire digest"):
        load_pack(bad)


# ------------------------------------------------------- commitments, not narrative

def test_the_business_narrative_never_crosses():
    r = requirement()
    assert isinstance(r, Emitted)
    blob = json.dumps(r.envelope)
    for phrase in ("rush-order", "expedited", "VA01", "nightly extract"):
        assert phrase not in blob
    assert r.envelope["data"]["intent_commitment"].startswith("hmac-sha256:")


def test_a_commitment_is_stable_and_pepper_bound():
    assert commitment(INTENT, PEPPER) == commitment(INTENT, PEPPER)
    assert commitment(INTENT, PEPPER) != commitment(INTENT, b"another-pepper-0123456789ab")
    assert commitment(INTENT, PEPPER) != commitment(CRITERIA, PEPPER)


def test_a_weak_or_missing_pepper_is_refused():
    for bad in (b"", b"tooshort"):
        with pytest.raises(OutboxContractError, match="pepper"):
            commitment(INTENT, bad)


def test_empty_intent_is_refused():
    assert isinstance(requirement(intent_text=""), Rejected)


# ------------------------------------------------------- envelope built from the pack

def test_the_envelope_matches_the_wire_specification():
    r = requirement()
    e = r.envelope
    assert e["source"] == "//manas/demand/intakepilot"
    assert e["lobe"] == "demand"
    assert e["subject"] == "req:intake-prod-1:IPR-2026-000014@v3"
    assert e["partitionkey"] == "t-intake#change:intake-prod-1:CHG-000014"
    assert e["entityrefs"] == "req:intake-prod-1:IPR-2026-000014@v3,change:intake-prod-1:CHG-000014"
    prov = json.loads(e["provenance"])
    assert prov["agent"] == "svc:demand/intakepilot@manas-export-v2"
    assert prov["activity"] == "export.outbox"
    assert prov["used"] == [e["data"]["source_binding"]]


def test_an_outcome_binds_deployment_requirement_and_change():
    r = outcome()
    assert isinstance(r, Emitted)
    refs = r.envelope["entityrefs"].split(",")
    assert refs[0].startswith("outcome:")
    assert refs[1].startswith("deployment:")
    assert refs[2].startswith("req:")
    assert refs[3].startswith("change:")
    assert json.loads(r.envelope["provenance"])["activity"] == "adjudicate.outcome"


def test_status_is_pinned_by_the_contract():
    assert requirement().envelope["data"]["status"] == "ready_for_build"


# ------------------------------------------------------- refusals

def test_an_out_of_contract_verdict_is_rejected():
    assert isinstance(outcome(verdict="probably_fine"), Rejected)


def test_only_a_human_can_adjudicate_an_outcome():
    """adjudication_method is const in the contract, so it is not a caller-supplied field."""
    import inspect

    from core.export.manas_outbox import emit_outcome_adjudicated as fn

    assert "adjudication_method" not in inspect.signature(fn).parameters
    assert outcome().envelope["data"]["adjudication_method"] == "human"


def test_only_a_business_or_product_owner_may_adjudicate():
    assert isinstance(outcome(adjudicated_by_role="developer"), Rejected)
    assert isinstance(outcome(adjudicated_by_role="business_owner"), Emitted)


def test_a_version_below_one_is_rejected():
    assert isinstance(requirement(requirement_version=0), Rejected)


def test_an_incomplete_binding_is_refused():
    for bad in ({"tenant_id": ""}, {"source_binding": "nope"},
                {"source_instance_id": "has spaces"}):
        assert isinstance(requirement(binding(**bad)), Rejected)


def test_clock_skew_and_bad_timestamps_are_rejected():
    assert isinstance(requirement(registered_at="2026-08-20 09:00:00"), Rejected)
    assert isinstance(
        requirement(registered_at="2026-08-25T09:00:00.000Z",
                    recorded_at="2026-08-20T09:00:00.000Z"), Rejected)


def test_a_rejection_never_echoes_the_narrative():
    r = requirement(request_type="not a valid type!!")
    assert isinstance(r, Rejected)
    assert "rush-order" not in r.reason


def test_identifiers_are_not_mistaken_for_phone_numbers():
    """IPR-2026-000014 is a requirement id. A naive phone heuristic rejects it."""
    assert isinstance(requirement(), Emitted)
    assert isinstance(requirement(requirement_id="REQ-555-8675309"), Emitted)


def test_a_real_phone_number_is_still_caught():
    from core.export.manas_outbox.emitter import _pii_kind

    assert _pii_kind("call +1 555 867 5309 now") == "phone"
    assert _pii_kind("a.person@example.com") == "email"


# ------------------------------------------------------- housekeeping

def test_default_off():
    assert outbox_enabled({}) is False
    assert outbox_enabled({"MANAS_OUTBOX_ENABLED": "true"}) is True


def test_ids_are_stable_for_the_same_fact():
    assert requirement().outbox_id == requirement().outbox_id
    assert requirement().outbox_id != requirement(requirement_version=4).outbox_id


def test_integral_floats_canonicalize_as_integers():
    from core.export.manas_outbox.emitter import canonical_bytes

    assert canonical_bytes({"c": 1.0}) == b'{"c":1}'
    assert canonical_bytes({"c": 0.8}) == b'{"c":0.8}'


def test_the_outbox_item_is_pending_and_serializable():
    item = requirement().as_item()
    assert item["state"] == "pending"
    assert json.loads(item["envelope_json"])["type"] == "io.manas.demand.requirement.versioned.v2"

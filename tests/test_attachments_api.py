"""The attachment preview API — upload, session binding, and the demo page."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.models import Provenance, Slot

from tests.conftest import make_obj, memory_config, seed
from tests.xlsx_factory import build_xlsx

CLEAN = build_xlsx({"Data": [["Customer", "Qty"], ["C-1", 5], ["C-2", 7]]})


@pytest.fixture
async def api():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        yield client, ctx


async def test_stateless_preview_with_fields(api):
    client, _ = api
    res = await client.post("/api/attachments/preview",
                            params={"filename": "orders.xlsx",
                                    "fields": "customer, quantity"},
                            content=CLEAN)
    assert res.status_code == 200
    rep = res.json()
    assert rep["verdict"] == "ready"
    assert rep["fitness"]["coverage_ratio"] == 1.0
    assert rep["filename"] == "orders.xlsx"


async def test_a_broken_file_reports_instead_of_erroring(api):
    client, _ = api
    res = await client.post("/api/attachments/preview", content=b"not,a,workbook")
    assert res.status_code == 200
    rep = res.json()
    assert rep["verdict"] == "unreadable"
    assert "re-save" in rep["summary"].lower()


async def test_an_empty_body_is_a_422(api):
    client, _ = api
    res = await client.post("/api/attachments/preview", content=b"")
    assert res.status_code == 422


async def test_requirement_bound_preview_requires_the_owning_session(api):
    client, ctx = api
    obj = make_obj("IPR-2026-000042", "vendor report by plant")
    await seed(ctx.store, obj)

    res = await client.post("/api/attachments/for/IPR-2026-000042", content=CLEAN)
    assert res.status_code == 401
    res = await client.post("/api/attachments/for/IPR-2026-000042", content=CLEAN,
                            headers={"X-Session-Id": "someone-else"})
    assert res.status_code == 404


async def test_requirement_bound_preview_uses_the_requirements_own_fields(api):
    client, ctx = api
    obj = make_obj("IPR-2026-000042", "vendor report by plant")
    obj.slots["data_fields"] = Slot(value="customer, quantity, plant",
                                    provenance=Provenance.ANSWERED, confidence=1.0)
    await seed(ctx.store, obj)

    res = await client.post("/api/attachments/for/IPR-2026-000042", content=CLEAN,
                            params={"filename": "orders.xlsx"},
                            headers={"X-Session-Id": "s-test"})
    assert res.status_code == 200
    rep = res.json()
    assert rep["req_id"] == "IPR-2026-000042"
    missing = [m["requested"] for m in rep["fitness"]["missing"]]
    assert missing == ["plant"]
    assert any(f["code"] == "requested_field_missing" for f in rep["findings"])


async def test_a_large_upload_passes_with_no_size_cap(api):
    client, _ = api
    big = build_xlsx({"Data": [["Customer", "Qty"]] + [[f"C-{i}", i] for i in range(5000)]})
    res = await client.post("/api/attachments/preview",
                            params={"fields": "customer, quantity"}, content=big)
    assert res.status_code == 200
    rep = res.json()
    assert rep["verdict"] == "ready"
    assert rep["sheets"][0]["data_rows"] == 5000


async def test_the_demo_page_serves(api):
    client, _ = api
    res = await client.get("/api/attachments/demo")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Drop an .xlsx" in res.text


# --------------------------------------------------- the in-chat session endpoint
# (the paperclip path: POST /api/sessions/{id}/attachments — report embedded in
# the transcript so a restored session re-renders the check)

async def test_session_upload_is_checked_and_persisted(api):
    client, ctx = api
    resp = await client.post("/api/sessions", json={})
    sid = resp.json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/attachments?filename=orders.xlsx",
                             content=CLEAN)
    assert resp.status_code == 200
    rep = resp.json()
    assert rep["filename"] == "orders.xlsx" and rep["verdict"] == "ready"

    resp = await client.get(f"/api/sessions/{sid}")
    assert [a["filename"] for a in resp.json()["attachments"]] == ["orders.xlsx"]


async def test_session_upload_unreadable_is_a_report_not_an_error(api):
    client, _ = api
    resp = await client.post("/api/sessions", json={})
    sid = resp.json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/attachments?filename=notes.pdf",
                             content=b"%PDF-1.7 not a workbook")
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "unreadable"


async def test_session_upload_guards(api):
    client, _ = api
    resp = await client.post("/api/sessions", json={})
    sid = resp.json()["session_id"]
    assert (await client.post(f"/api/sessions/{sid}/attachments",
                              content=b"")).status_code == 422
    assert (await client.post("/api/sessions/nope/attachments",
                              content=b"x")).status_code == 404

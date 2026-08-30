"""Attachment preview API — validate a spreadsheet the moment it is offered, not days later.

Three routes:

* ``POST /api/attachments/preview`` — stateless. Raw file bytes in the body (no multipart, so the
  zero-external-dependency run path keeps holding: python-multipart is not required). Optional
  ``fields`` query parameter supplies the needed columns when no requirement exists yet.
* ``POST /api/attachments/for/{req_id}`` — the product path. Session-bound exactly like the other
  requirement routes (``X-Session-Id``, wrong pairs return 404 so IDs cannot be enumerated), and the
  fitness check reads the requirement's own ``data_fields`` slot, so the file is judged against what
  this requester actually asked for.
* ``GET /api/attachments/demo`` — a self-contained drag-and-drop page for trying the feature in a
  browser. Serving HTML from the API follows the existing ``share.py`` precedent. This page is a
  development preview, not the final intake UI.

Uploads are held in memory only for the duration of the request; nothing is stored. There is no size
cap and no character cap anywhere on this path — the analyzer streams.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from core.attachments import analyze_attachment

logger = logging.getLogger("intakepilot.attachments")

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


def _ctx(request: Request):
    return request.app.state.ctx


async def _authorize(ctx, request: Request, req_id: str) -> None:
    """Same contract as core/api/requirements.py: session-bound, 404 over 403, no enumeration."""
    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        raise HTTPException(401, "X-Session-Id header required")
    session = await ctx.store.get_session(session_id)
    if session is None or session.get("req_id") != req_id:
        raise HTTPException(404, "requirement not found")


@router.post("/preview")
async def preview(request: Request, filename: str = "attachment.xlsx",
                  fields: str | None = None):
    """Validate an uploaded workbook. Body = the raw .xlsx bytes."""
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty upload — send the file bytes as the request body")
    slots = {"data_fields": fields} if fields else None
    report = analyze_attachment(io.BytesIO(body), filename=filename, slots=slots)
    logger.info("attachment preview: %s -> %s (%d finding(s))",
                filename, report.verdict, len(report.findings))
    return report.as_dict()


@router.post("/for/{req_id}")
async def preview_for_requirement(req_id: str, request: Request,
                                  filename: str = "attachment.xlsx"):
    """Validate a workbook against a specific requirement's own stated data fields."""
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    try:
        obj = await ctx.store.latest(req_id)
    except KeyError:
        raise HTTPException(404, "requirement not found")
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty upload — send the file bytes as the request body")
    report = analyze_attachment(io.BytesIO(body), filename=filename, slots=obj.slots)
    logger.info("attachment preview for %s: %s -> %s",
                req_id, filename, report.verdict)
    payload = report.as_dict()
    payload["req_id"] = req_id
    return payload


_DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Attachment preview — IntakePilot (dev)</title>
<style>
:root { color-scheme: light dark;
  --bg:#f6f7f9; --card:#ffffff; --ink:#1c2430; --mut:#5b6674; --line:#dde2e9;
  --ok:#0e7a4b; --okbg:#e2f4ea; --warn:#8a5a00; --warnbg:#fdf1d7;
  --bad:#a52333; --badbg:#fbe4e7; --info:#33526e; --infobg:#e7eef5; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#12161c; --card:#1a2029; --ink:#e6ebf1; --mut:#93a0af; --line:#2a3340;
  --ok:#4cc38a; --okbg:#12301f; --warn:#e2b23e; --warnbg:#33270c;
  --bad:#ef7d8b; --badbg:#3a1319; --info:#8fb6d8; --infobg:#16232e; } }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:860px; margin:0 auto; padding:32px 20px 64px }
h1 { font-size:20px; margin:0 0 4px } .sub { color:var(--mut); margin:0 0 24px }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:20px; margin-bottom:16px }
#drop { border:2px dashed var(--line); border-radius:10px; padding:36px; text-align:center;
  color:var(--mut); cursor:pointer; transition:border-color .15s }
#drop.hot { border-color:var(--info); color:var(--ink) }
label { display:block; font-size:13px; color:var(--mut); margin:14px 0 4px }
input[type=text] { width:100%; padding:8px 10px; border:1px solid var(--line);
  border-radius:8px; background:var(--bg); color:var(--ink); font:inherit }
.pill { display:inline-block; padding:2px 10px; border-radius:99px; font-size:13px;
  font-weight:600 }
.v-ready { background:var(--okbg); color:var(--ok) }
.v-needs_fixes { background:var(--warnbg); color:var(--warn) }
.v-unusable,.v-unreadable { background:var(--badbg); color:var(--bad) }
.f { display:flex; gap:10px; padding:10px 0; border-top:1px solid var(--line) }
.f:first-of-type { border-top:none }
.sev { flex:0 0 78px; font-size:11px; font-weight:700; letter-spacing:.04em;
  text-transform:uppercase; padding-top:2px }
.sev.blocking { color:var(--bad) } .sev.warning { color:var(--warn) }
.sev.info { color:var(--info) }
.ref { font-family:ui-monospace,Menlo,monospace; font-size:12px; background:var(--infobg);
  color:var(--info); border-radius:5px; padding:1px 6px; margin-left:6px }
.fix { color:var(--mut); font-size:13.5px; margin-top:2px }
#summary { margin:10px 0 0; color:var(--mut) }
.hide { display:none }
</style>
</head>
<body><main>
<h1>Attachment preview</h1>
<p class="sub">Drop an Excel file to check it before it goes anywhere. Development preview —
the same check runs inside the intake flow via <code>/api/attachments/for/{req_id}</code>.</p>

<div class="card">
  <div id="drop">Drop an .xlsx here, or click to choose a file.<br>
    <span style="font-size:12px">No size limit. Nothing is stored.</span></div>
  <input id="file" type="file" accept=".xlsx,.xlsm" class="hide">
  <label for="fields">Fields this request needs (optional, comma-separated — normally taken
    from the requirement)</label>
  <input id="fields" type="text" placeholder="customer number, material, quantity">
</div>

<div id="out" class="card hide">
  <div><span id="verdict" class="pill"></span> <strong id="fname"></strong></div>
  <p id="summary"></p>
  <div id="findings"></div>
</div>

<script>
const drop = document.getElementById('drop'), file = document.getElementById('file');
drop.onclick = () => file.click();
['dragover','dragenter'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add('hot'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove('hot'); }));
drop.addEventListener('drop', ev => { if (ev.dataTransfer.files[0]) go(ev.dataTransfer.files[0]); });
file.onchange = () => { if (file.files[0]) go(file.files[0]); };

async function go(f) {
  drop.textContent = 'Checking ' + f.name + '…';
  const fields = document.getElementById('fields').value.trim();
  const qs = new URLSearchParams({filename: f.name});
  if (fields) qs.set('fields', fields);
  let rep;
  try {
    const res = await fetch('/api/attachments/preview?' + qs, {method:'POST', body: f});
    rep = await res.json();
  } catch (e) { drop.textContent = 'Request failed: ' + e; return; }
  drop.innerHTML = 'Drop another file, or click to choose.<br><span style="font-size:12px">No size limit. Nothing is stored.</span>';
  render(rep);
}

function render(rep) {
  document.getElementById('out').classList.remove('hide');
  const v = document.getElementById('verdict');
  v.textContent = (rep.verdict || '').replace('_',' ');
  v.className = 'pill v-' + rep.verdict;
  document.getElementById('fname').textContent = rep.filename || '';
  document.getElementById('summary').textContent = rep.summary || '';
  const box = document.getElementById('findings'); box.innerHTML = '';
  (rep.findings || []).forEach(f => {
    const row = document.createElement('div'); row.className = 'f';
    const sev = document.createElement('div');
    sev.className = 'sev ' + f.severity;
    sev.textContent = f.severity === 'blocking' ? 'must fix' :
                      f.severity === 'warning' ? 'should fix' : 'note';
    const body = document.createElement('div');
    const msg = document.createElement('div');
    msg.textContent = f.message;
    if (f.ref) { const r = document.createElement('span'); r.className='ref';
                 r.textContent = f.ref; msg.appendChild(r); }
    const fix = document.createElement('div'); fix.className = 'fix';
    fix.textContent = f.fix || '';
    body.appendChild(msg); body.appendChild(fix);
    row.appendChild(sev); row.appendChild(body); box.appendChild(row);
  });
  if (!(rep.findings || []).length) {
    const ok = document.createElement('div'); ok.className='f';
    ok.textContent = 'No problems found.'; box.appendChild(ok);
  }
}
</script>
</main></body></html>"""


@router.get("/demo", response_class=HTMLResponse)
async def demo_page() -> HTMLResponse:
    """Self-contained try-it page. Development preview, not the final intake UI."""
    return HTMLResponse(_DEMO_PAGE)

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cloneFromTriage, getTriage, rerouteRequirement } from "../api";
import type { TriageItem } from "../api";
import { useToast } from "../toast";

const QUEUES = ["data-platform", "integrations", "analytics", "platform", "security"];

export function TriagePage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [items, setItems] = useState<TriageItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => {
    setFailed(false);
    getTriage()
      .then((r) => setItems(r.items))
      .catch((err: unknown) => {
        setFailed(true);
        toast(`Triage unavailable: ${err instanceof Error ? err.message : String(err)}`);
      });
  };

  useEffect(() => {
    load();
  }, []);

  const reroute = async (reqId: string, queue: string) => {
    setBusy(reqId);
    try {
      await rerouteRequirement(reqId, queue);
      toast(`Rerouted ${reqId} → ${queue}`);
      load();
    } catch (err: unknown) {
      toast(`Reroute failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  const clone = async (reqId: string) => {
    setBusy(reqId);
    try {
      const s = await cloneFromTriage(reqId);
      try { sessionStorage.setItem("intakepilot-session", s.session_id); } catch { /* ignore */ }
      toast("Cloned into a new draft");
      navigate("/intake");
      window.location.reload();
    } catch (err: unknown) {
      toast(`Clone failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  };

  if (failed) {
    return (
      <div className="metrics-page">
        <h1 className="page-title">Triage</h1>
        <div className="empty-note">
          Triage is admin-gated. Leave <code>INTAKEPILOT_ADMIN_TOKEN</code> unset for open demo mode, or send a Bearer token.
        </div>
        <button className="ghost-btn" type="button" onClick={load}>Retry</button>
      </div>
    );
  }

  if (!items) {
    return (
      <div className="metrics-page">
        <h1 className="page-title">Triage</h1>
        <div className="empty-note">Loading queue…</div>
      </div>
    );
  }

  return (
    <div className="metrics-page">
      <h1 className="page-title">Triage</h1>
      <p className="page-sub">Routed and gated requirements — reroute with one click.</p>
      {items.length === 0 ? (
        <div className="empty-note">No routed or gated intakes yet — run one from Intake.</div>
      ) : (
        <div className="triage-list">
          {items.map((item) => (
            <article key={item.req_id} className="triage-card">
              <div className="triage-card-head">
                <span className="req-id">{item.req_id}</span>
                <span className={`status-chip status-${item.status}`}>{item.status}</span>
                {item.queue && <span className="triage-queue">{item.queue}</span>}
              </div>
              <h3>{item.title_hint || "Untitled"}</h3>
              <p>{item.ask_verbatim}</p>
              <div className="triage-actions">
                <label>
                  Reroute
                  <select
                    disabled={busy === item.req_id || item.status !== "routed"}
                    defaultValue=""
                    onChange={(e) => {
                      const q = e.target.value;
                      if (q) void reroute(item.req_id, q);
                      e.target.value = "";
                    }}
                  >
                    <option value="">Choose queue…</option>
                    {QUEUES.map((q) => (
                      <option key={q} value={q}>{q}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="ghost-btn small"
                  disabled={busy === item.req_id}
                  onClick={() => void clone(item.req_id)}
                >
                  Clone &amp; modify
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

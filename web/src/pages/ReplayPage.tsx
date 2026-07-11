import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { cloneFromShare, getShare } from "../api";
import type { SharePayload } from "../api";
import { percent } from "../format";
import { useToast } from "../toast";
import { DecisionRail } from "../components/DecisionRail";

export function ReplayPage() {
  const { token } = useParams<{ token: string }>();
  const toast = useToast();
  const navigate = useNavigate();
  const [payload, setPayload] = useState<SharePayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [step, setStep] = useState(0);
  const [cloning, setCloning] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getShare(token)
      .then((p) => {
        if (!cancelled) setPayload(p);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!payload) return;
    setStep(0);
    const timers = [
      window.setTimeout(() => setStep(1), 400),
      window.setTimeout(() => setStep(2), 1100),
      window.setTimeout(() => setStep(3), 1800),
      window.setTimeout(() => setStep(4), 2600),
    ];
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [payload]);

  const clone = async () => {
    if (!token) return;
    setCloning(true);
    try {
      const s = await cloneFromShare(token);
      try { sessionStorage.setItem("intakepilot-session", s.session_id); } catch { /* ignore */ }
      toast("Cloned — continue on Intake");
      navigate("/intake");
      window.location.reload();
    } catch (err: unknown) {
      toast(`Clone failed: ${err instanceof Error ? err.message : String(err)}`);
      setCloning(false);
    }
  };

  if (failed) {
    return (
      <div className="replay-page">
        <h1>Share not found</h1>
        <p>This replay link is missing or expired.</p>
        <Link to="/intake">Start a new intake</Link>
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="replay-page">
        <div className="empty-note">Loading replay…</div>
      </div>
    );
  }

  return (
    <div className="replay-page">
      <header className="replay-hero">
        <p className="replay-kicker">X-ray replay</p>
        <h1 className="replay-title">{payload.title_hint || payload.req_id}</h1>
        <p className="replay-ask">{payload.ask_verbatim}</p>
        <div className="replay-meta">
          <span>{payload.req_id}</span>
          <span>{payload.status}</span>
          {payload.queue && <span>→ {payload.queue}</span>}
          <span>ready {payload.readiness_score}</span>
        </div>
      </header>

      {step >= 1 && (
        <section className="replay-section fade-in">
          <h2>Ask</h2>
          <blockquote>{payload.ask_verbatim}</blockquote>
        </section>
      )}

      {step >= 2 && payload.decisions?.length > 0 && (
        <section className="replay-section fade-in">
          <h2>Gap ladder</h2>
          <DecisionRail decisions={payload.decisions} />
        </section>
      )}

      {step >= 3 && payload.gates && (
        <section className="replay-section fade-in">
          <h2>Gates</h2>
          <div className="gate-pipeline">
            {payload.gates.map((g) => (
              <div key={g.gate} className={`gate-node ${g.passed ? "passed" : "failed"}`}>
                <span className="gate-num">{g.gate}</span>
                <span className="gate-name">{g.name}</span>
                <span className="gate-state">{g.passed ? "✓" : "✕"}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {step >= 4 && (
        <section className="replay-section fade-in">
          <h2>Outcome</h2>
          {payload.routing && (
            <div className="routing-card">
              <div className="card-kicker">Routed to</div>
              <div className="routing-queue">{payload.routing.queue}</div>
              <div className="routing-confidence">{percent(payload.routing.confidence)} confidence</div>
              <p className="routing-explanation">{payload.routing.explanation}</p>
            </div>
          )}
          {payload.ticket && (
            <div className="ticket-card" style={{ marginTop: 12 }}>
              <div className="card-kicker">Ticket · {payload.ticket.ref}</div>
              <div className="ticket-title">{payload.ticket.title}</div>
            </div>
          )}
          {(payload.collisions?.length ?? 0) > 0 && (
            <ul className="collision-list">
              {payload.collisions!.map((c) => (
                <li key={c.req_id}>
                  {c.req_id} — {c.shared.map((s) => s.replace(/^system:/, "")).join(", ")}
                </li>
              ))}
            </ul>
          )}
          <div className="share-finale">
            <button className="confirm-btn big" disabled={cloning} onClick={() => void clone()}>
              {cloning ? "Cloning…" : "Start from this intake"}
            </button>
            <Link className="ghost-btn" to="/intake">Try IntakePilot</Link>
          </div>
        </section>
      )}
    </div>
  );
}

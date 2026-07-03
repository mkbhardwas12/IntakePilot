import { useEffect, useState } from "react";
import type { ConfirmResponse } from "../types";
import { percent } from "../format";
import { SystemContextCard, backendContextOf } from "./SystemContext";

const GATE_STEP_MS = 550;

export function PostConfirm({ result, onRestart }: { result: ConfirmResponse; onRestart: () => void }) {
  const gates = result.gates;
  const [litCount, setLitCount] = useState(0);
  const allLit = litCount >= gates.length;

  useEffect(() => {
    setLitCount(0);
    if (gates.length === 0) return;
    const timers: number[] = [];
    for (let i = 1; i <= gates.length; i++) {
      timers.push(window.setTimeout(() => setLitCount(i), i * GATE_STEP_MS));
    }
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [gates.length]);

  const failures = gates.filter((g) => !g.passed);
  const backendContext = backendContextOf(result.draft.slots["backend_context"]);

  return (
    <div className="post-confirm">
      <div className="post-head">
        <h2>Requirement confirmed</h2>
        <span className="overlay-sub">
          {result.draft.req_id} · v{result.draft.version} ·{" "}
          <span className={`status-chip status-${result.draft.status}`}>{result.draft.status.replace(/_/g, " ")}</span>
        </span>
      </div>

      <div className="gate-pipeline">
        {gates.map((g, i) => {
          const lit = i < litCount;
          return (
            <div key={g.gate} className="gate-node-wrap">
              <div className={`gate-node ${lit ? (g.passed ? "passed" : "failed") : "pending"}`}>
                <span className="gate-num">{g.gate}</span>
                <span className="gate-name">{g.name}</span>
                <span className="gate-state">{lit ? (g.passed ? "✓" : "✕") : "·"}</span>
              </div>
              {i < gates.length - 1 && <div className={`gate-link ${lit ? "lit" : ""}`} />}
            </div>
          );
        })}
      </div>

      {allLit && failures.length > 0 && (
        <div className="gate-failures fade-in">
          {failures.map((g) => (
            <div key={g.gate} className="gate-failure">
              <span className="gate-failure-title">
                Gate {g.gate} — {g.name}
              </span>
              {g.reason && <span className="gate-failure-reason">{g.reason}</span>}
              {g.suggestion && <span className="gate-failure-suggestion">Suggestion: {g.suggestion}</span>}
            </div>
          ))}
        </div>
      )}

      {allLit && (
        <div className="post-cards fade-in">
          <div className="routing-card">
            <div className="card-kicker">Routed to</div>
            <div className="routing-queue">{result.routing.queue}</div>
            <div className="routing-confidence">{percent(result.routing.confidence)} confidence</div>
            <p className="routing-explanation">{result.routing.explanation}</p>
            {result.routing.alternatives.length > 0 && (
              <div className="routing-alts">
                <div className="card-kicker">Alternatives</div>
                {result.routing.alternatives.map((alt) => (
                  <div key={alt.queue} className="routing-alt-row">
                    <span>{alt.queue}</span>
                    <span className="tnum">{percent(alt.score)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {result.ticket ? (
            <TicketCard ticket={result.ticket} />
          ) : (
            <div className="ticket-card">
              <div className="card-kicker">Ticket</div>
              <div className="ticket-none">No ticket was created.</div>
            </div>
          )}
        </div>
      )}

      {allLit && backendContext && (
        <div className="post-syscontext fade-in">
          <SystemContextCard context={backendContext} source={result.draft.slots["backend_context"]?.source} />
        </div>
      )}

      {allLit && (
        <button className="confirm-btn big fade-in" onClick={onRestart}>
          Start new intake
        </button>
      )}
    </div>
  );
}

function TicketCard({ ticket }: { ticket: NonNullable<ConfirmResponse["ticket"]> }) {
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className="ticket-card">
      <div className="card-kicker">
        Ticket · {ticket.target} · {ticket.ref}
      </div>
      <div className="ticket-title">{ticket.title}</div>
      <div className="ticket-path">{ticket.path}</div>
      <button className="ghost-btn small" onClick={() => setShowRaw((s) => !s)}>
        {showRaw ? "Hide raw" : "View raw"}
      </button>
      {showRaw && <pre className="ticket-raw">{ticket.path}</pre>}
    </div>
  );
}

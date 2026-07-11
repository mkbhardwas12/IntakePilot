import { useEffect, useMemo, useState } from "react";
import { attachRequirement, createShare, getGraph } from "../api";
import type { ConfirmResponse, DecisionEvent } from "../types";
import { percent } from "../format";
import { useToast } from "../toast";
import { SystemContextCard, backendContextOf } from "./SystemContext";
import { DecisionRail } from "./DecisionRail";

const GATE_STEP_MS = 550;

export function PostConfirm({
  result, sessionId, decisions = [], onRestart
}: {
  result: ConfirmResponse;
  sessionId: string;
  decisions?: DecisionEvent[];
  onRestart: () => void;
}) {
  const toast = useToast();
  const gates = result.gates;
  const [litCount, setLitCount] = useState(0);
  const [attachedTo, setAttachedTo] = useState<string | null>(null);
  const [attaching, setAttaching] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [graph, setGraph] = useState<{
    nodes: { id: string }[];
    edges: { source: string; target: string; shared?: string[] }[];
  } | null>(null);
  const allLit = litCount >= gates.length;

  const duplicateOf = gates.find((g) => g.gate === 4 && !g.passed)?.meta
    ?.duplicate_of as string | undefined;

  const attach = async () => {
    if (!duplicateOf) return;
    setAttaching(true);
    try {
      const resp = await attachRequirement(result.draft.req_id, sessionId, duplicateOf);
      setAttachedTo(resp.attached_to);
    } catch (err: unknown) {
      toast(`Attach failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAttaching(false);
    }
  };

  const share = async () => {
    setSharing(true);
    try {
      const resp = await createShare(result.draft.req_id, sessionId, {
        decisions,
        gates: result.gates,
        routing: result.routing,
        ticket: result.ticket,
        collisions: result.collisions,
      });
      const absolute = `${window.location.origin}${resp.url}`;
      setShareUrl(absolute);
      try {
        await navigator.clipboard.writeText(absolute);
        toast("Share link copied");
      } catch {
        toast("Share link ready");
      }
    } catch (err: unknown) {
      toast(`Share failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSharing(false);
    }
  };

  useEffect(() => {
    setLitCount(0);
    if (gates.length === 0) return;
    const timers: number[] = [];
    for (let i = 1; i <= gates.length; i++) {
      timers.push(window.setTimeout(() => setLitCount(i), i * GATE_STEP_MS));
    }
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [gates.length]);

  useEffect(() => {
    if (!allLit) return;
    getGraph()
      .then((g) => setGraph(g as typeof graph))
      .catch(() => { /* graph is optional polish */ });
  }, [allLit]);

  const failures = gates.filter((g) => !g.passed);
  const backendContext = backendContextOf(result.draft.slots["backend_context"]);
  const cod = result.draft.slots["cost_of_delay"];

  const collisionFocus = useMemo(() => {
    const ids = new Set((result.collisions ?? []).map((c) => c.req_id));
    ids.add(result.draft.req_id);
    return ids;
  }, [result.collisions, result.draft.req_id]);

  return (
    <div className="post-confirm">
      <div className="post-head">
        <h2>Requirement confirmed</h2>
        <span className="overlay-sub">
          {result.draft.req_id} · v{result.draft.version} ·{" "}
          <span className={`status-chip status-${result.draft.status}`}>
            {result.draft.status.replace(/_/g, " ")}
          </span>
        </span>
      </div>

      <div className="gate-pipeline" role="list" aria-label="Quality gates">
        {gates.map((g, i) => {
          const lit = i < litCount;
          return (
            <div key={g.gate} className="gate-node-wrap" role="listitem">
              <div className={`gate-node ${lit ? (g.passed ? "passed" : "failed") : "pending"}`}>
                <span className="gate-num">{g.gate}</span>
                <span className="gate-name">{g.name}</span>
                <span className="gate-state" aria-label={lit ? (g.passed ? "passed" : "failed") : "pending"}>
                  {lit ? (g.passed ? "✓" : "✕") : "·"}
                </span>
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
          {duplicateOf && result.draft.status === "gated" && !attachedTo && (
            <button className="confirm-btn" disabled={attaching} onClick={() => void attach()}>
              {attaching ? "Attaching…" : `Attach to ${duplicateOf} (mark as duplicate)`}
            </button>
          )}
          {attachedTo && (
            <div className="gate-failure">
              <span className="gate-failure-title">Attached to {attachedTo} ✓</span>
              <span className="gate-failure-suggestion">
                This intake is closed as a duplicate; the existing requirement carries the work.
              </span>
            </div>
          )}
        </div>
      )}

      {allLit && (
        <div className="post-climax fade-in">
          <div className="post-cards">
            <div className="routing-card">
              <div className="card-kicker">Routed to</div>
              <div className="routing-queue">{result.routing.queue}</div>
              <div className="routing-confidence">{percent(result.routing.confidence)} confidence</div>
              <p className="routing-explanation">{result.routing.explanation}</p>
              {cod?.value != null && (
                <div className="cod-line">
                  Cost of delay: <strong>{String(typeof cod.value === "object" ? JSON.stringify(cod.value) : cod.value)}</strong>
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

          {(result.collisions?.length ?? 0) > 0 && (
            <CollisionConstellation
              selfId={result.draft.req_id}
              collisions={result.collisions!}
              graph={graph}
              focus={collisionFocus}
            />
          )}

          {decisions.length > 0 && (
            <div className="post-xray">
              <DecisionRail decisions={decisions} />
            </div>
          )}

          {backendContext && (
            <div className="post-syscontext">
              <SystemContextCard context={backendContext} source={result.draft.slots["backend_context"]?.source} />
            </div>
          )}

          <div className="share-finale">
            <button className="confirm-btn big" disabled={sharing} onClick={() => void share()}>
              {sharing ? "Creating link…" : shareUrl ? "Copy share link again" : "Share this intake"}
            </button>
            {shareUrl && (
              <a className="share-url" href={shareUrl} target="_blank" rel="noreferrer">
                {shareUrl}
              </a>
            )}
            <button className="ghost-btn" onClick={onRestart}>
              Start new intake
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TicketCard({ ticket }: { ticket: NonNullable<ConfirmResponse["ticket"]> }) {
  return (
    <div className="ticket-card">
      <div className="card-kicker">
        Ticket · {ticket.target} · {ticket.ref}
      </div>
      <div className="ticket-title">{ticket.title}</div>
      <div className="ticket-path" title={ticket.path}>{ticket.path}</div>
      {ticket.path.startsWith("http") ? (
        <a className="ghost-btn small" href={ticket.path} target="_blank" rel="noreferrer">
          Open ticket
        </a>
      ) : (
        <span className="ticket-hint">Saved under {ticket.target}</span>
      )}
    </div>
  );
}

function CollisionConstellation({
  selfId, collisions, graph, focus
}: {
  selfId: string;
  collisions: NonNullable<ConfirmResponse["collisions"]>;
  graph: { nodes: { id: string }[]; edges: { source: string; target: string; shared?: string[] }[] } | null;
  focus: Set<string>;
}) {
  const nodes = useMemo(() => {
    const ids = [selfId, ...collisions.map((c) => c.req_id)];
    return ids.map((id, i) => {
      const angle = (Math.PI * 2 * i) / Math.max(ids.length, 1) - Math.PI / 2;
      const r = ids.length === 1 ? 0 : 70;
      return { id, x: 120 + Math.cos(angle) * r, y: 100 + Math.sin(angle) * r };
    });
  }, [selfId, collisions]);

  const edges = collisions.map((c) => ({
    from: selfId,
    to: c.req_id,
    label: c.shared.map((s) => s.replace(/^system:/, "")).slice(0, 2).join(", "),
  }));

  return (
    <div className="collision-card fade-in">
      <div className="card-kicker">Collision constellation</div>
      <p className="collision-sub">Open work touching the same backend entities — not duplicates.</p>
      <svg className="collision-svg" viewBox="0 0 240 200" role="img" aria-label="Impact graph">
        {edges.map((e) => {
          const a = nodes.find((n) => n.id === e.from);
          const b = nodes.find((n) => n.id === e.to);
          if (!a || !b) return null;
          return (
            <g key={`${e.from}-${e.to}`}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="collision-edge" />
            </g>
          );
        })}
        {nodes.map((n) => (
          <g key={n.id}>
            <circle
              cx={n.x}
              cy={n.y}
              r={n.id === selfId ? 18 : 14}
              className={n.id === selfId ? "collision-node self" : "collision-node"}
            />
            <text x={n.x} y={n.y + 32} textAnchor="middle" className="collision-label">
              {n.id.replace(/^IPR-\d+-0*/, "IPR-")}
            </text>
          </g>
        ))}
      </svg>
      <ul className="collision-list">
        {collisions.map((c) => (
          <li key={c.req_id}>
            <strong>{c.req_id}</strong>
            {c.queue ? ` · ${c.queue}` : ""} — {c.shared.map((s) => s.replace(/^system:/, "")).join(", ")}
          </li>
        ))}
      </ul>
      {graph && focus.size > 0 && (
        <span className="collision-meta">{graph.nodes.length} nodes in portfolio graph</span>
      )}
    </div>
  );
}

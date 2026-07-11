import type { DecisionEvent } from "../types";

const ACTION_LABEL: Record<DecisionEvent["action"], string> = {
  extracted: "extracted",
  inferred: "inferred",
  retrieved: "retrieved",
  asked: "asked",
  skipped: "skipped",
  assumed: "assumed",
  answered: "answered",
  edited: "edited",
};

interface DecisionRailProps {
  decisions: DecisionEvent[];
  schemaLabels?: Record<string, string>;
}

export function DecisionRail({ decisions, schemaLabels }: DecisionRailProps) {
  // Newest last in stream; show newest first in the rail.
  const ordered = [...decisions].reverse();

  return (
    <aside className="decision-rail" aria-label="Gap ladder decisions">
      <div className="decision-rail-header">
        <span className="decision-rail-title">X-ray</span>
        <span className="decision-rail-sub">why it filled — or asked</span>
      </div>
      {ordered.length === 0 ? (
        <div className="decision-empty">
          Decisions appear here as the orchestrator resolves gaps — infer, retrieve, then ask.
        </div>
      ) : (
        <ul className="decision-list">
          {ordered.map((d, i) => {
            const label =
              schemaLabels?.[d.slot] ?? d.slot.replace(/_/g, " ");
            return (
              <li
                key={`${d.slot}-${d.action}-${decisions.length - i}`}
                className={`decision-item decision-${d.action}${d.action === "asked" ? " pulse" : ""}`}
              >
                <div className="decision-item-top">
                  <span className={`decision-action action-${d.action}`}>
                    {ACTION_LABEL[d.action]}
                  </span>
                  <span className="decision-slot">{label}</span>
                </div>
                <p className="decision-reason">{d.reason}</p>
                {d.source && (
                  <span className="decision-source">{d.source}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}

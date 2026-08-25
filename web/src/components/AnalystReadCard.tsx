import { useState } from "react";
import type { AnalystRead } from "../types";

/** The analyst's read of the ask: where it sits in the business, what the
 * requester actually means, and the checklist a seasoned BA would still
 * check — flipping to covered live as the draft fills. Advisory only. */
export function AnalystReadCard({ read }: { read: AnalystRead }) {
  const [showRisks, setShowRisks] = useState(false);
  const openCount = read.unstated_needs.filter((n) => n.status === "open").length;

  return (
    <section className="analyst-card" aria-label="Analyst read">
      <div className="analyst-head">
        <span className="analyst-title">Analyst read</span>
        {read.process && (
          <span
            className="analyst-process"
            title={`Placed from: ${read.process.evidence.join(", ")}`}
          >
            {read.process.label}
          </span>
        )}
      </div>
      <p className="analyst-interpretation">
        {read.interpretation}
        {read.interpretation_source === "deterministic" && (
          <span className="analyst-det-tag" title="Model unavailable — deterministic restatement">
            {" "}
            (restated)
          </span>
        )}
      </p>

      {read.unstated_needs.length > 0 && (
        <div className="analyst-needs">
          <div className="analyst-subhead">
            Usually left unsaid{" "}
            <span className="analyst-count">
              {openCount === 0 ? "all covered" : `${openCount} open`}
            </span>
          </div>
          <ul>
            {read.unstated_needs.map((n) => (
              <li key={n.need} className={`analyst-need ${n.status}`} title={n.why}>
                <span className="need-mark" aria-hidden="true">
                  {n.status === "covered" ? "✓" : "○"}
                </span>
                <span className="need-text">
                  {n.need}
                  {n.status === "covered" && n.covered_by && (
                    <span className="need-covered-by"> · {n.covered_by.replace(/_/g, " ")}</span>
                  )}
                  {n.status === "open" && n.evidence_count > 0 && (
                    <span
                      className="need-evidence"
                      title={`Left open in ${n.evidence_count} delivered requirement(s) that missed the mark`}
                    >
                      missed ×{n.evidence_count}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(read.risks.length > 0 || read.kpis.length > 0) && (
        <button
          type="button"
          className="analyst-toggle"
          onClick={() => setShowRisks((v) => !v)}
        >
          {showRisks ? "Hide" : "Show"} risks & measures
        </button>
      )}
      {showRisks && (
        <div className="analyst-extra">
          {read.risks.map((r) => (
            <div key={r.risk} className="analyst-risk">
              <span className="risk-mark" aria-hidden="true">!</span>
              <span>
                {r.risk}
                <span className="risk-why"> — {r.why}</span>
              </span>
            </div>
          ))}
          {read.kpis.length > 0 && (
            <div className="analyst-kpis">
              Measured by: {read.kpis.join(" · ")}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

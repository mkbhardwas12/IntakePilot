import { useState } from "react";
import type { AttachmentFinding, AttachmentReport, AttachmentVerdict } from "../types";

const VERDICT_LABELS: Record<AttachmentVerdict, string> = {
  ready: "Ready to use",
  needs_fixes: "Usable — fixes suggested",
  unusable: "Fix before it can be used",
  unreadable: "Could not be read"
};

const SHOWN_FINDINGS = 4;

/** The instant answer to "can this spreadsheet actually be used?" —
 * verdict, findings with the exact cell to fix, and coverage of the
 * fields the requirement itself asked for. */
export function AttachmentCard({ report }: { report: AttachmentReport }) {
  const [expanded, setExpanded] = useState(false);
  const findings = report.findings.filter((f) => f.severity !== "info");
  const shown = expanded ? findings : findings.slice(0, SHOWN_FINDINGS);
  const hiddenCount = findings.length - shown.length;
  const rows = report.sheets.reduce((n, s) => n + s.data_rows, 0);

  return (
    <div className={`attach-card verdict-${report.verdict}`}>
      <div className="attach-head">
        <svg className="attach-clip" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path
            d="M10.5 4.5 5.7 9.3a1.6 1.6 0 1 0 2.3 2.3l4.8-4.8a3.2 3.2 0 1 0-4.6-4.6L3.4 7"
            fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"
          />
        </svg>
        <span className="attach-name">{report.filename}</span>
        <span className={`attach-verdict verdict-${report.verdict}`}>
          {VERDICT_LABELS[report.verdict]}
        </span>
      </div>
      {report.verdict !== "unreadable" && (
        <div className="attach-meta">
          {rows.toLocaleString()} data row{rows === 1 ? "" : "s"} ·{" "}
          {report.sheets.filter((s) => s.data_rows > 0).length} sheet
          {report.sheets.filter((s) => s.data_rows > 0).length === 1 ? "" : "s"}
          {report.fitness && report.fitness.requested_fields.length > 0 && (
            <>
              {" "}· covers {report.fitness.covered.length} of{" "}
              {report.fitness.requested_fields.length} requested field
              {report.fitness.requested_fields.length === 1 ? "" : "s"}
            </>
          )}
        </div>
      )}
      {shown.length > 0 && (
        <ul className="attach-findings">
          {shown.map((f, i) => (
            <FindingRow key={`${f.code}-${i}`} finding={f} />
          ))}
        </ul>
      )}
      {hiddenCount > 0 && (
        <button type="button" className="attach-more" onClick={() => setExpanded(true)}>
          Show {hiddenCount} more
        </button>
      )}
      {findings.length === 0 && report.verdict === "ready" && (
        <div className="attach-clean">No problems found — structure and types check out.</div>
      )}
    </div>
  );
}

function FindingRow({ finding }: { finding: AttachmentFinding }) {
  return (
    <li className={`attach-finding sev-${finding.severity}`}>
      <span className="finding-dot" aria-hidden="true" />
      <div className="finding-body">
        <span className="finding-msg">
          {finding.message}
          {finding.ref && <code className="finding-ref">{finding.ref}</code>}
        </span>
        <span className="finding-fix">{finding.fix}</span>
      </div>
    </li>
  );
}

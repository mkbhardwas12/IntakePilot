import { useState } from "react";
import type { Provenance, RequirementObject, Slot, SlotSchemaEntry } from "../types";
import { formatValue } from "../format";
import { backendContextOf } from "./SystemContext";

const PROVENANCE_LABEL: Record<Provenance, string> = {
  extracted: "extracted",
  inferred: "inferred",
  retrieved: "retrieved",
  answered: "answered",
  assumed: "assumed",
  edited: "edited"
};

interface ShadowDraftProps {
  draft: RequirementObject | null;
  schema: Record<string, SlotSchemaEntry> | null;
  changedKeys: Set<string>;
  confirmUnlocked: boolean;
  confirmDisabledReason?: string | null;
  /** Pre-confirm: filled slots can be revised in place. */
  editable?: boolean;
  onRevise?: (key: string, value: string) => void;
  onConfirm: () => void;
}

export function ShadowDraft({
  draft, schema, changedKeys, confirmUnlocked, confirmDisabledReason,
  editable, onRevise, onConfirm
}: ShadowDraftProps) {
  // Union: request-type schema forks (E) can add slots beyond the default
  // schema the page loaded — anything present in the draft must render.
  const slotKeys = Array.from(new Set([
    ...(schema ? Object.keys(schema) : []),
    ...(draft ? Object.keys(draft.slots) : [])
  ]));

  const confirmDisabled = !draft || !confirmUnlocked;

  return (
    <aside className="draft-pane">
      <div className="draft-header">
        <div className="draft-meta">
          <span className="draft-title">Shadow Draft</span>
          {draft ? (
            <div className="draft-ids">
              <span className="req-id">{draft.req_id}</span>
              <span className="version">v{draft.version}</span>
              <span className={`status-chip status-${draft.status}`}>{draft.status.replace(/_/g, " ")}</span>
            </div>
          ) : (
            <div className="draft-ids">
              <span className="req-id muted">starting…</span>
            </div>
          )}
        </div>
        <div className="readiness-block">
          <ReadinessRing score={draft?.readiness_score ?? 0} />
          <button
            className="confirm-btn"
            disabled={confirmDisabled}
            onClick={onConfirm}
            title={confirmDisabledReason ?? undefined}
            aria-description={confirmDisabledReason ?? undefined}
          >
            Confirm <span aria-hidden="true">→</span>
          </button>
          {confirmDisabled && confirmDisabledReason && (
            <span className="confirm-hint">{confirmDisabledReason}</span>
          )}
        </div>
      </div>

      <div className="slot-list">
        {slotKeys.length === 0 && <div className="slot-empty-hint">Slots appear here as the agent extracts them.</div>}
        {slotKeys.map((key) => {
          const entry = schema?.[key];
          const slot = draft?.slots[key];
          return (
            <SlotRow
              key={key}
              slotKey={key}
              entry={entry}
              slot={slot}
              changed={changedKeys.has(key)}
              editable={!!editable}
              onRevise={onRevise}
            />
          );
        })}
      </div>

      {draft && draft.assumptions.length > 0 && (
        <div className="draft-assumptions">
          <div className="draft-assumptions-title">Assumptions</div>
          {draft.assumptions.map((a, i) => {
            const slot = draft.slots[a];
            const label = schema?.[a]?.label ?? a.replace(/_/g, " ");
            return (
              <div key={i} className="draft-assumption-line">
                {label}: {String(slot?.value ?? "—")}
                {slot?.default_reason ? ` — ${slot.default_reason}` : ""}
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}

function SlotRow({
  slotKey,
  entry,
  slot,
  changed,
  editable,
  onRevise
}: {
  slotKey: string;
  entry: SlotSchemaEntry | undefined;
  slot: Slot | undefined;
  changed: boolean;
  editable: boolean;
  onRevise?: (key: string, value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const label = entry?.label ?? slotKey.replace(/_/g, " ");
  const value = slot ? displayValue(slotKey, slot) : null;
  const provenance = slot?.provenance ?? null;
  const confidence = slot?.confidence ?? 0;
  // backend_context is structured discovery data — not hand-editable.
  const canEdit =
    editable && !!onRevise && !!slot && slot.value !== null && slotKey !== "backend_context";

  const beginEdit = () => {
    const v = slot?.value;
    setText(Array.isArray(v) ? v.map(String).join(", ") : String(v ?? ""));
    setEditing(true);
  };

  return (
    <div className={changed ? "slot-row changed" : "slot-row"}>
      <div className="slot-row-top">
        <span className="slot-label">
          {label}
          {entry?.required && <span className="required-mark" title="Required">*</span>}
          {entry && !entry.askable && (
            <span className="auto-icon" title="Never asked — auto-resolved">
              <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                <rect x="2.5" y="5" width="7" height="5" rx="1.2" fill="currentColor" />
                <path d="M4 5 V3.8 a2 2 0 0 1 4 0 V5" stroke="currentColor" strokeWidth="1.3" fill="none" />
              </svg>
            </span>
          )}
        </span>
        <span className="slot-row-actions">
          {canEdit && !editing && (
            <button
              type="button"
              className="slot-edit-btn"
              title={`Revise ${label}`}
              aria-label={`Revise ${label}`}
              onClick={beginEdit}
            >
              <svg viewBox="0 0 14 14" width="11" height="11" aria-hidden="true">
                <path
                  d="M9.9 1.6 12.4 4.1 5 11.5 2 12l.5-3z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          )}
          {provenance && (
            <span className={`prov-badge prov-${provenance}`}>
              <span className="prov-dot" />
              {PROVENANCE_LABEL[provenance]}
            </span>
          )}
        </span>
      </div>
      {editing ? (
        <form
          className="slot-edit-form"
          onSubmit={(e) => {
            e.preventDefault();
            setEditing(false);
            if (onRevise) onRevise(slotKey, text);
          }}
        >
          <input
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditing(false);
            }}
            aria-label={`New value for ${label}`}
          />
          <button type="submit" disabled={text.trim() === ""}>Save</button>
          <button type="button" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      ) : (
        <div className={value === null ? "slot-value empty" : "slot-value"}>{value ?? "—"}</div>
      )}
      <div className="confidence-track">
        <div
          className={`confidence-fill${provenance ? ` conf-${provenance}` : ""}`}
          style={{ width: `${Math.max(0, Math.min(1, confidence)) * 100}%` }}
        />
      </div>
    </div>
  );
}

/** backend_context is structured discovery data — summarize instead of JSON. */
function displayValue(slotKey: string, slot: Slot): string | null {
  if (slotKey === "backend_context") {
    const ctx = backendContextOf(slot);
    if (!ctx) return null;
    const customs = ctx.entities.reduce((n, e) => n + e.customizations.length, 0);
    return `${ctx.entities.length} backend entit${ctx.entities.length === 1 ? "y" : "ies"} · ${customs} customization${customs === 1 ? "" : "s"} · ${ctx.systems.join(", ")}`;
  }
  return formatValue(slot.value);
}

export function ReadinessRing({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const r = 30;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - clamped / 100);

  return (
    <div className="readiness-ring" role="img" aria-label={`Readiness ${Math.round(clamped)} out of 100`}>
      <svg viewBox="0 0 76 76" width="76" height="76">
        <defs>
          <linearGradient id="ring-g" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" style={{ stopColor: "var(--accent)" }} />
            <stop offset="1" style={{ stopColor: "var(--accent-2)" }} />
          </linearGradient>
        </defs>
        <circle cx="38" cy="38" r={r} fill="none" stroke="var(--track)" className="ring-track" strokeWidth="6" />
        <circle
          cx="38"
          cy="38"
          r={r}
          fill="none"
          stroke="url(#ring-g)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 38 38)"
          className="ring-progress"
        />
      </svg>
      <div className="ring-center">
        <span className="ring-number">{Math.round(clamped)}</span>
        <span className="ring-sub">ready</span>
      </div>
    </div>
  );
}

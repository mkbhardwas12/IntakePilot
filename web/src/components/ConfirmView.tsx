import { useEffect, useMemo, useRef, useState } from "react";
import { confirmRequirement, getRender } from "../api";
import type { ConfirmResponse, RequirementObject, SlotSchemaEntry } from "../types";
import { editableString, formatValue } from "../format";
import { useToast } from "../toast";
import { SystemContextCard, backendContextOf } from "./SystemContext";

interface ConfirmViewProps {
  draft: RequirementObject;
  sessionId: string;
  schema: Record<string, SlotSchemaEntry> | null;
  demoAutoConfirm?: boolean;
  onCancel: () => void;
  onConfirmed: (resp: ConfirmResponse) => void;
}

export function ConfirmView({
  draft, sessionId, schema, demoAutoConfirm, onCancel, onConfirmed
}: ConfirmViewProps) {
  const toast = useToast();
  const [rendered, setRendered] = useState<string | null>(null);
  const [renderFailed, setRenderFailed] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const autoStarted = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getRender(draft.req_id, sessionId)
      .then((r) => {
        if (!cancelled) setRendered(r.business);
      })
      .catch(() => {
        if (!cancelled) setRenderFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [draft.req_id, sessionId]);

  // Focus trap + Escape closes (does not commit).
  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () =>
      panel
        ? Array.from(
            panel.querySelectorAll<HTMLElement>(
              'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
            )
          )
        : [];
    const first = focusable()[0];
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && editingKey === null) {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const nodes = focusable();
      if (nodes.length === 0) return;
      const firstEl = nodes[0];
      const lastEl = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previouslyFocused.current?.focus?.();
    };
  }, [onCancel, editingKey]);

  const slotKeys = Array.from(new Set([
    ...(schema ? Object.keys(schema) : []),
    ...Object.keys(draft.slots)
  ]))
    .filter((k) => k !== "backend_context")
    .sort((a, b) => (draft.slots[a]?.confidence ?? 0) - (draft.slots[b]?.confidence ?? 0));
  const backendContext = backendContextOf(draft.slots["backend_context"]);

  const changedEdits = useMemo(() => {
    const diff: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(edits)) {
      if (value !== editableString(draft.slots[key]?.value)) diff[key] = value;
    }
    return diff;
  }, [edits, draft.slots]);

  const assumedKeys = slotKeys.filter((k) => draft.slots[k]?.provenance === "assumed");

  const submit = async () => {
    setSubmitting(true);
    try {
      const resp = await confirmRequirement(
        draft.req_id,
        sessionId,
        changedEdits,
        draft.requester.name
      );
      onConfirmed(resp);
    } catch (err: unknown) {
      toast(`Confirm failed: ${err instanceof Error ? err.message : String(err)}`);
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (!demoAutoConfirm || autoStarted.current || submitting) return;
    autoStarted.current = true;
    const t = window.setTimeout(() => void submit(), 1100);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoAutoConfirm]);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Review and confirm">
      <div className="overlay-panel" ref={panelRef}>
        <div className="overlay-head">
          <div>
            <h2>Review &amp; confirm</h2>
            <span className="overlay-sub">
              {draft.req_id} · v{draft.version}
            </span>
          </div>
          <button className="ghost-btn" onClick={onCancel} disabled={submitting}>
            ← Back to chat
          </button>
        </div>

        <div className="render-card">
          {rendered !== null ? (
            <pre className="render-text">{rendered}</pre>
          ) : renderFailed ? (
            <span className="render-fallback">Summary unavailable — review the fields below.</span>
          ) : (
            <span className="render-loading">Rendering summary…</span>
          )}
        </div>

        <div className="confirm-slots">
          <div className="section-title">Fields — click any value to edit</div>
          {slotKeys.map((key) => {
            const entry = schema?.[key];
            const slot = draft.slots[key];
            const original = editableString(slot?.value);
            const isEdited = key in edits && edits[key] !== original;
            const display = key in edits ? edits[key] : formatValue(slot?.value);
            return (
              <div key={key} className="confirm-slot-row">
                <span className="slot-label">
                  {entry?.label ?? key.replace(/_/g, " ")}
                  {entry?.required && <span className="required-mark" aria-label="required">*</span>}
                </span>
                {editingKey === key ? (
                  <input
                    className="edit-input"
                    autoFocus
                    value={edits[key] ?? original}
                    onChange={(e) => setEdits((prev) => ({ ...prev, [key]: e.target.value }))}
                    onBlur={() => setEditingKey(null)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setEditingKey(null);
                      if (e.key === "Escape") {
                        setEdits((prev) => {
                          const next = { ...prev };
                          delete next[key];
                          return next;
                        });
                        setEditingKey(null);
                      }
                    }}
                  />
                ) : (
                  <button
                    className={display === null || display === "" ? "editable-value empty" : "editable-value"}
                    onClick={() => setEditingKey(key)}
                    disabled={submitting}
                  >
                    {display === null || display === "" ? "—" : display}
                  </button>
                )}
                {isEdited ? (
                  <span className="prov-badge prov-edited">
                    <span className="prov-dot" />
                    edited
                  </span>
                ) : slot?.provenance ? (
                  <span className={`prov-badge prov-${slot.provenance}`}>
                    <span className="prov-dot" />
                    {slot.provenance}
                  </span>
                ) : (
                  <span className="prov-badge prov-none">—</span>
                )}
              </div>
            );
          })}
        </div>

        {backendContext && (
          <SystemContextCard context={backendContext} source={draft.slots["backend_context"]?.source} />
        )}

        {assumedKeys.length > 0 && (
          <div className="assumption-register">
            <div className="section-title">Assumption register</div>
            {assumedKeys.map((key) => {
              const slot = draft.slots[key];
              const entry = schema?.[key];
              return (
                <div key={key} className="assumption-row">
                  <span className="assumption-key">{entry?.label ?? key.replace(/_/g, " ")}</span>
                  <span className="assumption-reason">
                    Assumed: {formatValue(slot.value) ?? "—"}
                    {slot.default_reason ? ` — ${slot.default_reason}` : " — default applied; override here"}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <div className="overlay-foot">
          <span className="edit-count">
            {Object.keys(changedEdits).length === 0
              ? "No edits"
              : `${Object.keys(changedEdits).length} field${Object.keys(changedEdits).length === 1 ? "" : "s"} edited`}
          </span>
          <button className="confirm-btn big" onClick={() => void submit()} disabled={submitting}>
            {submitting ? "Confirming…" : "Confirm requirement"}
          </button>
        </div>
      </div>
    </div>
  );
}

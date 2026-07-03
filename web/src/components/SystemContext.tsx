import type { BackendContext, Slot } from "../types";

/** Read a backend_context slot value defensively; null when absent/empty. */
export function backendContextOf(slot: Slot | undefined): BackendContext | null {
  const v = slot?.value;
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const ctx = v as BackendContext;
  return Array.isArray(ctx.entities) && ctx.entities.length > 0 ? ctx : null;
}

/** ADDENDUM-01: auto-discovered backend entities + customizations, shown so
 * the requester (and later the assigned team) can see what was attached
 * without ever having been asked about it. */
export function SystemContextCard({ context, source }: { context: BackendContext; source?: string | null }) {
  return (
    <div className="syscontext-card">
      <div className="syscontext-head">
        <span className="syscontext-title">System context (auto-discovered)</span>
        <span className="prov-badge prov-retrieved">
          <span className="prov-dot" />
          retrieved
        </span>
      </div>
      <p className="syscontext-note">
        Discovered via {source?.replace(/^(connector|system_kb):/, "$1: ") ?? "system connectors"} — you were not
        asked for any of this, and the routed ticket carries it for the assigned team.
      </p>
      {context.entities.map((ent) => (
        <div key={`${ent.system}:${ent.entity}`} className="syscontext-entity">
          <div className="syscontext-entity-head">
            <span className="syscontext-entity-name">{ent.label || ent.entity}</span>
            <span className="syscontext-backend">{ent.backend_name || ent.entity}</span>
            <span className="syscontext-system">{ent.system_label || ent.system}</span>
            <span className={ent.verified ? "kb-chip verified" : "kb-chip unverified"}>
              {ent.verified ? "verified" : "unverified"}
            </span>
          </div>
          {ent.description && <p className="syscontext-desc">{ent.description}</p>}
          {ent.customizations.length > 0 && (
            <div className="syscontext-customs">
              {ent.customizations.map((c) => (
                <div key={c.name} className="syscontext-custom">
                  <span className="syscontext-custom-name">{c.name}</span>
                  <span className="syscontext-custom-desc">
                    {c.type && `${c.type} · `}
                    {c.description}
                  </span>
                  {c.owner_team && <span className="syscontext-custom-owner">owner: {c.owner_team}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

import { useEffect, useState } from "react";
import { acceptGlossaryTerm, getGlossaryProposals, getMetrics } from "../api";
import type { GlossaryProposal, MetricsResponse } from "../api";
import { useToast } from "../toast";

export function MetricsPage() {
  const toast = useToast();
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [proposals, setProposals] = useState<GlossaryProposal[]>([]);

  const loadMetrics = () => {
    setFailed(false);
    getMetrics()
      .then((m) => setMetrics(m))
      .catch((err: unknown) => {
        setFailed(true);
        toast(`Could not load metrics: ${err instanceof Error ? err.message : String(err)}`);
      });
  };

  const loadProposals = () => {
    getGlossaryProposals()
      .then((r) => setProposals(Array.isArray(r) ? r : r.proposals ?? []))
      .catch(() => setProposals([]));
  };

  useEffect(() => {
    loadMetrics();
    loadProposals();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const accept = async (p: GlossaryProposal) => {
    try {
      await acceptGlossaryTerm(p.term, p.maps_to ?? {});
      toast(`Accepted “${p.term}”`);
      loadProposals();
    } catch (err: unknown) {
      toast(`Accept failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  if (failed) {
    return (
      <div className="metrics-page">
        <h1 className="page-title">Metrics</h1>
        <div className="empty-note">Metrics are unavailable right now — is the backend running?</div>
        <button type="button" className="ghost-btn" onClick={loadMetrics}>Retry</button>
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="metrics-page">
        <h1 className="page-title">Metrics</h1>
        <div className="empty-note">Loading metrics…</div>
      </div>
    );
  }

  const t = metrics.totals;
  const editEntries = Object.entries(metrics.edit_rate_per_field).sort((a, b) => b[1] - a[1]);
  const maxEditRate = editEntries.length > 0 ? Math.max(...editEntries.map(([, v]) => v)) : 0;

  return (
    <div className="metrics-page">
      <h1 className="page-title">Metrics</h1>

      <div className="stat-grid">
        <StatCard label="Intakes" value={String(t.intakes)} />
        <StatCard label="Confirmed" value={String(t.confirmed)} />
        <StatCard label="Routed" value={String(t.routed)} />
        <StatCard label="Edits" value={String(t.edits)} />
        <StatCard label="Questions asked" value={String(t.questions_asked)} />
        <StatCard
          label="Avg questions / intake"
          value={metrics.questions_per_intake_avg !== null ? metrics.questions_per_intake_avg.toFixed(1) : null}
        />
        <StatCard
          label="Intake latency"
          value={
            metrics.intake_latency_seconds_avg !== null ? `${metrics.intake_latency_seconds_avg.toFixed(1)}s` : null
          }
        />
        <StatCard label="Analyst-hours displaced" value={metrics.analyst_hours_displaced.toFixed(1)} accent />
        <StatCard
          label="Routing accuracy"
          value={metrics.routing_accuracy !== null ? `${Math.round(metrics.routing_accuracy * 100)}%` : null}
        />
        <StatCard
          label="Duplicate catch rate"
          value={metrics.duplicate_catch_rate !== null ? `${Math.round(metrics.duplicate_catch_rate * 100)}%` : null}
        />
        <StatCard
          label="Assumption rate"
          value={metrics.assumption_rate !== null ? `${Math.round(metrics.assumption_rate * 100)}%` : null}
        />
        <StatCard
          label="Backend knowledge base"
          value={metrics.system_kb && metrics.system_kb.entities > 0 ? String(metrics.system_kb.entities) : null}
          sub={
            metrics.system_kb && metrics.system_kb.entities > 0
              ? `entities · ${metrics.system_kb.customizations} customizations · ${metrics.system_kb.verified} verified`
              : undefined
          }
          accent
        />
      </div>

      <section className="edit-rates">
        <h2 className="section-title">Edit rate per field</h2>
        {editEntries.length === 0 ? (
          <div className="empty-note">No confirmed intakes yet — run one from the Intake tab.</div>
        ) : (
          <div className="bar-list">
            {editEntries.map(([field, rate]) => (
              <div key={field} className="bar-row">
                <span className="bar-label">{field.replace(/_/g, " ")}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${maxEditRate > 0 ? (rate / maxEditRate) * 100 : 0}%` }}
                  />
                </div>
                <span className="bar-value tnum">{Math.round(rate * 100)}%</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="glossary-inbox">
        <h2 className="section-title">Glossary proposals</h2>
        <p className="page-sub">Recurring corrections mined into vocabulary — accept to teach the next intake.</p>
        {proposals.length === 0 ? (
          <div className="empty-note">No proposals yet — confirm a few intakes with edits.</div>
        ) : (
          <ul className="proposal-list">
            {proposals.map((p) => (
              <li key={p.term} className="proposal-row">
                <div>
                  <strong>{p.term}</strong>
                  <span className="proposal-meta">
                    {typeof p.maps_to === "object" ? JSON.stringify(p.maps_to) : String(p.maps_to ?? "")}
                    {p.evidence_count != null ? ` · evidence ${p.evidence_count}` : ""}
                  </span>
                </div>
                <button type="button" className="ghost-btn small" onClick={() => void accept(p)}>
                  Accept
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  accent
}: {
  label: string;
  value: string | null;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className={accent ? "stat-card accent" : "stat-card"}>
      <span className="stat-label">{label}</span>
      {value !== null ? (
        <>
          <span className="stat-value tnum">{value}</span>
          {sub && <span className="stat-sub">{sub}</span>}
        </>
      ) : (
        <span className="stat-empty">No data yet — run an intake</span>
      )}
    </div>
  );
}

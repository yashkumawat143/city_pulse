import { useCallback, useState } from "react";
import api from "../lib/api";
import { clock, metricLabel, num } from "../lib/format";
import { useApiQuery } from "../hooks/useApiQuery";
import { Card, Drawer, ErrorState, KeyValue, Loading, SevBadge, StatusPill, Tag } from "./ui";
import { ConfidenceBreakdown } from "./panels";

const LIFECYCLE_ORDER = ["DETECTED", "MONITORING", "ESCALATING", "PEAK", "RECOVERING", "ACKNOWLEDGED", "RESOLVED"];

/**
 * Event explanation + lifecycle actions. Everything shown here comes from
 * GET /api/disruptions/{id}; acknowledge / resolve write back to the backend.
 */
export default function EventDrawer({ eventId, onClose, onChanged }) {
  const fetchDetail = useCallback(() => api.disruption(eventId), [eventId]);
  const { data, error, loading, reload } = useApiQuery(fetchDetail, [eventId], { enabled: Boolean(eventId) });
  const fetchAnalyst = useCallback(() => api.analyst(eventId), [eventId]);
  const ana = useApiQuery(fetchAnalyst, [eventId], { enabled: Boolean(eventId) });
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);

  const act = async (action) => {
    setBusy(action);
    setActionError(null);
    try {
      await api.disruptionAct(eventId, action);
      await reload();
      onChanged?.();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const lifecycle = data?.lifecycle || {};
  const steps = Object.keys(lifecycle).sort(
    (a, b) => LIFECYCLE_ORDER.indexOf(a) - LIFECYCLE_ORDER.indexOf(b),
  );
  const evidence = data?.evidence || [];
  const lagged = data?.correlation?.lagged || [];

  return (
    <Drawer
      open={Boolean(eventId)}
      onClose={onClose}
      title={`Civic event ${eventId || ""}`}
      subtitle="Backend event record with supporting observations and lifecycle state"
      footer={data && (
        <div className="row between wrap">
          <span className="muted small">
            Acknowledging keeps the event active; resolving closes it. Both update backend state.
          </span>
          <span className="row wrap">
            <button type="button" className="btn" disabled={busy || data.status !== "active"}
                    onClick={() => act("acknowledge")}
                    title={data.status !== "active" ? "Only active events can be acknowledged" : "Acknowledge"}>
              {busy === "acknowledge" ? "Acknowledging…" : "Acknowledge"}
            </button>
            <button type="button" className="btn danger" disabled={busy || data.status === "resolved"}
                    onClick={() => act("resolve")}
                    title={data.status === "resolved" ? "Already resolved" : "Mark resolved"}>
              {busy === "resolve" ? "Resolving…" : "Mark resolved"}
            </button>
          </span>
        </div>
      )}
    >
      {loading && <Loading label="Loading event detail…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {actionError && <p className="inline-error" role="alert">{actionError}</p>}
      {data && !loading && (
        <div className="drawer-grid">
          <Card title="Event summary">
            <div className="row wrap gap">
              <SevBadge severity={data.severity} />
              <StatusPill status={data.status} />
              <Tag tone="warn">State {data.state}</Tag>
              <Tag tone="info">Confidence {Math.round(data.confidence)}%</Tag>
              {data.event_label && <Tag tone="info">{data.event_label}</Tag>}
              {data.trend && <Tag tone="info">Trend {data.trend}</Tag>}
              {data.risk_band && (
                <Tag tone={data.risk_band === "CRITICAL" || data.risk_band === "HIGH" ? "warn" : "info"}>
                  Risk {data.risk} · {data.risk_band}
                </Tag>
              )}
            </div>
            <KeyValue items={[
              ["Zone", data.zone],
              ["Identity", data.id],
              ["Classification", data.event_type || "—"],
              ["Started", `${clock(data.started)} (city clock)`],
              ["Duration", `${data.duration_min} min`],
              ["Trajectory", `${data.state}${data.trend ? ` · ${data.trend}` : ""}`],
              ["Risk score", data.risk != null ? `${data.risk}/100 (${data.risk_band})` : "—"],
              ["Signal sequence", data.sequence],
              ["Independent sources", (data.sources || []).join(", ")],
              ["Peak score", num(data.peak, 2)],
              ["Coordinates", data.latitude ? `${data.latitude}, ${data.longitude}` : "unavailable"],
            ]} />
            <p className="muted small">{data.note}</p>
            <p className="muted small">
              CityPulse Event Confidence is a prototype score built from signal strength, signal diversity,
              co-activity time and persistence. It is not a probability.
            </p>
          </Card>

          <Card title="Confidence breakdown" subtitle="Explainable components behind the Event Confidence score">
            {data.confidence_breakdown ? (
              <ConfidenceBreakdown breakdown={data.confidence_breakdown} weights={data.confidence_weights} />
            ) : (
              <p className="muted">Breakdown unavailable for this event (recorded from the current engine version).</p>
            )}
          </Card>

          <Card title="AI Civic Analyst" subtitle="Plain-language explanation generated from this event's evidence"
                badge={<Tag tone="info">Explainable AI</Tag>}>
            {ana.loading && !ana.data && <Loading label="Assembling the analyst brief…" rows={2} />}
            {ana.error && <ErrorState message={ana.error} onRetry={ana.reload} />}
            {ana.data && (
              <>
                <p>{ana.data.narrative}</p>
                <p className="muted small">
                  Engine: {ana.data.engine} · generated {clock(ana.data.generated_at)}
                </p>
                <p className="muted small">{ana.data.disclaimer}</p>
              </>
            )}
          </Card>

          <Card title="Detection rationale" subtitle="Why CityPulse raised this event (supporting observations only)">
            {evidence.length === 0
              ? <p className="muted">No supporting observations are attached to this event right now.</p>
              : (
                <ul className="evidence">
                  {evidence.map((e, i) => (
                    <li key={`${e.kind}-${e.metric}-${i}`}>
                      <Tag tone={e.kind === "anomaly" ? "warn" : "info"}>{e.kind === "anomaly" ? "Signal" : "Lag"}</Tag>
                      <span>{e.text}</span>
                    </li>
                  ))}
                </ul>
              )}
            {lagged.length > 0 && (
              <>
                <h3 className="sub-title">Temporal relationships (association, not causation)</h3>
                <ul className="evidence">
                  {lagged.slice(0, 4).map((p, i) => (
                    <li key={i}>
                      <Tag tone="info">r = {p.r}</Tag>
                      <span>{metricLabel(p.a)} → {metricLabel(p.b)} at lag +{p.lag_minutes} min · {p.classification}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card title="Lifecycle timeline" subtitle="Backend state machine">
            <ol className="timeline">
              {steps.map((s) => (
                <li key={s}>
                  <b>{s}</b>
                  <span className="muted small">{clock(lifecycle[s])}</span>
                </li>
              ))}
              {steps.length === 0 && <li className="muted">No lifecycle transitions recorded.</li>}
            </ol>
            {data.acknowledged_at && <p className="muted small">Acknowledged {clock(data.acknowledged_at)}</p>}
            {data.resolved_at && (
              <p className="muted small">
                Resolved {clock(data.resolved_at)}{data.resolved_by ? ` by ${data.resolved_by}` : ""}
              </p>
            )}
          </Card>
        </div>
      )}
    </Drawer>
  );
}

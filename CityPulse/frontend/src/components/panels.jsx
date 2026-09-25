import { Link } from "react-router-dom";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { clock, healthBand, healthColor, int, metricLabel, metricUnit, num, pctText } from "../lib/format";
import { Card, Empty, HealthPill, LevelBadge, Meter, SevBadge, StatusPill, Tag } from "./ui";

export const CHART_AXIS = { stroke: "#7f8db8", fontSize: 11 };
export const TOOLTIP_STYLE = { background: "#0e1730", border: "1px solid #26324f", borderRadius: 10, fontSize: 12, color: "#e8eeff" };

export function AttentionPanel({ attention, eventId, onInspectEvent }) {
  const a = attention;
  if (!a) return null;
  return (
      <Card title="What needs attention?" subtitle={a.headline || "Prioritised view built from live evidence"}
            badge={<Tag tone={a.level === "CRITICAL" || a.level === "HIGH" ? "warn" : a.level === "ALL_CLEAR" ? "info" : "warn"}>{a.level}</Tag>}
            actions={eventId && (
              <button type="button" className="btn ghost" onClick={() => onInspectEvent(eventId)}>View event detail</button>
            )}>
        {a.level === "ALL_CLEAR" ? (
          <Empty title="Nothing urgent needs attention"
                 hint={a.text || "No active multi-signal events. City signals are within expected ranges."} />
        ) : (
          <>
            <div className="row wrap gap">
              <Tag tone="info">State {a.state}</Tag>
              <Tag tone="warn">Trend {a.trend}</Tag>
              {a.confidence != null && <Tag tone="info">Confidence {a.confidence}%</Tag>}
              {a.risk && (
                <span className="row wrap gap">
                  <b style={{ color: riskColor(a.risk.score) }}>Risk {a.risk.score}/100</b>
                  <Tag tone={a.risk.band === "CRITICAL" ? "warn" : "info"}>{a.risk.band}</Tag>
                </span>
              )}
            </div>
            {a.signals?.length > 0 && (
              <>
                <h3 className="sub-title">Strongest signals</h3>
                {a.signals.map((s) => (
                  <div key={s.metric} className="meter-row">
                    <span>{s.label} <small>{s.current} {s.unit} · z {s.z} · {s.band}</small></span>
                    <b>{s.score ?? "—"}</b>
                    <Meter value={s.score ?? 0} color={riskColor(s.score ?? 0)} label={`${s.label} anomaly score`} />
                  </div>
                ))}
              </>
            )}
            {a.recommendations?.length > 0 && (
              <>
                <h3 className="sub-title">Recommended checks</h3>
                <ul className="why">{a.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </>
            )}
            {a.early_warnings?.length > 0 && (
              <p className="inline-warn">
                Early warning: {a.early_warnings.map((w) => `${w.zone} at ${w.confidence}% confidence`).join(", ")} — below the event threshold, watching closely.
              </p>
            )}
            <p className="muted small">{a.text}</p>
          </>
        )}
      </Card>
    );
}

const RISK_TONE = (band) => (band === "CRITICAL" || band === "HIGH" ? "warn" : "info");

function riskColor(score) {
  return score > 75 ? "#f87171" : score > 50 ? "#fb923c" : score > 25 ? "#facc15" : "#34d399";
}

export function RiskPanel({ risk }) {
  if (!risk) return null;
  return (
    <Card title="Risk engine" subtitle="0-100 evidence-based risk — separate from anomaly severity and health">
      <div className="health-top">
        <span className="health-score" style={{ color: riskColor(risk.score) }}>{risk.score}</span>
        <Tag tone={RISK_TONE(risk.band)}>{risk.band}</Tag>
        <span className="muted small">worst zone: {risk.zone}</span>
      </div>
      {Object.entries(risk.zones || {}).map(([z, v]) => (
        <div key={z} className="meter-row">
          <span>{z}</span><b>{v}</b>
          <Meter value={v} color={riskColor(v)} label={`risk ${z}`} />
        </div>
      ))}
      <p className="muted small">{risk.note}</p>
    </Card>
  );
}

export function TimelinePanel({ timeline, onInspect }) {
  const items = [...(timeline || [])].slice(-40).reverse();
  return (
    <Card title="Event timeline" subtitle="Chronological detection history — built only from real backend records"
          collapsible defaultOpen={false}
          badge={<Tag tone="info">{items.length} entries</Tag>}>
      {items.length === 0 ? (
        <Empty title="No timeline entries yet"
               hint="Anomalies, event lifecycle transitions and alerts appear here as they are detected." />
      ) : (
        <ul className="timeline">
          {items.map((it, i) => (
            <li key={`${it.ref}-${it.t}-${i}`}>
              <b>{clock(it.t)}</b>
              <span>
                <Tag tone={it.severity === "critical" || it.severity === "high" ? "warn" : "info"}>{it.kind}</Tag>{" "}
                <span className="strong">{it.title}</span>
                {onInspect && it.kind === "event" && (
                  <button type="button" className="btn ghost" onClick={() => onInspect(it.ref)}>Open</button>
                )}
                <span className="muted small"> — {it.text} · {it.zone}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const CONF_LABELS = {
  anomaly_strength: "Anomaly strength",
  signal_diversity: "Signal diversity",
  temporal_proximity: "Temporal proximity",
  persistence: "Persistence",
  spatial_concentration: "Spatial concentration",
};

export function ConfidenceBreakdown({ breakdown, weights }) {
  const entries = Object.entries(breakdown || {});
  if (!entries.length) return null;
  return (
    <>
      {entries.map(([k, v]) => (
        <div key={k} className="meter-row">
          <span>{CONF_LABELS[k] || k}
            <small>{weights?.[k] != null ? `${Math.round(weights[k] * 100)}% weight` : ""}</small></span>
          <b>{Math.round(v)}</b>
          <Meter value={v} color="#22d3ee" label={CONF_LABELS[k] || k} />
        </div>
      ))}
      <p className="muted small">
        Confidence = weighted sum of these five 0-100 components — a prototype score, not a probability.
      </p>
    </>
  );
}
export function KpiGrid({ kpis, health }) {
  const items = [
    { to: "/", label: "City health", value: health.score, suffix: "/100", note: health.status,
      accent: healthColor(health.score) },
    { to: "/anomalies", label: "Active anomalies", value: kpis.anomalies, note: "above baseline + floor" },
    { to: "/events", label: "Civic events", value: kpis.disruptions,
      note: `${kpis.events_acknowledged} acknowledged · ${kpis.events_resolved} resolved` },
    { to: "/events", label: "Correlations", value: kpis.correlations, note: "possible multi-signal links" },
    { to: "/alerts", label: "Active alerts", value: kpis.alerts, note: "operator queue" },
    { to: "/sources", label: "Feeds live", value: `${kpis.sources_live}/${kpis.sources_total}`,
      note: "synthetic sources" },
  ];
  return (
    <div className="kpis">
      {items.map((i) => (
        <Link key={i.label} to={i.to} className="kpi" style={i.accent ? { "--accent": i.accent } : undefined}>
          <span className="kpi-label">{i.label}</span>
          <span className="kpi-value">{i.value}<small>{i.suffix || ""}</small></span>
          <span className="kpi-note">{i.note}</span>
        </Link>
      ))}
    </div>
  );
}

export function WhyNowPanel({ summary, onInspectEvent, eventId }) {
  const hasEvent = Boolean(summary?.zone) && (summary?.lines?.length ?? 0) > 0;
  return (
    <Card
      title="Why now?"
      subtitle={summary?.headline || "Rule-based explanation assembled from live readings"}
      badge={<Tag tone="info">Explainable</Tag>}
      actions={eventId && (
        <button type="button" className="btn ghost" onClick={() => onInspectEvent(eventId)}>View event detail</button>
      )}
    >
      {!hasEvent ? (
        <Empty title="No active multi-signal event"
               hint={summary?.text || "City signals are currently within expected ranges."} />
      ) : (
        <>
          <ul className="why">
            {summary.lines.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
          {summary.confidence != null && (
            <div className="row wrap gap">
              <HealthPill score={Math.round(summary.confidence)} status="Event confidence" />
              <Tag tone="warn">State {summary.state}</Tag>
            </div>
          )}
          <p className="muted small">{summary.text}</p>
        </>
      )}
    </Card>
  );
}

export function TrendChart({ trend, metric = "rainfall" }) {
  const data = (trend || []).filter(Boolean);
  if (!data.length) {
    return (
      <Card title="Historical trends">
        <Empty title="No trend data yet" hint="Trend rows appear once the engine has produced a few ticks." />
      </Card>
    );
  }
  const unit = metricUnit(metric);
  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 16 }}>
        <CartesianGrid stroke="#1f2b47" strokeDasharray="3 3" />
        <XAxis dataKey="t" {...CHART_AXIS} minTickGap={24}
               label={{ value: "simulated city time (HH:MM)", position: "insideBottom", offset: -6, fill: "#7f8db8", fontSize: 11 }} />
        <YAxis yAxisId="health" domain={[0, 100]} {...CHART_AXIS}
               label={{ value: "city health (0-100)", angle: -90, position: "insideLeft", fill: "#7f8db8", fontSize: 11 }} />
        <YAxis yAxisId="metric" orientation="right" {...CHART_AXIS}
               label={{ value: `${metricLabel(metric)} (${unit})`, angle: 90, position: "insideRight", fill: "#7f8db8", fontSize: 11 }} />
        <Tooltip contentStyle={TOOLTIP_STYLE}
                 formatter={(v, n) => [n === "health" ? `${v}/100` : `${v} ${unit}`, n === "health" ? "City health" : metricLabel(n)]}
                 labelFormatter={(l) => `City clock ${l}`} />
        <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12 }} />
        <Line yAxisId="health" type="monotone" dataKey="health" name="City health" stroke="#a855f7"
              strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line yAxisId="metric" type="monotone" dataKey={metric} name={metricLabel(metric)} stroke="#22d3ee"
              strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function HealthBreakdown({ health }) {
  const comps = Object.entries(health.components || {});
  return (
    <Card title="City health breakdown"
          subtitle="0-100 per component (higher = healthier), minus anomaly / event penalties">
      <div className="health-top">
        <span className="health-score" style={{ color: healthColor(health.score) }}>{health.score}</span>
        <HealthPill score={health.score} status={health.status} />
        <span className="muted small">
          {health.trend_pct >= 0 ? "▲" : "▼"} {Math.abs(health.trend_pct)}% vs 10 ticks ago
        </span>
      </div>
      {comps.length === 0
        ? <p className="muted">All health feeds are offline — no component score can be computed.</p>
        : comps.map(([name, v]) => (
          <div key={name} className="meter-row">
            <span>
              {name}
              <small>{Math.round((health.weights_used?.[name] ?? health.weights?.[name] ?? 0) * 100)}% weight</small>
            </span>
            <b>{v}</b>
            <Meter value={v} color={healthColor(v)} label={`${name} component`} />
          </div>
        ))}
      {health.partial && (
        <p className="inline-warn">
          Partial data: {health.missing_components?.join(", ")} feed(s) offline — weights re-normalised over the
          remaining components.
        </p>
      )}
      <p className="muted small">
        Penalties applied: −{health.penalty_anomalies} (anomalies) · −{health.penalty_disruptions} (active events)
      </p>
    </Card>
  );
}


export function ActiveEventsPanel({ events, onInspect, onAction, busyId }) {
  return (
    <Card title="Active civic events" subtitle="Multi-signal disruptions tracked by the backend lifecycle"
          collapsible defaultOpen={events.length <= 3}
          badge={<Tag tone="warn">{events.length} active</Tag>}>
      {events.length === 0 ? (
        <Empty title="No active civic events"
               hint="No zone currently shows ≥3 co-active anomaly signals with sufficient confidence. Run a scenario in Simulation to see this panel react." />
      ) : (
        <ul className="event-list">
          {events.map((e) => (
            <li key={e.id}>
              <div className="row between wrap">
                <span className="row wrap gap">
                  <b>{e.zone}</b>
                  <SevBadge severity={e.severity} compact />
                  <StatusPill status={e.status} />
                  <Tag tone="warn">{e.state}</Tag>
                </span>
                <span className="muted small">
                  confidence {Math.round(e.confidence)}% · {e.duration_min} min
                </span>
              </div>
              <p className="muted small">{e.sequence}</p>
              <div className="row wrap gap">
                <button type="button" className="btn ghost" onClick={() => onInspect(e.id)}>Evidence & lifecycle</button>
                <button type="button" className="btn ghost" disabled={busyId === e.id || e.status !== "active"}
                        onClick={() => onAction(e.id, "acknowledge")}>
                  {busyId === e.id ? "Working…" : "Acknowledge"}
                </button>
                <button type="button" className="btn ghost danger" disabled={busyId === e.id}
                        onClick={() => onAction(e.id, "resolve")}>Resolve</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function LifecycleStepper({ lifecycle = {}, status }) {
  const order = ["DETECTED", "MONITORING", "ESCALATING", "PEAK", "RECOVERING", "ACKNOWLEDGED", "RESOLVED"];
  const reached = new Set([...Object.keys(lifecycle), status === "acknowledged" ? "ACKNOWLEDGED" : null].filter(Boolean));
  return (
    <ol className="stepper" aria-label="Civic event lifecycle">
      {order.map((s) => (
        <li key={s} className={reached.has(s) ? "done" : ""}>
          <span className="dot" aria-hidden="true">{reached.has(s) ? "✓" : ""}</span>
          <span className="label">{s}</span>
          {lifecycle[s] && <span className="muted small">{clock(lifecycle[s])}</span>}
        </li>
      ))}
    </ol>
  );
}

export function EventStream({ events, onInspect }) {
  return (
    <Card title="Signal readings stream" subtitle="Anomalous measurement rows emitted by the ingestion pipeline"
          badge={<Tag tone="info">latest {events.length}</Tag>}>
      {events.length === 0 ? (
        <Empty title="No readings yet" hint="Readings appear when a metric exceeds its baseline threshold and practical floor." />
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Latest anomalous signal readings</caption>
            <thead>
              <tr><th scope="col">Time</th><th scope="col">Metric</th><th scope="col">Value</th>
                <th scope="col">Zone</th><th scope="col">Source</th><th scope="col">Severity</th></tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} onClick={() => onInspect?.(e.id)} tabIndex={onInspect ? 0 : undefined}
                    onKeyDown={(ev) => { if (onInspect && (ev.key === "Enter" || ev.key === " ")) onInspect(e.id); }}>
                  <td>{clock(e.timestamp)}</td>
                  <td>{metricLabel(e.event_type)}</td>
                  <td>{e.value} {e.unit}</td>
                  <td>{e.zone}</td>
                  <td>{e.source}</td>
                  <td><SevBadge severity={e.severity} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function WhatChangedTable({ rows }) {
  return (
    <Card title="What changed vs baseline" subtitle="Live reading against the adaptive EWMA baseline">
      {(!rows || rows.length === 0) ? <Empty title="No baseline comparison available" /> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Metric</th><th scope="col">Now</th><th scope="col">Baseline</th>
                <th scope="col">Change</th><th scope="col">Severity</th></tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.metric}>
                  <td>{w.label}<span className="muted small"> · {w.zone}</span></td>
                  <td>{w.value} {w.unit}</td>
                  <td>{w.baseline} {w.unit}</td>
                  <td>{w.direction === "up" ? "▲" : "▼"} {pctText(w.pct_change)}</td>
                  <td><SevBadge severity={w.severity} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}


export function AlertList({ alerts, onAction, busyId }) {
  if (!alerts || alerts.length === 0) {
    return <Empty title="No alerts match the current filters"
                  hint="CityPulse raises WATCH → WARNING → CRITICAL alerts from detected events, and INFO alerts for lifecycle changes." />;
  }
  return (
    <ul className="alert-list">
      {alerts.map((a) => (
        <li key={a.id} className={`alert alert-${(a.level || "info").toLowerCase()}`}>
          <div className="row between wrap">
            <span className="row wrap gap">
              <LevelBadge level={a.level} />
              <b>{a.title}</b>
            </span>
            <span className="muted small">{clock(a.timestamp)} · {a.zone} · {a.id}</span>
          </div>
          <p>{a.message}</p>
          <div className="row wrap gap">
            <StatusPill status={a.status} />
            <button type="button" className="btn ghost" disabled={busyId === a.id || a.status !== "active"}
                    onClick={() => onAction(a.id, "acknowledge")}>Acknowledge</button>
            <button type="button" className="btn ghost danger" disabled={busyId === a.id || a.status === "resolved"}
                    onClick={() => onAction(a.id, "resolve")}>Mark resolved</button>
            {a.disruption_id && <Tag tone="info">Event {a.disruption_id}</Tag>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SourcesTable({ sources, onToggle, busy }) {
  if (!sources || sources.length === 0) return <Empty title="No sources registered" />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th scope="col">Source</th><th scope="col">Status</th><th scope="col">Freshness</th>
            <th scope="col">Latency</th><th scope="col">Readings</th><th scope="col">Error rate</th>
            <th scope="col">Last update</th><th scope="col">Control</th></tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source}>
              <td>{s.source}</td>
              <td><StatusPill status={s.status === "LIVE" ? "LIVE" : "OFFLINE"} /></td>
              <td>{s.freshness_min <= 0 ? "current tick" : `${s.freshness_min * 15} min behind`}</td>
              <td>{s.latency_ms ?? "—"}{s.latency_ms ? " ms" : ""}</td>
              <td>{int(s.event_count)}</td>
              <td>{s.error_rate}%</td>
              <td>{clock(s.last_update)}</td>
              <td>
                <button type="button" className="btn ghost" disabled={busy === s.source}
                        onClick={() => onToggle(s.source, s.status === "LIVE" ? "offline" : "live")}>
                  {busy === s.source ? "Working…" : s.status === "LIVE" ? "Simulate outage" : "Restore feed"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PipelineFlow({ snapshot, conn }) {
  const k = snapshot.kpis || {};
  const coverage = snapshot.coverage || {};
  const sim = snapshot.sim || {};
  const stages = [
    { name: "1 · Simulation", detail: `${sim.scenario ?? "—"} @ ${sim.speed ?? "—"}x`, count: sim.tick ?? 0, unit: "ticks" },
    { name: "2 · Ingestion", detail: `${coverage.metric_streams_live ?? "—"}/${coverage.metric_streams_total ?? "—"} streams`, count: k.events_total ?? 0, unit: "readings" },
    { name: "3 · Analytics", detail: "EWMA baselines per zone × metric", count: (snapshot.what_changed || []).length, unit: "tracked" },
    { name: "4 · Anomaly detection", detail: "z-score + practical floor", count: k.anomalies, unit: "active" },
    { name: "5 · Correlation", detail: "lagged pairs 0/15/30 min", count: k.correlations, unit: "active" },
    { name: "6 · Event fusion", detail: "≥3 signals in one zone", count: k.disruptions, unit: "active" },
    { name: "7 · Alerting", detail: "WATCH → WARNING → CRITICAL", count: k.alerts, unit: "active" },
    { name: "8 · Delivery", detail: conn === "LIVE" ? "WebSocket push" : "REST polling fallback", count: conn, unit: "" },
  ];
  return (
    <ol className="pipeline" aria-label="End-to-end data pipeline">
      {stages.map((s) => (
        <li key={s.name}>
          <span className="stage">{s.name}</span>
          <span className="count">{s.count}</span>
          <span className="muted small">{s.unit}</span>
          <span className="muted small">{s.detail}</span>
        </li>
      ))}
    </ol>
  );
}


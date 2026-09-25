import { useState } from "react";
import { Link } from "react-router-dom";
import CityMap from "../components/CityMap";
import { ActiveEventsPanel, AttentionPanel, EventStream, HealthBreakdown, KpiGrid, RiskPanel, TimelinePanel, TrendChart, WhatChangedTable, WhyNowPanel } from "../components/panels";
import { Card, Empty, Select, Tag } from "../components/ui";
import { int, metricLabel, num } from "../lib/format";

const METRICS = ["rainfall", "traffic", "complaints", "incidents"];

export default function Dashboard({ snapshot, onInspectEvent, onEventAction, busyId }) {
  const [metric, setMetric] = useState("rainfall");
  const d = snapshot;
  const events = d.disruptions || [];
  const focusEvent = events.length ? events.reduce((a, b) => (b.confidence > a.confidence ? b : a)) : null;

  return (
    <div className="stack">
      <AttentionPanel attention={d.attention} eventId={focusEvent?.id} onInspectEvent={onInspectEvent} />
      <KpiGrid kpis={d.kpis} health={d.health} />

      <div className="grid-main">
        <Card
          title="Live city map"
          subtitle="Search zones, switch basemaps (Streets / Satellite / Terrain / Night) and inspect health, anomalies and civic events on stable synthetic coordinates"
          badge={<Tag tone="warn">Simulated</Tag>}
        >
          <CityMap zones={d.zones} anomalies={d.anomalies} events={events} onSelectEvent={(e) => onInspectEvent(e.id)} />
        </Card>

        <WhyNowPanel summary={d.summary} eventId={focusEvent?.id} onInspectEvent={onInspectEvent} />
      </div>

      <ActiveEventsPanel events={events} onInspect={onInspectEvent} onAction={onEventAction} busyId={busyId} />

      <div className="grid-main">
        <TimelinePanel timeline={d.timeline} onInspect={onInspectEvent} />
        <RiskPanel risk={d.risk} />
      </div>

      <div className="grid-main">
        <Card
          title="City health trend"
          subtitle="City health against Zone A's live metric stream (all values from the backend trend table)"
          actions={<Select label="Metric" value={metric} onChange={setMetric} allLabel={null}
                           ariaLabel="Trend metric"
                           options={METRICS.map((m) => ({ value: m, label: metricLabel(m) }))} />}
        >
          <TrendChart trend={d.trend} metric={metric} />
        </Card>
        <HealthBreakdown health={d.health} />
      </div>

      <div className="grid-main">
        <WhatChangedTable rows={d.what_changed} />
        <Card title="Prototype trend prediction" subtitle="Least-squares over the last 30 simulated minutes (+30 min estimate)">
          {(d.predictions?.items || []).length === 0 ? (
            <Empty title="Not enough history for a prediction"
                   hint="Predictions need at least 5 samples of a metric for the selected zone." />
          ) : (
            <ul className="prediction">
              {d.predictions.items.map((p) => (
                <li key={p.metric}>
                  <div className="row between wrap">
                    <span><b>{p.label}</b> <span className="muted small">· {p.zone}</span></span>
                    <span>{p.trend === "up" ? "▲" : p.trend === "down" ? "▼" : "■"} {p.trend_strength}</span>
                  </div>
                  <div className="muted small">
                    now {num(p.current)} {p.unit} · est. {p.range_low}–{p.range_high} {p.unit} in {p.horizon_min ?? 30} min
                    {" · "}{p.model} · confidence {p.confidence}%
                  </div>
                  <div className="muted small">{p.text}</div>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">{d.predictions?.note}</p>
        </Card>
      </div>

      <div className="grid-main">
        <EventStream events={d.events} onInspect={onInspectEvent} />
        <Card title="Possible links" subtitle="Lagged signal relationships per zone — association only, never causation"
              badge={<Tag tone="info">Correlation ≠ causation</Tag>}>
          {(d.correlations || []).length === 0 ? (
            <Empty title="No active multi-signal patterns"
                   hint="A pattern needs at least two anomaly signals from two independent sources." />
          ) : (
            (d.correlations || []).map((c) => (
              <div key={c.id} className="link-item">
                <div className="row between wrap">
                  <b>{c.zone}</b>
                  <span className="muted small">confidence {c.confidence}% · {c.signal_count} signals · {c.co_active_min} min co-active</span>
                </div>
                <p className="muted small">{c.note}</p>
                <ul className="evidence">
                  {(c.evidence || []).slice(0, 4).map((e, i) => <li key={i}><span>{e.text}</span></li>)}
                </ul>
              </div>
            ))
          )}
        </Card>
      </div>

      <Card title="Zone overview" subtitle="Per-zone health, risk and live readings (synthetic)">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Zone</th><th scope="col">Health</th><th scope="col">Risk</th>
                <th scope="col">Anomalies</th><th scope="col">Readings</th><th scope="col">Event confidence</th>
              </tr>
            </thead>
            <tbody>
              {(d.zones || []).map((z) => (
                <tr key={z.zone}>
                  <td><b>{z.zone}</b></td>
                  <td>{z.health}/100</td>
                  <td>{z.risk}{z.risk_band ? <Tag tone={z.risk_band === "CRITICAL" || z.risk_band === "HIGH" ? "warn" : "info"}> {z.risk_band}</Tag> : null}</td>
                  <td>{z.anomalies}</td>
                  <td className="muted small">
                    {Object.entries(z.metrics || {}).map(([k, v]) => `${metricLabel(k)} ${v}`).join(" · ")}
                  </td>
                  <td>{z.event_confidence != null ? `${z.event_confidence}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Total readings processed this run: {int(d.kpis?.events_total)} ·{" "}
          <Link to="/simulation">open simulation controls</Link> to drive the pipeline end to end.
        </p>
      </Card>
    </div>
  );
}

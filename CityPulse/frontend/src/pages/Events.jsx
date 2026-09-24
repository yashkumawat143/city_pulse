import { useCallback, useState } from "react";
import api from "../lib/api";
import { useApiQuery, useDebounced } from "../hooks/useApiQuery";
import {
  Card, Empty, ErrorState, FilterBar, Loading, SearchBox, Select, SevBadge, StatusPill, Tag,
} from "../components/ui";
import { clock, num, metricLabel, metricUnit, SEVERITIES } from "../lib/format";

const ZONES = ["Zone A", "Zone B", "Zone C"];
const METRICS = ["rainfall", "traffic", "complaints", "incidents"];
const TABS = [["events", "Civic events"], ["readings", "Signal readings"]];

export default function Events({ snapshot, onInspectEvent, onEventAction, busyId }) {
  const [tab, setTab] = useState("events");

  const [q, setQ] = useState("");
  const dq = useDebounced(q, 300);
  const [status, setStatus] = useState("all");
  const [zone, setZone] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [metric, setMetric] = useState("all");

  const [rq, setRq] = useState("");
  const drq = useDebounced(rq, 300);
  const [rZone, setRZone] = useState("all");
  const [rSev, setRSev] = useState("all");
  const [rMetric, setRMetric] = useState("all");
  const [minutes, setMinutes] = useState("60");

  const fetchEvents = useCallback(
    () => api.disruptions({ q: dq, status, zone, severity, metric, limit: 200 }),
    [dq, status, zone, severity, metric],
  );
  const fetchReadings = useCallback(
    () => api.events({ q: drq, zone: rZone, severity: rSev, event_type: rMetric, minutes, limit: 200 }),
    [drq, rZone, rSev, rMetric, minutes],
  );

  const evQ = useApiQuery(fetchEvents, [dq, status, zone, severity, metric],
                          { intervalMs: 5000, enabled: tab === "events" });
  const rdQ = useApiQuery(fetchReadings, [drq, rZone, rSev, rMetric, minutes],
                          { intervalMs: 5000, enabled: tab === "readings" });

  const filtersActive = Boolean(q || status !== "all" || zone !== "all" || severity !== "all" || metric !== "all");

  return (
    <div className="stack">
      <div className="tabs" role="tablist" aria-label="Event views">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id}
                  className={tab === id ? "tab active" : "tab"} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "events" && (
        <EventSearchCard {...{ evQ, q, setQ, status, setStatus, zone, setZone, severity, setSeverity, metric, setMetric,
                               filtersActive, onInspectEvent, onEventAction, busyId }} />
      )}
      {tab === "readings" && (
        <ReadingsCard {...{ rdQ, rq, setRq, rZone, setRZone, rSev, setRSev, rMetric, setRMetric, minutes, setMinutes }} />
      )}
      <CorrelationsCard snapshot={snapshot} />
    </div>
  );
}

function EventSearchCard({ evQ, q, setQ, status, setStatus, zone, setZone, severity, setSeverity, metric, setMetric,
                           filtersActive, onInspectEvent, onEventAction, busyId }) {
  return (
    <Card
      title="Civic event search"
      subtitle="Backend lifecycle records — search by text, zone, severity, status and signal type"
      badge={<Tag tone="info">{(evQ.data || []).length} records</Tag>}
    >
      <FilterBar active={filtersActive}
                 onReset={() => { setQ(""); setStatus("all"); setZone("all"); setSeverity("all"); setMetric("all"); }}>
        <SearchBox label="Search events" value={q} onChange={setQ} placeholder="event id, zone, state, note…" />
        <Select label="Status" value={status} onChange={setStatus} allLabel="All statuses"
                options={[{ value: "active", label: "Active" }, { value: "acknowledged", label: "Acknowledged" },
                          { value: "resolved", label: "Resolved" }]} />
        <Select label="Zone" value={zone} onChange={setZone} options={ZONES} allLabel="All zones" />
        <Select label="Severity" value={severity} onChange={setSeverity} allLabel="All severities" options={SEVERITIES} />
        <Select label="Signal type" value={metric} onChange={setMetric} allLabel="Any signal type"
                options={METRICS.map((m) => ({ value: m, label: metricLabel(m) }))} />
      </FilterBar>

      {evQ.loading && !evQ.data && <Loading label="Loading civic events…" />}
      {evQ.error && <ErrorState message={evQ.error} onRetry={evQ.reload}
                                hint="Check that the backend is running and reachable (see README)." />}
      {evQ.data && evQ.data.length === 0 && (
        <Empty title="No civic events match these filters"
               hint={filtersActive ? "Try widening the filters, or reset them."
                                   : "No event detected yet. Start the full disruption scenario in Simulation."} />
      )}
      {evQ.data && evQ.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Event</th><th scope="col">Zone</th><th scope="col">State</th>
                <th scope="col">Status</th><th scope="col">Severity</th><th scope="col">Confidence</th>
                <th scope="col">Duration</th><th scope="col">Started</th><th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {evQ.data.map((e) => (
                <tr key={e.id}>
                  <td><button type="button" className="link-btn" onClick={() => onInspectEvent(e.id)}>{e.id}</button></td>
                  <td>{e.zone}</td>
                  <td>{e.state}</td>
                  <td><StatusPill status={e.status} /></td>
                  <td><SevBadge severity={e.severity} compact /></td>
                  <td>{Math.round(e.confidence)}%</td>
                  <td>{e.duration_min} min</td>
                  <td>{clock(e.started)}</td>
                  <td>
                    <span className="row gap">
                      <button type="button" className="btn ghost" disabled={busyId === e.id || e.status !== "active"}
                              onClick={() => onEventAction(e.id, "acknowledge")}>Ack</button>
                      <button type="button" className="btn ghost danger"
                              disabled={busyId === e.id || e.status === "resolved"}
                              onClick={() => onEventAction(e.id, "resolve")}>Resolve</button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        Acknowledging marks an event as seen by an operator but keeps it updating; resolving closes it. Both write
        to backend state and raise an audit alert.
      </p>
    </Card>
  );
}


function ReadingsCard({ rdQ, rq, setRq, rZone, setRZone, rSev, setRSev, rMetric, setRMetric, minutes, setMinutes }) {
  return (
    <Card title="Signal readings" subtitle="Individual anomalous measurements emitted by the ingestion pipeline"
          badge={<Tag tone="info">{(rdQ.data || []).length} readings</Tag>}>
      <FilterBar
        active={Boolean(rq || rZone !== "all" || rSev !== "all" || rMetric !== "all" || minutes !== "60")}
        onReset={() => { setRq(""); setRZone("all"); setRSev("all"); setRMetric("all"); setMinutes("60"); }}
      >
        <SearchBox label="Search readings" value={rq} onChange={setRq} placeholder="event id, metric, zone…" />
        <Select label="Metric" value={rMetric} onChange={setRMetric} allLabel="All metrics"
                options={METRICS.map((m) => ({ value: m, label: metricLabel(m) }))} />
        <Select label="Zone" value={rZone} onChange={setRZone} options={ZONES} allLabel="All zones" />
        <Select label="Severity" value={rSev} onChange={setRSev} allLabel="All severities" options={SEVERITIES} />
        <Select label="Window" value={minutes} onChange={setMinutes} allLabel={null}
                options={[{ value: "30", label: "last 30 min" }, { value: "60", label: "last 60 min" },
                          { value: "180", label: "last 3 h" }, { value: "720", label: "last 12 h" }]} />
      </FilterBar>

      {rdQ.loading && !rdQ.data && <Loading label="Loading readings…" />}
      {rdQ.error && <ErrorState message={rdQ.error} onRetry={rdQ.reload} />}
      {rdQ.data && rdQ.data.length === 0 && (
        <Empty title="No readings in this window"
               hint="Only readings that breach the anomaly threshold and the practical floor are emitted here." />
      )}
      {rdQ.data && rdQ.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Time</th><th scope="col">Metric</th><th scope="col">Value</th>
                <th scope="col">Zone</th><th scope="col">Source</th><th scope="col">Severity</th>
                <th scope="col">Z-score</th><th scope="col">Event</th></tr>
            </thead>
            <tbody>
              {rdQ.data.map((e) => (
                <tr key={e.id}>
                  <td>{clock(e.timestamp)}</td>
                  <td>{metricLabel(e.event_type)}</td>
                  <td>{e.value} {e.unit}</td>
                  <td>{e.zone}</td>
                  <td>{e.source}</td>
                  <td><SevBadge severity={e.severity} compact /></td>
                  <td>{num(e.metadata?.z_score, 2)}</td>
                  <td>{e.metadata?.anomaly_id || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        Expected units — {METRICS.map((m) => `${metricLabel(m)}: ${metricUnit(m)}`).join(" · ")}. The window uses
        simulated city minutes (1 tick = 15 min).
      </p>
    </Card>
  );
}

function CorrelationsCard({ snapshot }) {
  const rows = snapshot.correlations || [];
  return (
    <Card title="Active correlation links" subtitle="Possible multi-signal patterns behind the events above"
          badge={<Tag tone="info">Correlation ≠ causation</Tag>}>
      {rows.length === 0
        ? <Empty title="No active correlation right now"
                 hint="A pattern needs at least two anomaly signals from two independent sources in one zone." />
        : (
          <ul className="evidence">
            {rows.map((c) => (
              <li key={c.id}>
                <Tag tone="info">{c.zone}</Tag>
                <span>
                  {(c.metrics || []).map(metricLabel).join(" + ")} · confidence {c.confidence}% · co-active{" "}
                  {c.co_active_min} min · sources {(c.sources || []).join(", ")}
                </span>
              </li>
            ))}
          </ul>
        )}
    </Card>
  );
}


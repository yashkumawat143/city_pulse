import { useCallback, useMemo, useState } from "react";
import api from "../lib/api";
import { useApiQuery, useDebounced } from "../hooks/useApiQuery";
import { Card, Empty, ErrorState, FilterBar, Loading, SearchBox, Select, SevBadge, Tag } from "../components/ui";
import { clock, metricLabel, metricUnit, num, pctText, SEVERITIES } from "../lib/format";

const ZONES = ["Zone A", "Zone B", "Zone C"];
const METRICS = ["rainfall", "traffic", "complaints", "incidents"];

export default function Anomalies({ config }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const [status, setStatus] = useState("active");
  const [zone, setZone] = useState("all");
  const [metric, setMetric] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [open, setOpen] = useState(null);

  const fetcher = useCallback(
    () => api.anomalies({ status, zone, metric, severity, limit: 300 }),
    [status, zone, metric, severity],
  );
  const { data, error, loading, reload } = useApiQuery(fetcher, [status, zone, metric, severity], { intervalMs: 4000 });

  const rows = useMemo(() => {
    const list = data || [];
    if (!dq) return list;
    const needle = dq.toLowerCase();
    return list.filter((a) => JSON.stringify(a).toLowerCase().includes(needle));
  }, [data, dq]);

  const active = Boolean(q || status !== "active" || zone !== "all" || metric !== "all" || severity !== "all");
  const opened = rows.find((a) => a.id === open);

  return (
    <div className="stack">
      <Card
        title="Anomaly centre"
        subtitle="Adaptive EWMA baselines per zone and metric. A reading is reported when it exceeds the statistical threshold AND a practical significance floor."
        badge={<Tag tone="info">{rows.length} rows</Tag>}
        actions={<button type="button" className="btn ghost" onClick={reload}>⟳ Refresh</button>}
      >
        <FilterBar active={active}
                   onReset={() => { setQ(""); setStatus("active"); setZone("all"); setMetric("all"); setSeverity("all"); }}>
          <SearchBox label="Search anomalies" value={q} onChange={setQ} placeholder="zone, metric, source…" />
          <Select label="Status" value={status} onChange={setStatus} allLabel="Any status"
                  options={[{ value: "active", label: "Active only" }, { value: "resolved", label: "Resolved only" }]} />
          <Select label="Zone" value={zone} onChange={setZone} options={ZONES} allLabel="All zones" />
          <Select label="Metric" value={metric} onChange={setMetric} allLabel="All metrics"
                  options={METRICS.map((m) => ({ value: m, label: metricLabel(m) }))} />
          <Select label="Severity" value={severity} onChange={setSeverity} allLabel="All severities" options={SEVERITIES} />
        </FilterBar>

        {loading && !data && <Loading label="Loading anomalies…" />}
        {error && <ErrorState message={error} onRetry={reload} />}
        {data && rows.length === 0 && (
          <Empty title="No anomalies match the current filters"
                 hint={active ? "Adjust or reset the filters."
                              : "All monitored signals are within expected ranges — the normal state of a healthy city."} />
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Metric</th><th scope="col">Zone</th><th scope="col">Baseline</th>
                  <th scope="col">Current</th><th scope="col">Change</th><th scope="col">Z-score</th>
                  <th scope="col">Score</th>
                  <th scope="col">Severity</th><th scope="col">Persistence</th><th scope="col">First seen</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>{metricLabel(a.metric)}<span className="muted small"> · {a.source}</span></td>
                    <td>{a.zone}</td>
                    <td>{a.baseline} {a.unit}</td>
                    <td>{a.current} {a.unit}</td>
                    <td>{pctText(a.pct_change)}</td>
                    <td>{num(a.z_score, 2)}</td>
                    <td title={a.ml_anomaly_score != null ? `ML IsolationForest: ${a.ml_anomaly_score}/100` : "ML layer warming up"}>
                      <b>{a.anomaly_score ?? "—"}</b>
                      <span className="muted small"> {a.score_band || ""}</span>
                    </td>
                    <td><SevBadge severity={a.severity} compact /></td>
                    <td>{a.consecutive_steps} × 1 min</td>
                    <td>{clock(a.timestamp)}</td>
                    <td>
                      <button type="button" className="btn ghost" aria-expanded={open === a.id}
                              onClick={() => setOpen(open === a.id ? null : a.id)}>
                        {open === a.id ? "Hide" : "Explain"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {opened && (
          <div className="explain">
            <h3 className="sub-title">Why this is flagged</h3>
            <p>{opened.explanation || "No explanation recorded for this reading."}</p>
            <dl className="kv compact">
              <div><dt>Threshold</dt><dd>{opened.threshold ?? "—"} {opened.unit}</dd></div>
              <div><dt>Deviation</dt><dd>{opened.deviation} {opened.unit}</dd></div>
              <div><dt>Signal strength</dt><dd>{num(opened.strength, 2)} (0-1, derived from |z| / 6)</dd></div>
              <div><dt>Anomaly score</dt><dd>{opened.anomaly_score ?? "—"}/100 · {opened.score_band || "—"}</dd></div>
              <div><dt>ML layer (Isolation Forest)</dt><dd>{opened.ml_anomaly_score != null
                ? `${opened.ml_anomaly_score}/100${opened.ml_flagged ? " · flagged as outlier" : " · within cluster"}`
                : "warming up (needs 30 clean rows)"}</dd></div>
              <div><dt>Rolling 15/30/60 min</dt><dd>{[opened.rolling_15, opened.rolling_30, opened.rolling_60].map((v) => v ?? "—").join(" / ")} {opened.unit}</dd></div>
              <div><dt>Coordinates</dt><dd>{opened.latitude}, {opened.longitude}</dd></div>
              <div><dt>Anomaly id</dt><dd>{opened.id}</dd></div>
              <div><dt>Last update</dt><dd>{clock(opened.updated)}</dd></div>
            </dl>
          </div>
        )}
      </Card>

      <ConfigCard config={config} />
    </div>
  );
}

function ConfigCard({ config }) {
  return (
    <Card title="Detection configuration" subtitle="Live thresholds used by the engine (GET /api/config)">
      {!config ? <Loading label="Loading configuration…" rows={2} /> : (
        <>
          <dl className="kv">
            <div><dt>Method</dt><dd>{config.anomaly.method}</dd></div>
            <div><dt>Z threshold</dt><dd>{config.anomaly.z_threshold}σ</dd></div>
            <div><dt>Extra persistence</dt><dd>{config.anomaly.extra_persistence_ticks} extra tick(s) required</dd></div>
            <div><dt>Correlation</dt><dd>{config.correlation.method} · lags {config.correlation.lags_minutes.join("/")} min</dd></div>
            {config.anomaly.score && (
              <div><dt>Anomaly score</dt><dd>{config.anomaly.score.method} · bands {Object.entries(config.anomaly.score.bands).map(([k, v]) => `${k}≤${v}`).join(", ")}</dd></div>
            )}
            {config.anomaly.ml?.available && (
              <div><dt>ML layer</dt><dd>{config.anomaly.ml.model} · window {config.anomaly.ml.window_min} min · contamination {config.anomaly.ml.contamination} · refit every {config.anomaly.ml.refit_ticks ?? "—"} ticks</dd></div>
            )}
            {config.risk && (
              <div><dt>Risk bands</dt><dd>LOW ≤{config.risk.bands.low} · MODERATE ≤{config.risk.bands.moderate} · HIGH ≤{config.risk.bands.high} · CRITICAL &gt;{config.risk.bands.high}</dd></div>
            )}
          </dl>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Metric</th><th scope="col">Source</th><th scope="col">Unit</th>
                  <th scope="col">Baseline</th><th scope="col">Practical floor</th><th scope="col">Direction</th></tr>
              </thead>
              <tbody>
                {config.metrics.map((m) => (
                  <tr key={m.metric}>
                    <td>{m.label}</td><td>{m.source}</td><td>{m.unit}</td>
                    <td>{m.baseline}</td><td>{m.practical_floor}</td><td>{m.direction} baseline</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            {config.anomaly.note} Measured units — {METRICS.map((m) => `${metricLabel(m)} (${metricUnit(m)})`).join(", ")}.
          </p>
        </>
      )}
    </Card>
  );
}


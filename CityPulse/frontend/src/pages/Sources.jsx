import { useCallback, useState } from "react";
import api from "../lib/api";
import { useApiQuery } from "../hooks/useApiQuery";
import { SourcesTable } from "../components/panels";
import { Card, Empty, ErrorState, Loading, Tag } from "../components/ui";
import { cityTime, clock } from "../lib/format";

export default function Sources({ snapshot, config, conn, refresh }) {
  const fetchSources = useCallback(() => api.sources(), []);
  const { data, error, loading, reload } = useApiQuery(fetchSources, [], { intervalMs: 5000 });
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);

  const toggle = async (source, status) => {
    setBusy(source);
    setActionError(null);
    try {
      await api.simSource(source, status);
      await reload();
      refresh?.();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const cov = snapshot?.coverage;

  return (
    <div className="stack">
      <Card title="Data provenance" subtitle="Every value in CityPulse comes from the local simulation engine"
            badge={<Tag tone="warn">Simulated</Tag>}>
        <dl className="kv">
          <div><dt>Data mode</dt><dd>{cov?.mode || "simulation"} — synthetic city telemetry</dd></div>
          <div><dt>External integrations</dt><dd>None connected (no government, sensor or weather API)</dd></div>
          <div><dt>Coverage</dt><dd>{cov?.coverage_pct ?? "—"}% of {cov?.metric_streams_total ?? "—"} metric streams live</dd></div>
          <div><dt>City clock</dt><dd>{cityTime(cov?.city_time)} (1 tick = 15 simulated minutes)</dd></div>
          <div><dt>Tick / scenario</dt><dd>{cov?.tick ?? "—"} · {cov?.scenario || "—"} · {cov?.speed ?? "—"}x</dd></div>
          <div><dt>History depth</dt><dd>{cov?.history_points ?? 0} samples per zone/metric</dd></div>
          <div><dt>Delivery channel</dt><dd>{conn === "LIVE" ? "WebSocket push" : `${conn} (REST fallback active)`}</dd></div>
          <div><dt>Payload generated</dt><dd>{clock(snapshot?.generated_at)}</dd></div>
        </dl>
        <p className="muted small">{cov?.disclaimer}</p>
      </Card>

      <Card title="Source health" subtitle="Latency, freshness and per-source outages (all synthetic)" badge={data && <Tag tone="info">{data.length} feeds</Tag>}>
        {actionError && <p className="inline-error" role="alert">{actionError}</p>}
        {loading && !data && <Loading label="Loading sources…" />}
        {error && <ErrorState message={error} onRetry={reload} />}
        {data && data.length === 0 && <Empty title="No sources registered" />}
        {data && data.length > 0 && (
          <>
            <SourcesTable sources={data} onToggle={toggle} busy={busy} />
            <p className="muted small">
              Simulating an outage stops that feed from producing readings: its active anomalies are resolved, its
              health component drops out of the city score (weights re-normalise) and coverage falls. The remaining
              feeds keep running — this exercises the “missing data” path of the anomaly engine.
            </p>
          </>
        )}
      </Card>

      {config && (
        <Card title="Configuration reference" subtitle="Thresholds and weights exposed by GET /api/config">
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Section</th><th scope="col">Setting</th><th scope="col">Value</th></tr></thead>
              <tbody>
                <tr><td>Anomaly</td><td>z threshold</td><td>{config.anomaly.z_threshold}σ</td></tr>
                <tr><td>Anomaly</td><td>extra persistence</td><td>{config.anomaly.extra_persistence_ticks} tick(s)</td></tr>
                <tr><td>Correlation</td><td>lags</td><td>{config.correlation.lags_minutes.join(", ")} min</td></tr>
                <tr><td>Correlation</td><td>minimum samples</td><td>{config.correlation.min_samples}</td></tr>
                <tr><td>Events</td><td>minimum signals / confidence</td>
                  <td>{config.events.min_signals} signals · {config.events.min_confidence}% confidence</td></tr>
                <tr><td>Health</td><td>weights</td>
                  <td>{Object.entries(config.health.weights).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(" · ")}</td></tr>
                <tr><td>Health</td><td>bands</td>
                  <td>{Object.entries(config.health.bands).map(([k, v]) => `${k} ${v}`).join(" · ")}</td></tr>
                <tr><td>Engine</td><td>tick length</td>
                  <td>{config.tick_minutes} simulated minutes per tick</td></tr>
              </tbody>
            </table>
          </div>
          <p className="muted small">{config.disclaimer}</p>
        </Card>
      )}
    </div>
  );
}

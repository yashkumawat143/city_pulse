import { useState } from "react";
import api from "../lib/api";
import { PipelineFlow, SourcesTable } from "../components/panels";
import { Card, Empty, Field, Loading, SevBadge, StatusPill, Tag } from "../components/ui";
import { cityTime, clock } from "../lib/format";

const SCENARIOS = [
  { value: "normal", label: "normal — quiet city" },
  { value: "heavy_rain", label: "heavy rain" },
  { value: "urban_flooding", label: "urban flooding" },
  { value: "traffic_incident", label: "traffic incident" },
  { value: "full_disruption", label: "full civic disruption (demo)" },
];
const SPEEDS = [0.5, 1, 2, 5, 10];

export default function Simulation({ snapshot, refresh, config, conn }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const sim = snapshot.sim;

  const run = async (label, fn) => {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      const res = await fn();
      setMessage(`${label} → ${res?.status ? `${res.status} @ ${res.speed}x · ${res.scenario}` : "done"}`);
      refresh?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const sourceToggle = async (source, status) => {
    setBusy(source);
    setError(null);
    try {
      await api.simSource(source, status);
      setMessage(`${source} feed → ${status}`);
      refresh?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      <Card
        title="Simulation control"
        subtitle="Drives the real backend pipeline — simulation → ingestion → analytics → anomaly detection → correlation → event lifecycle → API/WebSocket"
        badge={<Tag tone="warn">Synthetic · fictional city</Tag>}
      >
        <div className="row wrap gap">
          <StatusPill status={sim.status} />
          <Tag tone="info">scenario {sim.scenario}</Tag>
          <Tag tone="info">T+{sim.scenario_time} sim min</Tag>
          <Tag tone="info">{sim.speed}x</Tag>
          <Tag tone="info">tick {sim.tick}</Tag>
          <Tag tone="info">seed {sim.seed}</Tag>
          <Tag tone="muted">city clock {cityTime(sim.simulation_time)}</Tag>
        </div>

        <div className="row wrap gap controls">
          <button type="button" className="btn primary big" disabled={busy !== null}
                  onClick={() => run("Run full civic disruption", () => api.sim("demo", { speed: 5 }))}>
            {busy === "Run full civic disruption" ? "Starting…" : "▶ Run full civic disruption (5x)"}
          </button>
          <button type="button" className="btn" disabled={busy !== null || sim.status === "running"}
                  onClick={() => run("Resume", () => api.sim("resume"))}>▶ Resume</button>
          <button type="button" className="btn" disabled={busy !== null || sim.status === "paused"}
                  onClick={() => run("Pause", () => api.sim("pause"))}>⏸ Pause</button>
          <button type="button" className="btn" disabled={busy !== null}
                  onClick={() => run("Step", () => api.sim("step"))}>⏭ Step one tick (15 min)</button>
          <button type="button" className="btn ghost" disabled={busy !== null}
                  onClick={() => run("Reset", () => api.sim("reset"))}>⟲ Reset</button>
          <button type="button" className="btn ghost" disabled={busy !== null}
                  onClick={() => run("Restart", () => api.sim("restart"))}>⟳ Restart</button>
        </div>

        {message && <p className="inline-ok" role="status">{message}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}

        <div className="row wrap gap controls">
          <Field label="Scenario" hint="Switching scenario restarts the run from the current seed">
            <select aria-label="Scenario" value={sim.scenario} disabled={busy !== null}
                    onChange={(e) => run("Scenario", () => api.simScenario(e.target.value))}>
              {SCENARIOS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Speed" hint="1 tick = 15 simulated minutes; 10x ≈ 1 tick per second">
            <select aria-label="Speed" value={sim.speed} disabled={busy !== null}
                    onChange={(e) => run("Speed", () => api.simSpeed(Number(e.target.value)))}>
              {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
            </select>
          </Field>
        </div>

        <p className="muted small">
          These controls call the backend (<code>/api/simulation/*</code>). Nothing is simulated in the browser — every
          change is computed by the Python engine and pushed back over WebSocket (or fetched by the REST fallback
          while the socket reconnects).
        </p>
      </Card>

      <Card title="Pipeline status" subtitle="Live counts at each stage of the real processing chain"
            badge={<Tag tone={conn === "LIVE" ? "info" : "warn"}>{conn === "LIVE" ? "Live push" : "REST fallback"}</Tag>}>
        <PipelineFlow snapshot={snapshot} conn={conn} />
      </Card>

      <SimulationTail snapshot={snapshot} sourceToggle={sourceToggle} busy={busy} config={config} />
    </div>
  );
}

function SimulationTail({ snapshot, sourceToggle, busy, config }) {
  return (
    <>
      <div className="grid-main">
        <Card title="Feed controls" subtitle="Simulate a source outage to exercise missing-data handling">
          <SourcesTable sources={snapshot.sources} onToggle={sourceToggle} busy={busy} />
        </Card>

        <Card title="Recent civic events" subtitle="Lifecycle records created by the engine (including resolved)">
          {(snapshot.recent_events || []).length === 0
            ? <Empty title="No civic events yet"
                     hint="Run the full civic disruption scenario and watch events appear here." />
            : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th scope="col">Event</th><th scope="col">Zone</th><th scope="col">State</th>
                      <th scope="col">Status</th><th scope="col">Severity</th><th scope="col">Started</th></tr>
                  </thead>
                  <tbody>
                    {snapshot.recent_events.map((e) => (
                      <tr key={e.id}>
                        <td>{e.id}</td><td>{e.zone}</td><td>{e.state}</td>
                        <td><StatusPill status={e.status} /></td>
                        <td><SevBadge severity={e.severity} compact /></td>
                        <td>{clock(e.started)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
      </div>

      {config ? (
        <Card title="How the demo behaves" subtitle="Expected sequence for the full civic disruption scenario">
          <ol className="why">
            <li>Rainfall in Zone A rises first; the EWMA baseline stays at the pre-storm level, so rainfall is flagged as an anomaly.</li>
            <li>Traffic congestion follows with a lag of roughly 15 simulated minutes, then complaint volume and road incidents.</li>
            <li>With ≥{config.events.min_signals} co-active signals and ≥{config.events.min_confidence}% prototype confidence, a civic event is fused and a WATCH alert is raised.</li>
            <li>The event escalates (ESCALATING → PEAK), alerts rise to CRITICAL, and the weighted city health score falls.</li>
            <li>After the storm curve decays the event moves to RECOVERING and finally RESOLVED, and health returns toward HEALTHY.</li>
          </ol>
          <p className="muted small">
            Trigger thresholds — anomaly z ≥ {config.anomaly.z_threshold}σ plus a per-metric floor; event fusion needs{" "}
            {config.events.min_signals} signals, mean z ≥ {config.events.min_mean_z} and confidence ≥{" "}
            {config.events.min_confidence}%. Confidence is a prototype score, not a probability.
          </p>
        </Card>
      ) : (
        <Card title="Configuration"><Loading label="Loading engine configuration…" rows={2} /></Card>
      )}
    </>
  );
}


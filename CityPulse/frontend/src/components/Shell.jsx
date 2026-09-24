import { useState } from "react";
import { NavLink } from "react-router-dom";
import { cityTime, clock } from "../lib/format";
import { StatusPill, Tag } from "./ui";

export const NAV = [
  ["/", "Dashboard"],
  ["/events", "Events"],
  ["/anomalies", "Anomalies"],
  ["/alerts", "Alerts"],
  ["/sources", "Sources"],
  ["/simulation", "Simulation"],
];

export function TopBar({ conn, lastUpdate, snapshot, onRefresh }) {
  const [open, setOpen] = useState(false);
  return (
    <header className="top">
      <div className="brand">
        <span className="logo" aria-hidden="true">◉</span>
        <span>
          <b>CITYPULSE</b>
          <small>Smart city intelligence command centre</small>
        </span>
      </div>

      <nav aria-label="Main navigation">
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>
        ))}
      </nav>

      <div className="top-status">
        <StatusPill status={conn} />
        <span className="muted small" title="Last successful data update">
          {lastUpdate ? `updated ${lastUpdate.toLocaleTimeString()}` : "waiting for data…"}
        </span>
        <button type="button" className="btn ghost" onClick={onRefresh} title="Re-sync with the backend now">
          ⟳ Sync
        </button>
        <button type="button" className="btn ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          Data source
        </button>
      </div>

      {open && (
        <div className="transparency" role="region" aria-label="Data transparency">
          <div className="row wrap gap">
            <Tag tone="warn">SIMULATED DATA</Tag>
            <Tag tone="info">{snapshot?.coverage?.source_kind || "synthetic city telemetry"}</Tag>
            <Tag tone="muted">No external or government API connected</Tag>
          </div>
          <dl className="kv compact">
            <div><dt>Data mode</dt><dd>{snapshot?.coverage?.mode || "simulation"}</dd></div>
            <div><dt>City clock</dt><dd>{cityTime(snapshot?.coverage?.city_time)} (1 tick = 15 simulated min)</dd></div>
            <div><dt>Tick</dt><dd>{snapshot?.coverage?.tick ?? "—"} · scenario {snapshot?.coverage?.scenario || "—"} · {snapshot?.coverage?.speed || "—"}x</dd></div>
            <div><dt>Coverage</dt><dd>{snapshot?.coverage?.coverage_pct ?? "—"}% of metric streams live
              {snapshot?.coverage?.offline_sources?.length ? ` (offline: ${snapshot.coverage.offline_sources.join(", ")})` : ""}</dd></div>
            <div><dt>History</dt><dd>{snapshot?.coverage?.history_points ?? 0} samples per zone/metric</dd></div>
            <div><dt>Delivery</dt><dd>{conn === "LIVE" ? "WebSocket push" : `${conn} — REST fallback active`}</dd></div>
            <div><dt>Last payload</dt><dd>{clock(snapshot?.generated_at)}</dd></div>
          </dl>
          <p className="muted small">{snapshot?.coverage?.disclaimer}</p>
        </div>
      )}
    </header>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <p>
        CityPulse prototype · synthetic data for a fictional city (Zone A/B/C) · correlations are shown as
        possible links, never as causes · Event Confidence and the city health score are prototype indicators,
        not official metrics · trend predictions are prototype estimates.
      </p>
    </footer>
  );
}

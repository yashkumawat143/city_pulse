/**
 * CityPulse frontend/backend contract check.
 * Verifies that every field the React views read actually exists in the live API
 * payloads, so a backend change cannot silently break the dashboard.
 *
 *   cd frontend
 *   node scripts/contract-check.mjs            (backend must be running on :8000)
 *   CITYPULSE_URL=http://127.0.0.1:8010 node scripts/contract-check.mjs
 */
const BASE = (process.env.CITYPULSE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

let passed = 0;
const failures = [];

function ok(cond, label, extra = "") {
  if (cond) {
    passed += 1;
    console.log(`  PASS  ${label}${extra ? `  [${extra}]` : ""}`);
  } else {
    failures.push(label);
    console.log(`  FAIL  ${label}${extra ? `  [${extra}]` : ""}`);
  }
}

const has = (obj, path) => {
  let cur = obj;
  for (const part of path.split(".")) {
    if (cur === null || cur === undefined) return false;
    cur = cur[part];
  }
  return cur !== null && cur !== undefined;
};

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

const REQUIRED = {
  "/api/health": ["status", "version", "data_mode", "simulated", "tick", "simulation_status"],
  "/api/config": ["product", "version", "data_mode", "metrics", "anomaly.z_threshold", "anomaly.floors",
                  "correlation.lags_minutes", "correlation.min_samples", "events.min_signals",
                  "events.min_confidence", "events.min_mean_z", "health.weights", "health.bands",
                  "sources", "scenarios", "speeds", "tick_minutes"],
  "/api/dashboard": ["health.score", "health.status", "health.components", "health.weights_used",
                     "health.penalty_anomalies", "health.penalty_disruptions",
                     "kpis.anomalies", "kpis.disruptions", "kpis.correlations", "kpis.alerts",
                     "kpis.sources_live", "kpis.sources_total", "kpis.events_total",
                     "kpis.events_acknowledged", "kpis.events_resolved",
                     "zones", "anomalies", "correlations", "disruptions", "recent_events", "alerts",
                     "sources", "events", "trend", "what_changed", "predictions.items", "predictions.note",
                     "summary.headline", "summary.lines", "summary.text",
                     "sim.status", "sim.scenario", "sim.speed", "sim.tick", "sim.seed", "sim.simulation_time",
                     "coverage.mode", "coverage.metric_streams_live", "coverage.metric_streams_total",
                     "coverage.coverage_pct", "coverage.history_points", "coverage.disclaimer", "generated_at"],
  "/api/disruptions": [],
  "/api/alerts": [],
  "/api/anomalies": [],
  "/api/events?limit=5": [],
  "/api/sources": [],
  "/api/trends?minutes=30": [],
};

const main = async () => {
  console.log(`Contract check against ${BASE}\n`);
  let dash = null;
  for (const [path, fields] of Object.entries(REQUIRED)) {
    let body;
    try {
      body = await get(path);
    } catch (e) {
      ok(false, `GET ${path}`, e.message);
      continue;
    }
    ok(true, `GET ${path} reachable`);
    fields.forEach((f) => ok(has(body, f), `${path} → ${f}`));
    if (path === "/api/dashboard") dash = body;
  }

  if (dash) {
    const zone = dash.zones[0];
    ["zone", "latitude", "longitude", "health", "risk", "anomalies", "metrics", "event_confidence"]
      .forEach((f) => ok(f in zone, `zone row → ${f}`));
    ok(Array.isArray(dash.trend) && (!dash.trend.length || ("t" in dash.trend[0] && "health" in dash.trend[0])),
      "trend rows expose t + health");
    ok(dash.what_changed.every((w) => ["metric", "label", "value", "baseline", "unit", "pct_change",
                                       "severity", "direction", "zone"].every((k) => k in w)),
      "what_changed rows expose value/baseline/severity/direction");
    ok(Array.isArray(dash.sources) && dash.sources.every((s) => ["source", "status", "freshness_min",
                                                                 "latency_ms", "event_count", "error_rate", "last_update"].every((k) => k in s)),
      "source rows expose freshness/latency/counters");
    ok(dash.events.every((e) => ["id", "timestamp", "event_type", "value", "unit", "zone", "source",
                                 "severity", "metadata"].every((k) => k in e)),
      "event rows expose the fields used by the stream table");
  }

  const events = await get("/api/disruptions");
  if (events.length) {
    const e = events[0];
    ["id", "zone", "state", "status", "severity", "confidence", "duration_min", "started", "sequence",
     "sources", "note", "lifecycle", "evidence", "latitude", "longitude", "peak"]
      .forEach((f) => ok(f in e, `event record → ${f}`));
    const detail = await get(`/api/disruptions/${e.id}`);
    ok("evidence" in detail && "correlation" in detail, "event detail exposes evidence + correlation");
    ok(Array.isArray(detail.evidence) && detail.evidence.every((x) => "kind" in x && "text" in x),
      "evidence items expose kind + text");
    const search = await get(`/api/disruptions?q=${encodeURIComponent(e.zone)}&status=${e.status}&severity=${e.severity}`);
    ok(search.some((x) => x.id === e.id), "server-side event search by zone/status/severity");
  } else {
    console.log("  SKIP  event-record field checks (no civic events yet — run a scenario)");
  }

  const alerts = await get("/api/alerts");
  if (alerts.length) {
    ["id", "level", "title", "message", "zone", "status", "timestamp", "disruption_id"]
      .forEach((f) => ok(f in alerts[0], `alert record → ${f}`));
  } else {
    console.log("  SKIP  alert-record field checks (no alerts yet)");
  }

  const anoms = await get("/api/anomalies");
  if (anoms.length) {
    ["id", "metric", "zone", "baseline", "current", "unit", "pct_change", "z_score", "severity",
     "consecutive_steps", "strength", "timestamp", "explanation", "latitude", "longitude", "threshold"]
      .forEach((f) => ok(f in anoms[0], `anomaly record → ${f}`));
  } else {
    console.log("  SKIP  anomaly-record field checks (no active anomalies)");
  }

  const metrics = await get("/api/metrics");
  ok(Object.keys(metrics).length === 3, "GET /api/metrics returns all three zones");
  ok(Object.values(metrics).every((z) => ["rainfall", "traffic", "complaints", "incidents"].every((m) => m in z)),
    "metric payload exposes the four registered metrics");

  console.log("\n" + "=".repeat(70));
  console.log(`contract checks: ${passed}/${passed + failures.length} passed`);
  failures.forEach((f) => console.log(`  FAILED: ${f}`));
  console.log("=".repeat(70));
  process.exit(failures.length ? 1 : 0);
};

main().catch((e) => { console.error("contract check crashed:", e); process.exit(2); });


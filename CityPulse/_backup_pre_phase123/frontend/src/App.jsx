import { useEffect, useRef, useState } from "react";
import { NavLink, Link, Routes, Route } from "react-router-dom";
import { MapContainer, TileLayer, Circle, CircleMarker, Popup } from "react-leaflet";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const WS = import.meta.env.VITE_WS_URL || "ws://127.0.0.1:8000/ws/citypulse";
const post = (p, b) => fetch(API + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
const hc = h => (h >= 85 ? "#10b981" : h >= 70 ? "#f59e0b" : h >= 50 ? "#f97316" : "#ef4444");
const sevColor = { low: "#3b82f6", moderate: "#f59e0b", high: "#f97316", critical: "#ef4444" };
const time = t => (t || "").slice(11, 19);

function useCity() {
  const [d, setD] = useState(null); const [conn, setConn] = useState("RECONNECTING"); const [err, setErr] = useState(false); const tries = useRef(0);
  useEffect(() => {
    let ws, timer, dead = false;
    const open = () => {
      ws = new WebSocket(WS);
      ws.onopen = () => { tries.current = 0; setConn("LIVE"); setErr(false); };
      ws.onmessage = e => { const m = JSON.parse(e.data); if (m.type === "score_updated") setD(m.data); };
      ws.onclose = () => { if (dead) return; tries.current++; setConn(tries.current > 2 ? "OFFLINE" : "RECONNECTING"); if (tries.current > 2) setErr(true); timer = setTimeout(open, 2000); };
      ws.onerror = () => ws.close();
    };
    open(); return () => { dead = true; clearTimeout(timer); ws && ws.close(); };
  }, []);
  return { d, conn, err };
}

function Sev({ s }) { return <span className={`badge ${s}`}>{String(s).toUpperCase()}</span>; }

function CityMap({ d }) {
  return (
    <MapContainer center={[17.700, 78.480]} zoom={13} scrollWheelZoom aria-label="Live city map">
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {d.zones.map(z => (
        <Circle key={z.zone} center={[z.latitude, z.longitude]} radius={1400} pathOptions={{ color: hc(z.health), fillColor: hc(z.health), fillOpacity: .22 }}>
          <Popup><b>Zone intelligence: {z.zone}</b><br />Health {z.health} / Risk {z.risk}<br />Active anomalies: {z.anomalies}<br />
            {z.event_confidence != null && <>CityPulse Event Confidence (prototype): {z.event_confidence}%<br /></>}
            {Object.entries(z.metrics).map(([k, v]) => <div key={k}>{k}: {v}</div>)}</Popup>
        </Circle>))}
      {d.disruptions.filter(x => x.state !== "RESOLVED").map(x => (
        <Circle key={x.id} center={[17.710, 78.465]} radius={1900} pathOptions={{ color: "#d946ef", dashArray: "8", fillOpacity: .08 }}>
          <Popup><b>Disruption {x.state}</b><br />{x.zone} · {x.severity}<br />{x.sequence}<br />Sources: {x.sources.join(", ")}<br />
            CityPulse Event Confidence (prototype): {Math.round(x.confidence)}%</Popup></Circle>))}
      {d.anomalies.filter(a => a.status === "active").map(a => (
        <CircleMarker key={a.id} center={[a.latitude, a.longitude]} radius={6 + a.strength * 8} pathOptions={{ color: sevColor[a.severity], fillOpacity: .7 }}>
          <Popup><b>{a.metric}</b> ({a.source})<br />{a.current} {a.unit} vs baseline {a.baseline}<br />z={a.z_score} · {a.severity}<br />{a.zone} · {time(a.timestamp)}</Popup></CircleMarker>))}
    </MapContainer>);
}

function Dashboard({ d }) {
  const h = d.health, k = d.kpis, s = d.summary;
  const act = d.correlations.filter(c => c.status === "active");
  const disr = d.disruptions.filter(x => x.state !== "RESOLVED");
  return (
    <div className="grid">
      <div className="grid kpis">
        <Link to="/" className={`card kpi ${h.score >= 85 ? "g" : h.score < 50 ? "o" : ""}`}><h3>City health</h3><b>{h.score}/100</b>{h.status} · {h.trend_pct >= 0 ? "↑" : "↓"} {Math.abs(h.trend_pct)}%</Link>
        <Link to="/anomalies" className="card kpi"><h3>Anomalies</h3><b>{k.anomalies}</b>active</Link>
        <Link to="/" className="card kpi o"><h3>Civic events</h3><b>{k.disruptions}</b>active</Link>
        <Link to="/" className="card kpi"><h3>Correlations</h3><b>{k.correlations}</b>possible</Link>
        <Link to="/alerts" className="card kpi o"><h3>Alerts</h3><b>{k.alerts}</b>active</Link>
        <Link to="/sources" className="card kpi g"><h3>Sources</h3><b>{k.sources_live}/{k.sources_total}</b>live</Link>
      </div>
      <div className="grid two">
        <div className="card"><h3>Live city map <span className="sim">SIMULATED DATA · FICTIONAL CITY</span></h3><CityMap d={d} /></div>
        <div className="card"><h3>Why now? <span className="sim">RULE-BASED SUMMARY</span></h3><b>{s.headline}</b>
          {s.lines.length === 0 ? <p>{s.text}</p> : <><ul>{s.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
            {s.confidence != null && <p>CityPulse Event Confidence (prototype): <b>{Math.round(s.confidence)}%</b> · State: {s.state}</p>}<p style={{ color: "var(--mut)" }}>{s.text}</p></>}
        </div>
      </div>
      {disr.length > 0 && (
        <div className="card event">
          <h3>🚨 Active civic event <span className="sim">PROTOTYPE DETECTION</span></h3>
          {disr.map(x => (
            <div key={x.id} className="row" style={{ justifyContent: "space-between" }}>
              <span><b>{x.zone}</b> — {x.sequence} · state <b>{x.state}</b> · severity <Sev s={x.severity} /></span>
              <span>CityPulse Event Confidence (prototype): <b>{Math.round(x.confidence)}%</b> · duration {x.duration_min} min</span>
            </div>))}
          <p style={{ color: "var(--mut)" }}>Signals increased in sequence within the event window. Possible temporal association — not a confirmed cause.</p>
        </div>)}
      <div className="grid two">
        <div className="card"><h3>City health trend + Zone A metrics</h3>
          <ResponsiveContainer width="100%" height={220}><LineChart data={d.trend}><CartesianGrid stroke="#243056" /><XAxis dataKey="t" stroke="#8fa0d0" /><YAxis domain={[0, 100]} stroke="#8fa0d0" />
            <Tooltip contentStyle={{ background: "#131c3a" }} /><Line dataKey="health" stroke="#a855f7" dot={false} isAnimationActive={false} /><Line dataKey="traffic" stroke="#22d3ee" dot={false} isAnimationActive={false} /><Line dataKey="rainfall" stroke="#3b82f6" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
        <div className="card"><h3>City health breakdown</h3>{Object.entries(h.components).map(([n, v]) => (
          <div key={n}><div className="row" style={{ justifyContent: "space-between" }}><span>{n}</span><b>{v}</b></div><div className="bar"><i style={{ width: v + "%", background: hc(v) }} /></div></div>))}
          <h3 style={{ marginTop: 12 }}>🔮 Prototype trend-based prediction</h3>
          {d.predictions.items.filter(i => i.trend !== "flat").slice(0, 4).map(i => (
            <p key={i.metric} style={{ margin: "4px 0" }}>{i.label}: est. <b>{i.range_low}–{i.range_high} {i.unit}</b> in 30 min <span style={{ color: "var(--mut)" }}>({i.trend_strength})</span></p>))}
          <p style={{ color: "var(--mut)" }}>{d.predictions.note}</p></div>
      </div>
      <div className="grid two">
        <div className="card"><h3>What changed (vs baseline)</h3><table><tbody>{d.what_changed.map(w => (
          <tr key={w.metric}><td>{w.label}</td><td>{w.value} {w.unit}</td><td>base {w.baseline}</td><td>{w.direction === "up" ? "▲" : "▼"} {w.pct_change}%</td><td><Sev s={w.severity} /></td></tr>))}</tbody></table>
          <h3 style={{ marginTop: 12 }}>Possible links <span className="sim">CORRELATION ≠ CAUSATION</span></h3>
          {act.length === 0 ? <p>No active multi-signal patterns right now.</p> :
            act.map(c => <div key={c.id} style={{ marginBottom: 10 }}><p style={{ margin: "2px 0" }}><b>{c.zone}</b>: {c.metrics.join(" + ")} · <b>Event Confidence (prototype) {c.confidence}%</b></p>
              <p style={{ margin: "2px 0", color: "var(--mut)" }}>{c.note}</p>
              {c.lagged && c.lagged.slice(0, 2).map((l, i) => <p key={i} style={{ margin: "2px 0" }}>{l.a} → {l.b} · lag +{l.lag_minutes} min · r = {l.r} · {l.classification}</p>)}</div>)}</div>
        <div className="card"><h3>Live event stream</h3><table><tbody>{d.events.slice(0, 14).map(e => (
          <tr key={e.id}><td>{time(e.timestamp)}</td><td>{e.event_type} {e.value}{e.unit}</td><td>{e.zone}</td><td><Sev s={e.severity} /></td></tr>))}</tbody></table></div>
      </div>
    </div>);
}

function Anomalies({ d }) {
  const [q, setQ] = useState("");
  const rows = d.anomalies.filter(a => JSON.stringify(a).toLowerCase().includes(q.toLowerCase())).sort((a, b) => b.strength - a.strength);
  return (<div className="card"><h3>Anomaly center</h3><input aria-label="Search anomalies" placeholder="Search zone, source, severity…" value={q} onChange={e => setQ(e.target.value)} />
    {rows.length === 0 ? <p>No active anomalies. City signals are currently within expected ranges.</p> : <table><thead><tr><th>Metric</th><th>Zone</th><th>Baseline</th><th>Current</th><th>Change</th><th>Z</th><th>Severity</th><th>Streak</th><th>First seen</th></tr></thead>
      <tbody>{rows.map(a => <tr key={a.id}><td>{a.metric}</td><td>{a.zone}</td><td>{a.baseline}</td><td>{a.current} {a.unit}</td><td>{a.pct_change}%</td><td>{a.z_score}</td><td><Sev s={a.severity} /></td><td>{a.consecutive_steps} × 15 min</td><td>{time(a.timestamp)}</td></tr>)}</tbody></table>}
    <p style={{ color: "var(--mut)" }}>Rule: a reading is anomalous when it is more than 2 standard deviations above its baseline AND above a practical floor. Baselines learn only from non-anomalous data.</p></div>);
}

function Alerts({ d }) {
  const act = (id, a) => post(`/api/alerts/${id}/${a}`);
  return (<div className="grid"><div className="card"><h3>Alert center</h3>{d.alerts.length === 0 ? <p>No alerts.</p> : [...d.alerts].reverse().map(a => (
    <div key={a.id} className="card" style={{ marginBottom: 8 }}><div className="row"><span className={`badge ${{ INFO: "low", WATCH: "moderate", WARNING: "high", CRITICAL: "critical" }[a.level]}`}>{a.level}</span><b>{a.title}</b><span>{time(a.timestamp)} · {a.status}</span></div>
      <p>{a.message}</p><div className="row"><button onClick={() => act(a.id, "acknowledge")}>Acknowledge</button><button onClick={() => act(a.id, "resolve")}>Mark resolved</button><Link to="/"><button>View map</button></Link></div></div>))}</div></div>);
}

function Sources({ d }) {
  return (<div className="card"><h3>Source health</h3><table><thead><tr><th>Source</th><th>Status</th><th>Freshness</th><th>Latency</th><th>Events</th><th>Error rate</th><th>Last update</th><th /></tr></thead><tbody>{d.sources.map(s => (
    <tr key={s.source}><td>{s.source}</td><td><span className={`badge ${s.status === "LIVE" ? "LIVE" : "OFFLINE"}`}>{s.status}</span></td><td>{s.freshness_min * 15} min</td><td>{s.latency_ms ?? "—"} ms</td><td>{s.event_count}</td><td>{s.error_rate}%</td><td>{time(s.last_update)}</td>
      <td><button onClick={() => post("/api/simulation/source", { source: s.source, status: s.status === "LIVE" ? "offline" : "live" })}>{s.status === "LIVE" ? "Simulate outage" : "Restore"}</button></td></tr>))}</tbody></table>
    <p>If a feed goes offline, the rest keep running and event confidence is reduced with a visible note.</p></div>);
}

function Simulation({ d }) {
  const s = d.sim;
  return (<div className="grid"><button className="big" onClick={() => post("/api/simulation/demo", { speed: 5 })}>RUN FULL CIVIC DISRUPTION</button>
    <div className="card"><h3>Simulation control <span className="sim">SYNTHETIC · FICTIONAL CITY</span></h3><p>Status <b>{s.status}</b> · scenario <b>{s.scenario}</b> · T+{s.scenario_time} min · {s.simulation_time.slice(0, 16).replace("T", " ")} · seed {s.seed} · {s.speed}x</p>
      <div className="row"><button onClick={() => post("/api/simulation/start")}>Start</button><button onClick={() => post("/api/simulation/pause")}>Pause</button><button onClick={() => post("/api/simulation/step")}>Step</button>
        <button onClick={() => post("/api/simulation/reset")}>Reset</button><button onClick={() => post("/api/simulation/restart")}>Restart</button>
        <select aria-label="Scenario" value={s.scenario} onChange={e => post("/api/simulation/scenario", { scenario: e.target.value })}>{["normal", "heavy_rain", "urban_flooding", "traffic_incident", "full_disruption"].map(x => <option key={x}>{x}</option>)}</select>
        <select aria-label="Speed" value={s.speed} onChange={e => post("/api/simulation/speed", { speed: +e.target.value })}>{[.5, 1, 2, 5, 10].map(x => <option key={x} value={x}>{x}x</option>)}</select></div>
      <p style={{ color: "var(--mut)" }}>Each tick is one simulated 15-minute city step. The demo scenario plays the full story: normal → rainfall → traffic response → complaints → anomalies → civic event → alerts → recovery.</p></div></div>);
}

export default function App() {
  const { d, conn, err } = useCity();
  return (<>
    <header className="top"><h1>CITYPULSE</h1><nav aria-label="Main">{[["/", "Dashboard"], ["/anomalies", "Anomalies"], ["/alerts", "Alerts"], ["/sources", "Sources"], ["/simulation", "Simulation"]].map(([p, l]) => <NavLink key={p} to={p} end>{l}</NavLink>)}</nav>
      <span className={`badge ${conn}`} role="status">● {conn}</span><span className="sim">SYNTHETIC DATA · FICTIONAL CITY</span></header>
    <main>{!d ? (err ? <p>Unable to connect to CityPulse backend. <button onClick={() => location.reload()}>Retry</button></p> : <p>Connecting to CityPulse…</p>) :
      <Routes><Route path="/" element={<Dashboard d={d} />} /><Route path="/anomalies" element={<Anomalies d={d} />} /><Route path="/alerts" element={<Alerts d={d} />} /><Route path="/sources" element={<Sources d={d} />} /><Route path="/simulation" element={<Simulation d={d} />} /></Routes>}</main>
    <footer style={{ color: "var(--mut)", padding: "12px 20px" }}>🌆 CityPulse prototype · synthetic data for a fictional city · correlations are possible links, not causes · Event Confidence and health score are prototype indicators, not official metrics · predictions are prototype trend estimates.</footer></>);
}

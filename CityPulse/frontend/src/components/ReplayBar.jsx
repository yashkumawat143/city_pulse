import { useCallback, useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api from "../lib/api";
import { clock, healthColor, int, num } from "../lib/format";
import { Empty, Loading, Meter, Tag } from "./ui";

const PHASE_TONE = { idle: "muted", building: "info", peak: "warn", recovering: "info", recovered: "ok" };
const CH_COLOR = { rain: "#3b82f6", traffic: "#22d3ee", complaints: "#a855f7", incidents: "#f59e0b" };

/** Linear interpolation over a [[minute, intensity], ...] curve from the backend. */
function sampleCurve(curve, x) {
  if (!curve?.length) return 0;
  if (x <= curve[0][0]) return curve[0][1];
  for (let i = 1; i < curve.length; i += 1) {
    if (x <= curve[i][0]) {
      const [x0, y0] = curve[i - 1];
      const [x1, y1] = curve[i];
      return x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
    }
  }
  return curve[curve.length - 1][1];
}

/**
 * Storm progression: the active scenario's channel curves (straight from GET /api/progression)
 * with the current position marked. Self-refreshes while the engine runs.
 */
export function ProgressionPanel({ intervalMs = 5000 }) {
  const [pr, setPr] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setPr(await api.progression());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, intervalMs);
    return () => clearInterval(id);
  }, [load, intervalMs]);

  if (error) return <p className="inline-error" role="alert">{error}</p>;
  if (!pr) return <Loading label="Loading storm progression…" rows={2} />;
  if (!pr.channels.length) {
    return (
      <Empty title="No active channels"
             hint="The normal scenario drives no channels. Pick a storm scenario to watch rainfall, traffic, complaints and incidents build and recover." />
    );
  }

  const duration = pr.duration_min || 0;
  const rows = [];
  for (let m = 0; m < duration; m += 10) {
    const row = { m };
    pr.channels.forEach((ch) => { row[ch.channel] = Math.round(sampleCurve(ch.curve, m) * 1000) / 1000; });
    rows.push(row);
  }
  const last = { m: duration };
  pr.channels.forEach((ch) => { last[ch.channel] = Math.round(sampleCurve(ch.curve, duration) * 1000) / 1000; });
  rows.push(last);
  const marker = Math.min(pr.elapsed_min, duration);

  return (
    <>
      <div className="row wrap gap">
        <Tag tone={PHASE_TONE[pr.phase] || "muted"}>phase {pr.phase}</Tag>
        <Tag tone="info">T+{pr.elapsed_min} / {duration} min</Tag>
        <Tag tone="muted">{num(pr.progress_pct, 0)}% through the curve</Tag>
      </div>
      <div className="replay-chart" aria-label="Scenario intensity curves">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="#243056" />
            <XAxis dataKey="m" type="number" domain={[0, duration]} stroke="#8fa0d0"
                   tickFormatter={(v) => `T+${v}`} />
            <YAxis domain={[0, 1]} stroke="#8fa0d0" tickFormatter={(v) => `${Math.round(v * 100)}%`} />
            <Tooltip contentStyle={{ background: "#131c3a" }}
                     formatter={(v, name) => [`${num(v * 100, 0)}%`, name]} />
            <ReferenceLine x={marker} stroke="#e9eeff" strokeDasharray="4 3"
                           label={{ value: "now", position: "insideTopRight", fill: "#93a1c7", fontSize: 10 }} />
            {pr.channels.map((ch) => (
              <Line key={ch.channel} type="monotone" dataKey={ch.channel} stroke={CH_COLOR[ch.channel] || "#38bdf8"}
                    dot={false} strokeWidth={2} isAnimationActive={false} name={ch.label} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {pr.channels.map((ch) => (
        <div key={ch.channel} className="meter-row">
          <span>{ch.label} <small>intensity {num(ch.intensity * 100, 0)}%</small></span>
          <b>{num(ch.intensity, 2)}</b>
          <Meter value={ch.intensity * 100} color={CH_COLOR[ch.channel] || "#38bdf8"} label={`${ch.label} intensity`} />
        </div>
      ))}
    </>
  );
}

/**
 * Replay bar: scrub frames recorded by the backend (GET /api/replay), one per simulated
 * minute. Playback and scrubbing are local — the live engine keeps running underneath.
 * A selection of -1 follows the newest frame ("live").
 */
export default function ReplayBar({ refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [idx, setIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const lastFetch = useRef(0);

  const load = useCallback(async () => {
    lastFetch.current = Date.now();
    try {
      setData(await api.replay());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Pull new frames when the simulation advances, throttled to one request / 8 s.
  useEffect(() => {
    if (Date.now() - lastFetch.current > 8000) load();
  }, [refreshKey, load]);

  const frames = data?.frames || [];
  const atEnd = idx === -1 || idx >= frames.length - 1;
  const sel = frames.length ? Math.max(0, Math.min(idx === -1 ? frames.length - 1 : idx, frames.length - 1)) : -1;
  const frame = sel >= 0 ? frames[sel] : null;

  // Playback: advance through recorded frames while playing.
  useEffect(() => {
    if (!playing) return undefined;
    const id = setInterval(() => {
      setIdx((i) => (i === -1 ? 0 : Math.min(i + 1, frames.length - 1)));
    }, 250);
    return () => clearInterval(id);
  }, [playing, frames.length]);

  useEffect(() => {
    if (playing && frames.length && idx >= frames.length - 1) setPlaying(false);
  }, [playing, idx, frames.length]);

  const togglePlay = () => {
    if (!playing && (idx === -1 || idx >= frames.length - 1)) setIdx(0);
    setPlaying((p) => !p);
  };

  if (error && !data) return <p className="inline-error" role="alert">{error}</p>;
  if (!data) return <Loading label="Loading recorded frames…" rows={2} />;
  if (!frames.length) {
    return (
      <Empty title="No frames recorded yet"
             hint="Run or step the simulation — CityPulse records one frame per simulated minute so you can scrub the run afterwards." />
    );
  }

  const chart = frames.map((f) => ({
    tick: f.tick, health: f.health,
    rainfall: f.zones?.["Zone A"]?.rainfall ?? 0,
  }));

  return (
    <>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="replay-controls">
        <button type="button" className="btn" onClick={() => { setIdx(0); setPlaying(false); }}
                aria-label="Jump to first frame">⏮</button>
        <button type="button" className="btn" onClick={togglePlay}
                aria-label={playing ? "Pause replay" : "Play replay"}>
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
        <button type="button" className="btn" onClick={() => { setIdx(frames.length - 1); setPlaying(false); }}
                aria-label="Jump to newest frame">⏭</button>
        <input type="range" min={0} max={frames.length - 1} value={Math.max(0, sel)}
               aria-label="Replay position" disabled={frames.length < 2}
               onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} />
        <button type="button" className="btn ghost" onClick={load}>↻ Reload</button>
      </div>
      <div className="replay-readout" role="status">
        <Tag tone={frame.phase ? (PHASE_TONE[frame.phase] || "muted") : "muted"}>phase {frame.phase || "—"}</Tag>
        <Tag tone={atEnd && !playing ? "ok" : "info"}>frame {sel + 1} / {frames.length}</Tag>
        <span className="muted small">tick {frame.tick} · city clock {clock(frame.time)}</span>
        <span className="muted small">
          health <b style={{ color: healthColor(frame.health) }}>{num(frame.health, 0)}</b>/100
        </span>
        <span className="muted small">
          {int(frame.kpis?.anomalies)} anomalies · {int(frame.kpis?.disruptions)} events · {int(frame.kpis?.alerts)} alerts
        </span>
        <span className="muted small">
          Zone A rain {num(frame.zones?.["Zone A"]?.rainfall, 1)} mm · traffic {num(frame.zones?.["Zone A"]?.traffic, 0)}%
        </span>
      </div>
      <div className="replay-chart" aria-label="Recorded health and rainfall per frame">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="#243056" />
            <XAxis dataKey="tick" type="number" domain={["dataMin", "dataMax"]} stroke="#8fa0d0"
                   tickFormatter={(v) => `T+${v}`} />
            <YAxis yAxisId="h" domain={[0, 100]} stroke="#8fa0d0" />
            <YAxis yAxisId="r" orientation="right" stroke="#8fa0d0" />
            <Tooltip contentStyle={{ background: "#131c3a" }} />
            <ReferenceLine yAxisId="h" x={frame.tick} stroke="#e9eeff" strokeDasharray="4 3" />
            <Line yAxisId="h" type="monotone" dataKey="health" stroke="#a855f7" dot={false} strokeWidth={2}
                  isAnimationActive={false} name="Health" />
            <Line yAxisId="r" type="monotone" dataKey="rainfall" stroke="#3b82f6" dot={false} strokeWidth={2}
                  isAnimationActive={false} name="Zone A rainfall (mm)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="muted small">
        Frames are recorded by the Python engine (one per simulated minute, last {frames.length} shown). Scrubbing is
        a local view of recorded history — it never rewinds the live pipeline.
      </p>
    </>
  );
}


"""CityPulse backend: simulator -> events -> anomalies -> correlations -> civic events -> health -> API/WS.
All data is SIMULATED (fictional city: Zone A / Zone B / Zone C). Correlations are never
presented as causation; confidence is labelled "CityPulse Event Confidence (prototype)".

Architecture adapted from the reference FastAPI+WS design; the analytics brain keeps the
CityPulse rules: mean+2*std with practical floors, event confidence from signal strength +
diversity + temporal proximity + persistence, weighted civic health score, and causal-safe
language everywhere.
"""
import asyncio
import logging
import math
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging (plain stdlib — no new dependency)
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("CITYPULSE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s [citypulse] %(message)s",
)
log = logging.getLogger("citypulse")

# Comma-separated allow-list for CORS; "*" (dev default) keeps the preview ports working.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CITYPULSE_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
ANOMALY_Z_THRESHOLD = float(os.getenv("CITYPULSE_ANOMALY_Z", "2.0"))   # configurable statistical threshold
ANOMALY_PERSISTENCE = int(os.getenv("CITYPULSE_ANOMALY_PERSISTENCE", "0"))  # extra consecutive ticks required
HEARTBEAT_SECONDS = float(os.getenv("CITYPULSE_WS_HEARTBEAT", "15"))
# How many replay frames the engine keeps (one frame per simulated minute).
REPLAY_FRAMES = int(os.getenv("CITYPULSE_REPLAY_FRAMES", "600"))

# --- Civic Event Intelligence Engine (all thresholds centralised / configurable) ---
try:  # Layer-2 ML anomaly detection (Isolation Forest); graceful degradation if absent
    from sklearn.ensemble import IsolationForest
    SKLEARN = True
except Exception:  # pragma: no cover - environment without sklearn
    SKLEARN = False
    log.info("scikit-learn unavailable - ML anomaly layer disabled (statistical layer only)")

IFOREST_CONTAMINATION = float(os.getenv("CITYPULSE_IFOREST_CONTAMINATION", "0.08"))
IFOREST_WINDOW = int(os.getenv("CITYPULSE_IFOREST_WINDOW", "60"))     # minutes of history per fit
IFOREST_MIN_ROWS = int(os.getenv("CITYPULSE_IFOREST_MIN_ROWS", "30")) # warm-up before ML is trusted
IFOREST_REFIT = int(os.getenv("CITYPULSE_IFOREST_REFIT", "10"))      # refit cadence in ticks

# Anomaly score 0-100 interpretation bands (configurable, single source of truth).
ANOMALY_BANDS = dict(normal=30, slight=50, moderate=70, high=85)  # <= boundaries
ANOMALY_BAND_LABELS = [(85, "Extreme anomaly"), (70, "High anomaly"), (50, "Moderate anomaly"),
                       (30, "Slight deviation"), (-1, "Normal")]

# Event confidence component weights (sum = 1.0). Confidence = weighted sum of 0-100 components.
CONF_W = dict(anomaly_strength=0.30, signal_diversity=0.25, temporal_proximity=0.20,
              persistence=0.15, spatial_concentration=0.10)

# Risk bands (configurable): score 0-100 -> LOW / MODERATE / HIGH / CRITICAL.
RISK_BANDS = dict(low=25, moderate=50, high=75)

# Lagged correlation windows (minutes).
LAGS = (0, 15, 30, 45, 60)

# Extensible civic event classification registry. The classifier picks from observed
# signals only; types with no matching feed stay dormant until a feed is added.
EVENT_TYPES = {
    "RAIN_DISRUPTION": "Possible rain-related civic disruption",
    "TRAFFIC_DISRUPTION": "Possible traffic disruption",
    "ROAD_INCIDENT_CLUSTER": "Possible road-incident cluster",
    "CIVIC_COMPLAINT_SURGE": "Possible civic complaint surge",
    "POLLUTION_SPIKE": "Possible pollution spike",          # dormant: no pollution feed yet
    "HEAT_EVENT": "Possible heat event",                    # dormant: no temperature feed yet
    "POWER_OUTAGE": "Possible power outage",                # dormant: no power feed yet
    "UNKNOWN_MULTI_SIGNAL_EVENT": "Possible multi-signal civic event",
}

# ---------------------------------------------------------------------------
# Fictional city layout + metric registry
# ---------------------------------------------------------------------------

ZONES = {
    "Zone A": (17.710, 78.465),   # west
    "Zone B": (17.700, 78.480),   # center
    "Zone C": (17.690, 78.495),   # east
}
WEIGHT = {"Zone A": 1.0, "Zone B": 0.10, "Zone C": 0.08}   # event coupling per zone (B/C stay near normal)

# Metric registry: add a feed by adding an entry here (+ a scenario channel curve).
M = {
    "rainfall":    dict(src="weather",    unit="mm",           base=0.5, eff=32, floor=3,  sign=1,  ch="rain",       off=(0.004,  0.004)),
    "traffic":     dict(src="traffic",    unit="congestion %", base=32,  eff=55, floor=8,  sign=1,  ch="traffic",    off=(0.003, -0.003)),
    "complaints":  dict(src="complaints", unit="reports/15min",base=4,   eff=16, floor=4,  sign=1,  ch="complaints", off=(-0.003, 0.003)),
    "incidents":   dict(src="traffic",    unit="per 15min",    base=0.3, eff=2.2,floor=0.8,sign=1,  ch="traffic",    off=(-0.002,-0.002)),
}
LBL = {"rainfall": "Rainfall", "traffic": "Traffic congestion", "complaints": "Complaint volume", "incidents": "Road incidents"}

# Scenario channel curves: (x = minutes since scenario start, y = intensity 0..1).
# Timed so all signals overlap inside the first ~2 hours (the demo story), with
# a long tail for recovery.
CH = {
    "rain":       ([0, 15, 45, 200, 260, 400], [0, 0.15, 0.7, 1.0, 0.6, 0]),
    "traffic":    ([0, 30, 70, 210, 280, 400], [0, 0, 0.7, 1.0, 0.45, 0]),
    "complaints": ([0, 35, 80, 220, 300, 400], [0, 0, 0.65, 1.0, 0.4, 0]),
    "incidents":  ([0, 30, 75, 220, 300, 400], [0, 0, 0.6, 1.0, 0.45, 0]),
}
SCEN = {
    "normal": [],
    "heavy_rain": ["rain"],
    "urban_flooding": ["rain", "traffic", "complaints", "incidents"],
    "traffic_incident": ["traffic"],
    "full_disruption": ["rain", "traffic", "complaints", "incidents"],
}
# Scenario registry: UI-facing label + story for every SCEN key (keys kept in sync by tests).
SCEN_META = {
    "normal": dict(label="normal — quiet city",
                   description="Baseline conditions — no scenario channel is driven."),
    "heavy_rain": dict(label="heavy rain",
                       description="Rainfall in Zone A builds, peaks around minute 200 and tapers by minute 400."),
    "urban_flooding": dict(label="urban flooding",
                           description="Rain drives congestion, complaint volume and road incidents across the city."),
    "traffic_incident": dict(label="traffic incident",
                             description="Congestion rises first (no rain); complaints and incidents follow the traffic curve."),
    "full_disruption": dict(label="full civic disruption (demo)",
                            description="The demo story: rain first, traffic/complaints/incidents lag behind, then recovery (about 400 minutes)."),
}
# Human labels for scenario channel keys (used by /api/progression).
CH_LBL = {"rain": "Rainfall", "traffic": "Traffic congestion",
          "complaints": "Complaint volume", "incidents": "Road incidents"}
# Civic Health Score component weights (prototype weights, not an official standard).
W = {"Traffic": 0.40, "Weather": 0.30, "Complaints": 0.30}
SOURCES = ["weather", "traffic", "complaints"]

# Event confidence weights (CityPulse prototype score — NOT a probability).
CONF = dict(base=40.0, per_extra_signal=12.0, strength_span=6.0, strength_bonus=25.0,
            per_persistent_step=5.0, persistence_cap=15.0, tight_bonus=10.0, spread_bonus=5.0, cap=95.0)


def clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def sevz(z: float) -> str:
    z = abs(z)
    return "critical" if z >= 6 else "high" if z >= 4 else "moderate" if z >= 3 else "low"


def correlation_label(r: float) -> str:
    """Exact v2.0 classification bands, direction-aware (correlation != causation)."""
    if r >= 0.70:
        return "Strong positive"
    if r >= 0.40:
        return "Moderate positive"
    if r >= 0.20:
        return "Weak positive"
    if r > -0.20:
        return "Very weak / little linear relationship"
    if r > -0.40:
        return "Weak inverse"
    if r > -0.70:
        return "Moderate inverse"
    return "Strong inverse"


def score_band(score: float) -> str:
    """0-100 anomaly score -> human label (uses ANOMALY_BANDS, configurable)."""
    for limit, label in ANOMALY_BAND_LABELS:
        if score > limit:
            return label
    return "Normal"


def risk_band(score: float) -> str:
    """0-100 risk score -> LOW / MODERATE / HIGH / CRITICAL."""
    if score <= RISK_BANDS["low"]:
        return "LOW"
    if score <= RISK_BANDS["moderate"]:
        return "MODERATE"
    if score <= RISK_BANDS["high"]:
        return "HIGH"
    return "CRITICAL"


def classify_event(metrics) -> str:
    """
    Extensible, evidence-driven event classifier. Uses ONLY the observed signal
    set - never a hard-coded event. Returns a key of EVENT_TYPES.
    """
    s = set(metrics)
    if "rainfall" in s and len(s) >= 2:
        return "RAIN_DISRUPTION"
    if "traffic" in s and "incidents" in s and "rainfall" not in s:
        return "ROAD_INCIDENT_CLUSTER" if "complaints" in s else "TRAFFIC_DISRUPTION"
    if "complaints" in s and len(s) >= 3:
        return "CIVIC_COMPLAINT_SURGE"
    if "traffic" in s:
        return "TRAFFIC_DISRUPTION"
    return "UNKNOWN_MULTI_SIGNAL_EVENT"


class Sim:
    """Live synthetic-city engine. One observe() tick = one 15-minute city step."""

    def __init__(self, seed: int = 42):
        self.speed = 1.0
        self.reset(seed)

    # ------------------------------------------------------------------ setup
    def reset(self, seed: Optional[int] = None, scenario: str = "normal", running: bool = False):
        if seed is not None:
            self.seed = seed
        self.rng = np.random.default_rng(self.seed)
        self.scenario = scenario
        self.status = "running" if running else "paused"
        self.start = datetime(2026, 9, 24, 10, 0)
        self.t = 0
        self.t0 = 0
        self.seq = 0
        self.pending: list = []
        self.events = deque(maxlen=3000)
        self.det = {}       # per (zone, metric) detector state
        self.anoms = {}     # anomaly_id -> anomaly
        self.act = {}       # (zone, metric) -> active anomaly id
        self.corrs = {}
        self.disr = {}
        self.dz = {}        # zone -> active disruption id
        self.alerts = {}
        self.akeys = set()
        self.cur = {}
        self.series = {m: deque(maxlen=480) for m in M}
        self.zone_series = {(z, m): deque(maxlen=480) for z in ZONES for m in M}
        self.hist = deque(maxlen=600)
        self.replay = deque(maxlen=REPLAY_FRAMES)
        self.health_hist = deque(maxlen=300)
        self.offline: set = set()
        self._ml = {}        # Isolation Forest per-tick score cache: zone -> result
        self._ml_models = {} # Isolation Forest fitted-model cache (refit every IFOREST_REFIT ticks)
        self._ml_t = -1
        self.src = {k: dict(count=0, last_t=0, latency=70) for k in SOURCES}
        # Pre-warm ~16h of quiet history so baselines exist from the first live tick.
        self._warm = True
        for _ in range(-64, 0):
            self.observe(quiet=True)
        self._warm = False
        self.t = 0

    def ts(self, t: Optional[int] = None) -> str:
        return (self.start + timedelta(minutes=self.t if t is None else t)).isoformat()

    def push(self, typ: str, data):
        self.pending.append({"type": typ, "data": data})

    def drain(self):
        msgs, self.pending = self.pending, []
        return msgs

    def intensity(self, ch: str) -> float:
        if ch not in SCEN[self.scenario]:
            return 0.0
        return float(np.interp(self.t - self.t0, *CH[ch]))

    def phase(self) -> str:
        """Where the active scenario sits right now: idle | building | peak | recovering | recovered."""
        chans = SCEN[self.scenario]
        if not chans:
            return "idle"
        x = self.t - self.t0
        ch = "rain" if "rain" in chans else chans[0]
        xs, ys = CH[ch]
        if x >= xs[-1]:
            return "recovered"
        now = float(np.interp(x, xs, ys))
        nxt = float(np.interp(min(x + 1.0, xs[-1]), xs, ys))
        if now >= 0.92 * max(ys):
            return "peak"
        if nxt > now:
            return "building"
        if nxt < now:
            return "recovering"
        return "building" if now > 0 else "idle"

    def progression(self) -> dict:
        """Scenario progression: per-channel intensity curves + the current position.
        Drives the Simulation page's storm-progression view (straight from the CH curves)."""
        x = self.t - self.t0
        channels = [dict(channel=ch, label=CH_LBL.get(ch, ch), intensity=round(self.intensity(ch), 3),
                         duration_min=int(CH[ch][0][-1]),
                         curve=[[int(a), float(b)] for a, b in zip(*CH[ch])])
                    for ch in SCEN[self.scenario]]
        dur = max((c["duration_min"] for c in channels), default=0)
        return dict(scenario=self.scenario, phase=self.phase(), elapsed_min=int(x), duration_min=dur,
                    progress_pct=round(100.0 * min(x, dur) / dur, 1) if dur else 0.0,
                    channels=channels, simulated=True, generated_at=self.ts())

    def record(self):
        """Append one replay frame per tick so GET /api/replay can scrub the run."""
        self.replay.append(dict(
            tick=self.t, time=self.ts(), scenario=self.scenario, scenario_time=self.t - self.t0,
            phase=self.phase(),
            health=self.health_hist[-1] if self.health_hist else round(self.health()["score"], 1),
            kpis=dict(anomalies=sum(1 for a in self.anoms.values() if a["status"] == "active"),
                      disruptions=sum(1 for d in self.disr.values() if d["state"] != "RESOLVED"),
                      alerts=sum(1 for a in self.alerts.values() if a["status"] == "active")),
            zones={z: {m: round(self.cur.get((z, m), 0), 2) for m in M} for z in ZONES},
        ))

    def pos(self, z: str, m: str):
        return round(ZONES[z][0] + M[m]["off"][0], 5), round(ZONES[z][1] + M[m]["off"][1], 5)

    def emit(self, m: str, z: str, v: float, sev: str, meta=None):
        self.seq += 1
        la, lo = self.pos(z, m)
        ev = dict(id=f"event-{self.seq:05d}", source=M[m]["src"], event_type=m, timestamp=self.ts(),
                  latitude=la, longitude=lo, zone=z, severity=sev, value=round(float(v), 2),
                  unit=M[m]["unit"], metadata=meta or {"simulated": True})
        self.events.append(ev)
        self.src[M[m]["src"]]["count"] += 1
        self.push("event_created", ev)

    # ------------------------------------------------- ingestion + anomaly engine
    def observe(self, quiet: bool = False):
        for z in ZONES:
            for m, c in M.items():
                if c["src"] in self.offline:
                    continue
                I = self.intensity(c["ch"]) * WEIGHT[z]
                v = c["base"] + c["eff"] * I + float(self.rng.normal(0, c["floor"] * 0.35))
                v = max(0.0, v)
                if m == "traffic":
                    v = min(100.0, v)
                self.cur[(z, m)] = v
                if not self._warm:
                    self.zone_series[(z, m)].append((self.t, v))
                    self.series[m].append((self.t, v))
                self.src[c["src"]]["last_t"] = self.t
                self.src[c["src"]]["latency"] = round(70 + float(self.rng.normal(0, 8)))
                self.detect(z, m, v, quiet)

    # ------------------------------------------------- feature engineering
    def rolling(self, z: str, m: str, win: int) -> Optional[float]:
        """Rolling mean over the last `win` minutes using ONLY t <= current tick."""
        pts = [v for (t, v) in self.zone_series[(z, m)] if t <= self.t and v is not None
               and not (isinstance(v, float) and math.isnan(v))][-win:]
        return float(np.mean(pts)) if pts else None

    def ml_zone(self, z: str) -> Optional[dict]:
        """
        Layer-2 ML anomaly detection: Isolation Forest over the current
        multi-signal vector (rainfall, traffic, complaints, incidents) fitted on
        the last IFOREST_WINDOW minutes of that zone ONLY (no future leakage).
        The model is refitted every IFOREST_REFIT ticks (features are slow-moving);
        scoring the current vector happens every tick against the cached model.
        Returns {score: 0-100, flagged: bool, rows: n} or None during warm-up.
        """
        if not SKLEARN:
            return None
        if self._ml_t != self.t:            # per-tick score cache (refit cache persists)
            self._ml, self._ml_t = {}, self.t
        if z in self._ml:
            return self._ml[z]
        metrics = list(M)
        cached = self._ml_models.get(z)
        if cached and self.t - cached["fitted_at"] < IFOREST_REFIT:
            model, span_hi, span_lo, rows_n = cached["model"], cached["hi"], cached["lo"], cached["rows"]
        else:
            by_t: dict = {}
            for m in metrics:
                for t, v in self.zone_series[(z, m)]:
                    if t <= self.t and v is not None and not (isinstance(v, float) and math.isnan(v)):
                        by_t.setdefault(t, {})[m] = v
            rows = [[by_t[t][m] for m in metrics] for t in sorted(by_t) if len(by_t[t]) == len(metrics)]
            rows = rows[-IFOREST_WINDOW:]
            if len(rows) < IFOREST_MIN_ROWS:
                self._ml[z] = None          # not enough clean history -> no ML opinion
                return None
            X = np.asarray(rows, dtype=float)
            model = IsolationForest(n_estimators=32, contamination=IFOREST_CONTAMINATION,
                                    random_state=42, n_jobs=1)   # deterministic
            model.fit(X)
            train_scores = model.score_samples(X)
            span_hi, span_lo = float(train_scores.max()), float(train_scores.min())
            rows_n = len(rows)
            self._ml_models[z] = dict(model=model, hi=span_hi, lo=span_lo, rows=rows_n,
                                      fitted_at=self.t)
        cur = [self.cur.get((z, m)) for m in metrics]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in cur):
            self._ml[z] = None
            return None
        cur_v = np.asarray([cur], dtype=float)
        cur_s = float(model.score_samples(cur_v)[0])
        span = span_hi - span_lo
        ml = 0.0 if span < 1e-9 else clip((span_hi - cur_s) / span * 100.0)
        out = dict(score=round(ml), flagged=bool(model.predict(cur_v)[0] == -1),
                   rows=rows_n, window_min=IFOREST_WINDOW)
        self._ml[z] = out
        return out

    def detect(self, z: str, m: str, v: float, quiet: bool):
        """
        Anomaly rule: value >= baseline_mean + ANOMALY_Z_THRESHOLD * baseline_std
        AND value >= a practical floor. The baseline learns ONLY from
        non-anomalous data (EWMA), so a storm is never absorbed into 'normal'
        while it is active. Insufficient history / zero std / missing values are
        all handled: a missing (NaN / None) reading never creates an anomaly.
        """
        c = M[m]
        k = (z, m)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            # Missing measurement: keep the last baseline, never raise an anomaly.
            return
        d = self.det.setdefault(k, dict(mean=v, var=(c["floor"] * 0.35) ** 2, streak=0))
        std = max(math.sqrt(d["var"]), c["floor"] * 0.35)
        zs = (v - d["mean"]) / std
        bz = zs * c["sign"]
        base = d["mean"]

        if bz < ANOMALY_Z_THRESHOLD:  # learn only from ordinary readings
            diff = v - d["mean"]
            d["mean"] += 0.05 * diff
            d["var"] = 0.95 * (d["var"] + 0.05 * diff * diff)
        d["streak"] = d["streak"] + 1 if bz >= ANOMALY_Z_THRESHOLD else 0

        a = self.anoms.get(self.act.get(k))
        floor = c["floor"]
        # statistically unusual AND practically significant AND persistent enough
        if bz >= ANOMALY_Z_THRESHOLD and v >= floor and d["streak"] - 1 >= ANOMALY_PERSISTENCE:
            b = base if abs(base) > 1e-6 else 1.0
            # --- feature engineering: rolling baselines (15/30/60 min, past data only)
            r15, r30, r60 = (self.rolling(z, m, w) for w in (15, 30, 60))
            ref30 = r30 if r30 is not None else base
            roll_dev = min(100.0, abs(v - ref30) / max(abs(ref30), floor, 1e-6) * 50.0)
            # --- Layer 1: statistical component (z-score scaled to 0-100)
            stat = min(100.0, abs(zs) / 6.0 * 100.0)
            # --- Layer 3: temporal persistence component
            pers = min(100.0, d["streak"] / 8.0 * 100.0)
            # --- Layer 2: ML component (Isolation Forest), optional
            ml = self.ml_zone(z)
            ml_score = ml["score"] if ml else None
            if ml_score is not None:
                anomaly_score = round(0.45 * stat + 0.25 * roll_dev + 0.15 * pers + 0.15 * ml_score)
            else:
                anomaly_score = round(0.55 * stat + 0.30 * roll_dev + 0.15 * pers)
            upd = dict(baseline=round(base, 2), current=round(v, 2), deviation=round(v - base, 2),
                       pct_change=round((v - base) / b * 100, 1), z_score=round(zs, 2),
                       strength=round(min(1.0, abs(zs) / 6.0), 2), severity=sevz(zs),
                       consecutive_steps=d["streak"], threshold=round(base + ANOMALY_Z_THRESHOLD * std, 2),
                       rolling_15=round(r15, 2) if r15 is not None else None,
                       rolling_30=round(r30, 2) if r30 is not None else None,
                       rolling_60=round(r60, 2) if r60 is not None else None,
                       anomaly_score=anomaly_score, score_band=score_band(anomaly_score),
                       ml_anomaly_score=ml_score, ml_flagged=(ml["flagged"] if ml else None),
                       ml_model=("IsolationForest" if ml else "unavailable"),
                       updated=self.ts())
            upd["explanation"] = (
                f"{LBL[m]} in {z} is {upd['current']} {c['unit']} versus an EWMA baseline of "
                f"{upd['baseline']} ({upd['pct_change']}% change), which is {abs(upd['z_score'])} standard "
                f"deviations (threshold {ANOMALY_Z_THRESHOLD:g}σ = {upd['threshold']} {c['unit']}) and above the "
                f"practical significance floor of {c['floor']} {c['unit']}. Rolling 30-min average: "
                f"{upd['rolling_30']}. Persistence: {upd['consecutive_steps']} consecutive step(s). "
                f"Anomaly score: {anomaly_score}/100 ({upd['score_band']})"
                + (f" [ML IsolationForest: {ml_score}/100{' , flagged' if ml['flagged'] else ''}]."
                   if ml else ".")
            )
            if a:
                a.update(upd)
            else:
                self.seq += 1
                la, lo = self.pos(z, m)
                a = dict(id=f"anom-{self.seq:04d}", source=c["src"], metric=m, zone=z, latitude=la,
                         longitude=lo, timestamp=self.ts(), first_t=self.t, status="active",
                         unit=c["unit"], **upd)
                self.anoms[a["id"]] = a
                self.act[k] = a["id"]
                if not quiet:
                    log.debug("anomaly %s %s %s z=%s", a["id"], z, m, a["z_score"])
                    self.push("anomaly_detected", a)
            if not quiet:
                self.emit(m, z, v, upd["severity"], {"simulated": True, "anomaly_id": a["id"], "z_score": upd["z_score"]})
        elif a and bz < 1.5:
            a["status"] = "resolved"
            a["resolved_at"] = self.ts()
            self.act.pop(k, None)

    # ------------------------------------------------- lagged temporal links
    def correlate(self):
        """
        Lagged temporal relationships A(t) -> B(t+lag) for lag in LAGS
        (0/15/30/45/60 min), per zone, using only observations up to the current
        tick. Output wording is direction-aware; correlation is never causation.
        """
        live = [a for a in self.anoms.values() if a["status"] == "active"]
        for z in ZONES:
            pairs_out = []
            series = {}
            for m in M:
                pts = [(t, v) for (t, v) in self.zone_series[(z, m)] if t <= self.t]
                if pts:
                    series[m] = dict(zip([p[0] for p in pts], [p[1] for p in pts]))
            for (a_m, b_m) in (("rainfall", "traffic"), ("rainfall", "complaints"), ("traffic", "complaints")):
                if a_m not in series or b_m not in series:
                    continue
                for lag in LAGS:  # minutes (1 tick = 1 simulated minute)
                    xs, ys = [], []
                    for t, av in series[a_m].items():
                        bv = series[b_m].get(t + lag)
                        if bv is not None:
                            xs.append(av)
                            ys.append(bv)
                    if len(xs) >= 8:
                        r = float(np.corrcoef(xs, ys)[0, 1])
                        if not np.isnan(r):
                            pairs_out.append(dict(
                                a=a_m, b=b_m, lag_minutes=lag, r=round(r, 2),
                                classification=correlation_label(r),
                                sentence=(f"{LBL[a_m]} changes preceded {LBL[b_m]} changes by approximately "
                                          f"{lag} minutes (r = {round(r, 2)} — possible temporal "
                                          f"association, not a confirmed cause)." if lag > 0 and r >= 0.2 else
                                          f"{LBL[a_m]} and {LBL[b_m]} show a {correlation_label(r).lower()} "
                                          f"relationship in {zone_label(z)} (temporal association only).")))
            pairs_out.sort(key=lambda p: abs(p["r"]), reverse=True)

            srcs = sorted({a["source"] for a in live if a["zone"] == z})
            old = self.corrs.get(z)
            if len(live) < 2 or len(srcs) < 2:
                if old and old["status"] == "active":
                    old["status"] = "resolved"
                self.corrs[z] = (dict(id=f"corr-{z}", zone=zone_label(z), sources=srcs, lagged=pairs_out[:6],
                                      status="resolved", updated=self.ts()) if (pairs_out or old) else None)
                if self.corrs[z] is None:
                    self.corrs.pop(z, None)
                continue

            zs_mean = float(np.mean([abs(a["z_score"]) for a in live if a["zone"] == z]))
            # Co-activity: how long ALL these signals have been abnormal together.
            firsts = [a["first_t"] for a in live if a["zone"] == z]
            co_active_min = (self.t - min(firsts)) if firsts else 0
            n_sig = len({a["metric"] for a in live if a["zone"] == z})
            streaks = [a["consecutive_steps"] for a in live if a["zone"] == z]
            # --- explainable 0-100 components, weighted into Event Confidence ---
            spread = (max(firsts) - min(firsts)) if len(firsts) > 1 else 0
            comp = dict(
                anomaly_strength=round(min(100.0, 50.0 + zs_mean / 6.0 * 50.0), 1),
                signal_diversity=round(min(100.0, 50.0 + max(0, n_sig - 2) * 25.0), 1),
                temporal_proximity=round(max(50.0, 100.0 - 2.0 * spread), 1),
                persistence=round(min(100.0, 20.0 + max(0, (max(streaks) if streaks else 1) - 1) * 10.0), 1),
                spatial_concentration=round(100.0 * len([a for a in live if a["zone"] == z]) / max(1, len(live)), 1),
            )
            conf = float(min(CONF["cap"], max(0.0, sum(CONF_W[k] * comp[k] for k in CONF_W))))
            metrics_active = sorted({a["metric"] for a in live if a["zone"] == z})
            etype = classify_event(metrics_active)

            c = dict(id=f"corr-{z}", zone=zone_label(z), sources=srcs, lagged=pairs_out[:6],
                     lagged_all=pairs_out,
                     metrics=metrics_active,
                     signal_count=n_sig, co_active_min=co_active_min, mean_z=round(zs_mean, 2),
                     confidence=round(conf), confidence_kind="CityPulse Event Confidence (prototype)",
                     confidence_breakdown=comp, confidence_weights=CONF_W,
                     event_type=etype, event_label=EVENT_TYPES[etype],
                     label=EVENT_TYPES[etype], status="active", updated=self.ts(),
                     latitude=ZONES[z][0], longitude=ZONES[z][1],
                     evidence=self.evidence(z, live, pairs_out),
                     note="Signals increased in sequence within the event window — a temporal association, not a confirmed cause.")
            if old and old.get("status") == "active":
                c["timestamp"] = old.get("timestamp", self.ts())
            else:
                c["timestamp"] = self.ts()
                self.push("correlation_detected", c)
            self.corrs[z] = c

    # ------------------------------------------------- disruption lifecycle
    def evidence(self, z: str, live, pairs):
        """Supporting observations behind a possible multi-signal event (explainability)."""
        out = []
        for a in sorted((x for x in live if x["zone"] == z), key=lambda x: -x["strength"]):
            out.append(dict(kind="anomaly", metric=a["metric"], label=LBL[a["metric"]], source=a["source"],
                            current=a["current"], baseline=a["baseline"], unit=a["unit"],
                            z_score=a["z_score"], severity=a["severity"], first_seen=a["timestamp"],
                            steps=a["consecutive_steps"],
                            text=f"{LBL[a['metric']]} {a['current']} {a['unit']} vs baseline {a['baseline']} "
                                 f"(z = {a['z_score']}, {a['severity']})"))
        for p in pairs:
            if abs(p["r"]) >= 0.4:
                out.append(dict(kind="lag", metric=f"{p['a']}->{p['b']}", label=f"{LBL[p['a']]} → {LBL[p['b']]}",
                                lag_minutes=p["lag_minutes"], r=p["r"], classification=p["classification"],
                                text=p["sentence"]))
        return out[:10]

    def raw_score(self, z: str) -> float:
        vals = [a["strength"] for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z]
        return min(1.0, sum(vals) / 3)

    def disrupt(self):
        for z in ZONES:
            c = self.corrs.get(z)
            act = bool(c and c.get("status") == "active")
            d = self.disr.get(self.dz.get(z))
            ok = act and c["signal_count"] >= 3 and c["mean_z"] >= 2.5 and c["confidence"] >= 60
            hold = act and c["confidence"] >= 45

            if not d and ok:
                self.seq += 1
                r = self.raw_score(z)
                rk = self.risk(z)
                d = dict(id=f"disr-{self.seq:04d}", zone=zone_label(z), state="DETECTED",
                         lifecycle={"DETECTED": self.ts()}, started=self.ts(), first_t=self.t,
                         score=round(r, 2), peak=r, severity="moderate", sources=c["sources"],
                         correlation_id=c["id"], confidence=c["confidence"], confidence_kind=c["confidence_kind"],
                         confidence_breakdown=c.get("confidence_breakdown"), confidence_weights=CONF_W,
                         event_type=c.get("event_type", "UNKNOWN_MULTI_SIGNAL_EVENT"),
                         event_label=c.get("event_label", EVENT_TYPES["UNKNOWN_MULTI_SIGNAL_EVENT"]),
                         trend="developing", risk=rk["score"], risk_band=rk["band"],
                         risk_detail=rk, score_hist=[round(r, 2)],
                         sequence=" → ".join(m.title() for m in c.get("metrics", [])),
                         note="Signals increased in sequence within the event window. Possible temporal association — not a confirmed cause.",
                         status="active", acknowledged_at=None, resolved_at=None,
                         evidence=c.get("evidence", []), latitude=ZONES[z][0], longitude=ZONES[z][1],
                         duration_min=0)
                self.disr[d["id"]] = d
                self.dz[z] = d["id"]
                self.push("disruption_created", d)
                self.alert("WATCH", f"Possible civic disruption in {zone_label(z)}",
                           f"{c['signal_count']} signal types rising together (Event Confidence {c['confidence']}%). "
                           "Signals increased in sequence — not a confirmed cause.", z, d, f"{d['id']}-w")
            elif d and d["state"] != "RESOLVED":
                if not hold:
                    d["state"] = "RESOLVED"
                    d["status"] = "resolved"
                    d["resolved_at"] = self.ts()
                    d["lifecycle"]["RESOLVED"] = self.ts()
                    self.dz.pop(z, None)
                    self.push("disruption_updated", d)
                    self.alert("INFO", f"Disruption resolved in {zone_label(z)}",
                               "Signals have returned toward their baselines.", z, d, f"{d['id']}-r")
                    continue
                prev = d["score"]
                d["score"] = round(0.8 * prev + 0.2 * self.raw_score(z), 2)
                d["peak"] = max(d["peak"], d["score"])
                delta = d["score"] - prev
                old = d["state"]
                new = old
                if old == "DETECTED" and self.t - d["first_t"] >= 2:
                    new = "MONITORING"
                elif delta > 0.01:
                    new = "ESCALATING"
                elif old in ("ESCALATING", "PEAK") and d["score"] >= 0.9 * d["peak"]:
                    new = "PEAK"
                elif old in ("ESCALATING", "PEAK", "RECOVERING") and d["score"] < 0.85 * d["peak"]:
                    new = "RECOVERING"
                d["confidence"] = c["confidence"]
                rk = self.risk(z)
                d["risk"], d["risk_band"], d["risk_detail"] = rk["score"], rk["band"], rk
                d["confidence_breakdown"] = c.get("confidence_breakdown", d.get("confidence_breakdown"))
                d["event_type"] = c.get("event_type", d.get("event_type", "UNKNOWN_MULTI_SIGNAL_EVENT"))
                d["event_label"] = c.get("event_label", d.get("event_label"))
                d["trend"] = ("escalating" if delta > 0.01 else
                              "recovering" if delta < -0.01 else "stable")
                hist = d.setdefault("score_hist", [])
                hist.append(d["score"])
                del hist[:-60]                       # bounded history for forecasting
                d["duration_min"] = self.t - d["first_t"]
                d["evidence"] = c.get("evidence", d.get("evidence", []))
                d["severity"] = "critical" if d["peak"] >= 0.85 else "high" if d["peak"] >= 0.6 else "moderate"
                if new != old:
                    d["state"] = new
                    d["lifecycle"].setdefault(new, self.ts())
                    self.push("disruption_updated", d)
                    lv = {"ESCALATING": "WARNING", "PEAK": "CRITICAL", "RECOVERING": "INFO"}.get(new)
                    if lv:
                        self.alert(lv, f"Disruption {new.lower()} in {zone_label(z)}",
                                   f"Event Confidence {c['confidence']}%. Possible temporal association — not a confirmed cause.",
                                   z, d, f"{d['id']}-{new}")

    def alert(self, level: str, title: str, msg: str, zone: str, d, key: str):
        if key in self.akeys:
            return
        self.akeys.add(key)
        self.seq += 1
        a = dict(id=f"alert-{self.seq:04d}", level=level, title=title, message=msg, zone=zone_label(zone),
                 disruption_id=d["id"], status="active", timestamp=self.ts(),
                 latitude=ZONES[zone][0], longitude=ZONES[zone][1])
        self.alerts[a["id"]] = a
        self.push("alert_created", a)

    # ------------------------------------------------- risk engine (separate from anomaly/event)
    def risk(self, z: str) -> dict:
        """
        Risk Score 0-100 for a zone — deliberately DISTINCT from anomaly severity
        and event confidence. Inputs: anomaly severity, event confidence, signal
        count, persistence, incident severity, forecast trend, spatial share.
        """
        live = [a for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z]
        c = self.corrs.get(z)
        active = bool(c and c.get("status") == "active")
        d = self.disr.get(self.dz.get(z))
        total_live = sum(1 for a in self.anoms.values() if a["status"] == "active")
        mean_z = float(np.mean([abs(a["z_score"]) for a in live])) if live else 0.0
        anomaly_sev = min(100.0, mean_z / 6.0 * 100.0)
        event_conf = float(c["confidence"]) if active else 0.0
        signal_cnt = min(100.0, len({a["metric"] for a in live}) / 4.0 * 100.0)
        spatial = 100.0 * len(live) / max(1, total_live)
        persist = min(100.0, (max((a["consecutive_steps"] for a in live), default=0)) / 8.0 * 100.0)
        inc = self.cur.get((z, "incidents")) or 0.0
        incident_sev = min(100.0, max(0.0, (inc - M["incidents"]["floor"])) /
                           max(M["incidents"]["eff"], 1e-6) * 100.0)
        trend_adj = {"ESCALATING": 6.0, "PEAK": 6.0, "RECOVERING": -8.0,
                     "MONITORING": 0.0, "DETECTED": -2.0}.get(d["state"] if d else "", 0.0)
        parts = dict(anomaly_severity=round(anomaly_sev, 1), event_confidence=round(event_conf, 1),
                     signal_count=round(signal_cnt, 1), persistence=round(persist, 1),
                     incident_severity=round(incident_sev, 1), spatial_share=round(spatial, 1))
        raw = (0.30 * anomaly_sev + 0.25 * event_conf + 0.15 * signal_cnt +
               0.10 * spatial + 0.10 * persist + 0.10 * incident_sev + trend_adj)
        score = round(clip(raw), 1)
        return dict(score=score, band=risk_band(score), parts=parts, trend_adjustment=trend_adj,
                    bands=RISK_BANDS,
                    note="Prototype risk index (0-100): evidence-based decision support, not an official rating.")

    def risk_global(self) -> dict:
        """City-wide risk = highest zone risk (the operator cares about the worst spot)."""
        per = {z: self.risk(z) for z in ZONES}
        worst_z = max(per, key=lambda z: per[z]["score"])
        top = per[worst_z]
        return dict(score=top["score"], band=top["band"], zone=zone_label(worst_z),
                    zones={zone_label(z): per[z]["score"] for z in ZONES},
                    parts=top["parts"], note=top["note"])

    # ------------------------------------------------- city health
    def comps(self, z: Optional[str] = None):
        """
        Health components per zone, each 0-100 where HIGHER = HEALTHIER
        (displayed as health bars in the UI). Severity scales are shifted so
        an ordinary working city is genuinely healthy: congestion 25% -> ~0
        severity, base complaint volume -> 0 severity, drizzle -> ~0 severity.
        A component whose feed is offline is reported as None (unknown) rather
        than a fabricated value.
        """
        def one(zz):
            g = lambda m: self.cur.get((zz, m), M[m]["base"])
            ctraffic = None if "traffic" in self.offline else round(100 - clip((g("traffic") - 25.0) * (100.0 / 75.0)), 1)
            cweather = None if "weather" in self.offline else round(100 - clip((g("rainfall") / 40.0) * 100), 1)
            ccompl = None if "complaints" in self.offline else round(100 - clip((g("complaints") - 4.0) * (100.0 / 16.0)), 1)
            out = {"Traffic": ctraffic, "Weather": cweather, "Complaints": ccompl}
            return {k: v for k, v in out.items() if v is not None}
        if z:
            return one(z)
        per = [one(x) for x in ZONES]
        return {k: round(0.5 * float(np.mean([p[k] for p in per if k in p])) +
                         0.5 * min(p[k] for p in per if k in p), 1)
                for k in W if any(k in p for p in per)}

    # component -> feed that must be online for the component to be usable
    COMP_SRC = {"Traffic": "traffic", "Weather": "weather", "Complaints": "complaints"}

    def health(self):
        """
        City health = weighted mean of the available components (weights
        re-normalised when a feed is offline) minus penalties for active
        anomalies / disruptions. Fully deterministic from live readings.
        """
        c = self.comps()
        used = {k: W[k] for k in c if k in W}
        have = all(k in c for k in W)
        price = [k for k in W if k not in c]
        base = (sum(c[k] * used[k] for k in used) / sum(used.values())) if used else 0.0
        na = sum(1 for a in self.anoms.values() if a["status"] == "active")
        nd = sum(1 for d in self.disr.values() if d["state"] != "RESOLVED")
        score = max(0.0, base - min(15, 1.5 * na) - min(10, 5 * nd))
        prev = self.health_hist[-10] if len(self.health_hist) >= 10 else (self.health_hist[0] if self.health_hist else score)
        st = "HEALTHY" if score >= 85 else "STABLE" if score >= 70 else "DEGRADED" if score >= 50 else "CRITICAL"
        return dict(score=round(score, 1), status=st,
                    trend_pct=round((score - prev) / prev * 100, 1) if prev else 0.0,
                    components={k: round(v) for k, v in c.items()}, weights=W,
                    weights_used={k: used[k] / sum(used.values()) if used else 0 for k in used},
                    missing_components=price, partial=not have, penalty_anomalies=round(min(15, 1.5 * na), 1),
                    penalty_disruptions=round(min(10, 5 * nd), 1),
                    note="Weighted 0-100 components (higher = healthier) minus anomaly/disruption penalties. "
                         "Prototype index, not an official city metric.")

    def score(self):
        h = self.health()
        self.health_hist.append(h["score"])
        row = dict(t=self.ts()[11:16], health=h["score"])
        for m in M:
            row[m] = round(self.cur.get(("Zone A", m), 0), 2)
        self.hist.append(row)

    # ------------------------------------------------- summary / why-now
    def target(self):
        ds = [d for d in self.disr.values() if d["state"] != "RESOLVED"]
        if ds:
            d = max(ds, key=lambda x: x["score"])
            z = [zz for zz in ZONES if zone_label(zz) == d["zone"]][0]
            return d["zone"], self.corrs.get(z), d
        cs = [c for c in self.corrs.values() if c.get("status") == "active"]
        if cs:
            c = max(cs, key=lambda x: x["confidence"])
            z = [zz for zz in ZONES if zone_label(zz) == c["zone"]][0]
            return z, c, None
        return None, None, None

    def summary(self):
        z, c, d = self.target()
        if not z or not c:
            return dict(zone=None, headline="No active event", lines=[],
                        text="No active multi-signal event. City signals are currently within expected ranges. "
                             "Conditions are stable across all monitored zones.", simulated=True)
        lines = []
        for a in sorted((self.anoms[i] for i in self._anom_ids(z)), key=lambda a: -a["strength"]):
            b = a["baseline"] or 1
            if abs(a["pct_change"]) >= 300:
                lines.append(f"{LBL[a['metric']]} is {a['current'] / b:.1f}x baseline ({a['current']} vs {a['baseline']} {a['unit']})")
            else:
                lines.append(f"{LBL[a['metric']]} is {abs(a['pct_change']):.0f}% {'above' if a['pct_change'] > 0 else 'below'} baseline ({a['current']} vs {a['baseline']} {a['unit']})")
        lines.append(f"Signals co-active for ~{c['co_active_min']} minutes across {len(c['sources'])} independent sources.")
        lagged = next((p for p in c.get("lagged", []) if p["lag_minutes"] > 0 and p["r"] >= 0.4), None)
        if lagged:
            lines.append(lagged["sentence"])
        kind = "an elevated civic disruption pattern" if d else "a possible multi-signal civic event"
        text = (f"{c['zone']} is showing {kind}. " + " ".join((l if l.endswith(".") else l + ".") for l in lines) +
                f" CityPulse Event Confidence: {c['confidence']}% (prototype score — not a probability). "
                "Signals increased in sequence; possible relationship detected, not confirmation of cause.")
        return dict(zone=c["zone"], headline=f"CityPulse Intelligence: {c['zone']}", lines=lines, text=text,
                    confidence=c["confidence"], state=d["state"] if d else "CORRELATED", simulated=True)

    def _anom_ids(self, z: str):
        return [i for i, a in self.anoms.items() if a["status"] == "active" and a["zone"] == z]

    def what_changed(self, z: Optional[str] = None):
        z = z or (self.target()[0] or "Zone A")
        out = []
        for m, c in M.items():
            d = self.det.get((z, m))
            cur = self.cur.get((z, m))
            if not d or cur is None:
                continue
            a = self.anoms.get(self.act.get((z, m)))
            b = d["mean"] or 1
            out.append(dict(metric=m, label=LBL[m], zone=zone_label(z), value=round(cur, 2),
                            baseline=round(d["mean"], 2), unit=c["unit"],
                            pct_change=round((cur - d["mean"]) / b * 100, 1),
                            severity=a["severity"] if a else "normal",
                            direction="up" if cur >= d["mean"] else "down"))
        return out

    def predict(self, z: Optional[str] = None):
        """Prototype trend-based prediction: least-squares over the last 30 minutes."""
        z = z or "Zone A"
        items = []
        for m in M:
            pts = [(t, v) for (t, v) in self.zone_series[(z, m)] if t <= self.t][-30:]
            if len(pts) < 5:
                continue
            ys = np.array([p[1] for p in pts], dtype=float)
            xs = np.arange(len(ys), dtype=float)
            slope = float(np.polyfit(xs, ys, 1)[0])
            if ys.std() > 1e-6:
                r = float(np.corrcoef(xs, ys)[0, 1])
                fit = abs(r) if not np.isnan(r) else 0.0
            else:
                fit = 0.0
            strength = "Strong" if fit >= 0.8 else "Moderate" if fit >= 0.5 else "Low"
            projected = max(0.0, float(ys[-1] + slope * 30))
            band = max(1.0, 0.25 * abs(slope) * 30)
            items.append(dict(zone=zone_label(z), metric=m, label=LBL[m], unit=M[m]["unit"],
                              current=round(float(ys[-1]), 2), trend="up" if slope > 0.05 else "down" if slope < -0.05 else "flat",
                              value=round(projected, 1), range_low=round(max(0.0, projected - band), 1),
                              range_high=round(projected + band, 1),
                              trend_strength=strength, model="least-squares trend (30 min window)",
                              horizon_min=30, confidence=round(fit * 100), timestamp=self.ts(),
                              text=(f"{LBL[m]} may continue to rise in {zone_label(z)} over the next 30 minutes." if slope > 0.05 else
                                    f"{LBL[m]} may ease in {zone_label(z)} over the next 30 minutes." if slope < -0.05 else
                                    f"{LBL[m]} looks roughly stable in {zone_label(z)}.")))
        # --- risk forecast: where is the ZONE RISK heading over the next 30 minutes?
        rk = self.risk(z)
        d = self.disr.get(self.dz.get(z))
        proj_delta = 0.0
        if d:
            hist = d.get("score_hist") or []
            if len(hist) >= 2:
                slope = hist[-1] - hist[-2]           # event-score change per tick
                proj_delta = max(-25.0, min(25.0, slope * 30 * 100 * 0.3))
        risk_now = rk["score"]
        risk_next = round(clip(risk_now + proj_delta), 1)
        items.append(dict(zone=zone_label(z), metric="risk", label="Zone risk index",
                          unit="score 0-100", current=risk_now,
                          trend="up" if proj_delta > 1 else "down" if proj_delta < -1 else "flat",
                          value=risk_next, range_low=round(clip(risk_next - max(3.0, abs(proj_delta) * 0.5)), 1),
                          range_high=round(clip(risk_next + max(3.0, abs(proj_delta) * 0.5)), 1),
                          trend_strength="Moderate" if d else "Low",
                          model="event-score trend extrapolation", horizon_min=30,
                          confidence=70 if d else 40, timestamp=self.ts(),
                          text=(f"{rk['band']} risk in {zone_label(z)} may {'rise' if proj_delta > 1 else 'ease' if proj_delta < -1 else 'hold steady'} "
                                f"to {risk_next}/100 in the next 30 minutes.")))
        return dict(items=items, horizon_min=30, timestamp=self.ts(),
                    note="Prototype trend-based prediction — not a certainty.")

    # ------------------------------------------------- views
    def zones(self):
        out = []
        for z, (la, lo) in ZONES.items():
            c = self.comps(z)
            na = sum(1 for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z)
            wsum = sum(W[k] for k in c if k in W)
            h = max(0.0, (sum(c[k] * W[k] for k in c if k in W) / wsum if wsum else 0.0) - 1.5 * na)
            ev = self.corrs.get(z)
            rk = self.risk(z)
            out.append(dict(zone=zone_label(z), latitude=la, longitude=lo, health=round(h, 1),
                            risk=rk["score"], risk_band=rk["band"], risk_detail=rk,
                            components={k: round(v) for k, v in c.items()}, anomalies=na,
                            events=sum(1 for e in self.events if e["zone"] == z),
                            event_confidence=ev.get("confidence") if ev and ev.get("status") == "active" else None,
                            metrics={m: round(self.cur.get((z, m), 0), 2) for m in M}))
        return out

    def sources(self):
        out = []
        for k, v in self.src.items():
            off = k in self.offline
            out.append(dict(source=k, status="OFFLINE" if off else "LIVE", freshness_min=self.t - v["last_t"],
                            latency_ms=None if off else v["latency"], event_count=v["count"],
                            error_rate=100.0 if off else 0.0, last_update=self.ts(v["last_t"])))
        return out

    # ------------------------------------------------- lifecycle actions (validated)
    def _zk(self, label: str) -> str:
        return label if label in ZONES else next((z for z in ZONES if zone_label(z) == label), "Zone A")

    def disruption_get(self, did: str):
        return self.disr.get(did)

    def disruption_view(self, status: Optional[str] = None, zone: Optional[str] = None,
                        severity: Optional[str] = None, state: Optional[str] = None,
                        metric: Optional[str] = None, q: Optional[str] = None, limit: int = 200):
        """Server-side search over civic events; reused by GET /api/disruptions."""
        out = []
        needle = (q or "").strip().lower()
        for d in self.disr.values():
            if status and d.get("status") != status:
                continue
            if zone and d["zone"] != zone:
                continue
            if severity and d["severity"] != severity:
                continue
            if state and d["state"] != state:
                continue
            if metric and metric.lower() not in (str(d.get("sequence", "")) + " " +
                                                 str(d.get("evidence", "")) + " " +
                                                 str(d.get("lifecycle", {}))).lower():
                continue
            if needle and needle not in (f"{d['id']} {d['zone']} {d['state']} {d['severity']} "
                                         f"{d.get('event_label','')} {d.get('event_type','')} "
                                         f"{d.get('sequence','')} {d.get('note','')}").lower():
                continue
            out.append(d)
        out.sort(key=lambda d: d["id"], reverse=True)
        return out[:limit]

    def disruption_act(self, did: str, action: str):
        """DETECTED/ACTIVE -> ACKNOWLEDGED -> RESOLVED, validated on the server."""
        d = self.disr.get(did)
        if not d:
            return None
        resolved = d["state"] == "RESOLVED" or d.get("status") == "resolved"
        if action == "acknowledge":
            if resolved:
                raise ValueError("cannot acknowledge a resolved civic event")
            if d.get("status") == "acknowledged":
                raise ValueError("civic event is already acknowledged")
            d["status"] = "acknowledged"
            d["acknowledged_at"] = self.ts()
            d["lifecycle"]["ACKNOWLEDGED"] = self.ts()
            self.alert("INFO", f"Event {did} acknowledged",
                       f"Operator acknowledged the possible civic disruption in {d['zone']}. The event stays "
                       "active and keeps updating until its signals return toward baseline.",
                       self._zk(d["zone"]), d, f"{did}-ack")
        else:  # resolve
            if resolved:
                raise ValueError("civic event is already resolved")
            d["state"] = "RESOLVED"
            d["status"] = "resolved"
            d["resolved_at"] = self.ts()
            d["resolved_by"] = "operator"
            d["lifecycle"]["RESOLVED"] = self.ts()
            if self.dz.get(self._zk(d["zone"])) == did:
                self.dz.pop(self._zk(d["zone"]), None)
            self.alert("INFO", f"Event {did} resolved by operator",
                       f"{d['zone']} civic event closed manually. Underlying feeds keep streaming and a new "
                       "event is detected if signals rise again.", self._zk(d["zone"]), d, f"{did}-resolve")
        d["updated_at"] = self.ts()
        self.push("disruption_updated", d)
        return d

    def alert_act(self, aid: str, action: str):
        a = self.alerts.get(aid)
        if not a:
            return None
        if action == "acknowledge":
            if a["status"] == "resolved":
                raise ValueError("cannot acknowledge a resolved alert")
            if a["status"] == "acknowledged":
                raise ValueError("alert is already acknowledged")
            a["status"] = "acknowledged"
            a["acknowledged_at"] = self.ts()
        else:
            if a["status"] == "resolved":
                raise ValueError("alert is already resolved")
            a["status"] = "resolved"
            a["resolved_at"] = self.ts()
        a["updated_at"] = self.ts()
        self.push("alert_updated", a)
        return a

    def alert_view(self, status: Optional[str] = None, level: Optional[str] = None, zone: Optional[str] = None,
                   q: Optional[str] = None, limit: int = 200):
        needle = (q or "").strip().lower()
        out = [a for a in self.alerts.values()
               if (not status or a["status"] == status) and (not level or a["level"] == level)
               and (not zone or a["zone"] == zone)
               and (not needle or needle in f"{a['id']} {a['title']} {a['message']} {a['zone']} {a['level']}".lower())]
        out.sort(key=lambda a: a["id"], reverse=True)
        return out[:limit]

    def anomaly_view(self, metric: Optional[str] = None, severity: Optional[str] = None, limit: int = 200):
        out = [a for a in self.anoms.values()
               if a["status"] == "active" and (not metric or a["metric"] == metric)
               and (not severity or a["severity"] == severity)]
        out.sort(key=lambda a: -a["strength"])
        return out[:limit]

    def event_get(self, eid: str):
        return next((e for e in reversed(self.events) if e["id"] == eid), None)

    def coverage(self):
        """Data coverage + freshness so the UI can state what is simulated and how fresh it is."""
        metrics_live, metrics_total = 0, len(M) * len(ZONES)
        for z in ZONES:
            for m, c in M.items():
                if c["src"] not in self.offline and (z, m) in self.cur:
                    metrics_live += 1
        return dict(mode="simulation", simulated=True, source_kind="synthetic city telemetry",
                    tick=self.t, city_time=self.ts(), speed=self.speed, scenario=self.scenario,
                    zones=len(ZONES), metrics=len(M), metric_streams_live=metrics_live,
                    metric_streams_total=metrics_total,
                    coverage_pct=round(100 * metrics_live / metrics_total, 1) if metrics_total else 0.0,
                    offline_sources=sorted(self.offline),
                    history_points=max((len(v) for v in self.zone_series.values()), default=0),
                    disclaimer="All CityPulse values come from a local simulation of a fictional city. "
                               "No external government, sensor or weather API is connected.")

    # ------------------------------------------------- What Needs Attention?
    def attention(self):
        """'What Needs Attention?' — prioritised, actionable, built ONLY from live evidence."""
        warnings = []
        for zz, cc in self.corrs.items():
            if cc and cc.get("status") == "active" and 45 <= cc.get("confidence", 0) < 60:
                warnings.append(dict(zone=zone_label(zz), confidence=cc["confidence"],
                                     event_type=cc.get("event_type"), state="EARLY WARNING"))
        z, c, d = self.target()
        if not z or not c:
            return dict(level="ALL_CLEAR", headline="Nothing urgent needs attention", zone=None,
                        risk=self.risk_global(), confidence=None, state="NORMAL", trend="stable",
                        signals=[], recommendations=[], early_warnings=warnings, simulated=True,
                        text="No active multi-signal events. City signals are within expected ranges.")
        rk = self.risk(z)
        live = sorted((a for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z),
                      key=lambda a: -a.get("anomaly_score", a.get("strength", 0) * 100))
        signals = [dict(label=LBL[a["metric"]], metric=a["metric"], severity=a["severity"],
                        score=a.get("anomaly_score"), band=a.get("score_band"),
                        z=a["z_score"], current=a["current"], unit=a["unit"]) for a in live[:5]]
        present = {a["metric"] for a in live}
        recs = []
        if "rainfall" in present:
            recs.append(f"Inspect drains and underpasses in {c['zone']}; stage traffic diversions on the worst corridors.")
        if "traffic" in present:
            recs.append("Prioritise signal timing and deploy traffic wardens at the busiest junctions.")
        if "incidents" in present:
            recs.append("Dispatch first-response teams to the incident cluster and publish alternate routes.")
        if "complaints" in present:
            recs.append("Triage the civic-report backlog for the zone and cross-check reports with field teams.")
        top = signals[0] if signals else None
        text = (f"{c['zone']} needs attention: {c.get('event_label', c['label'])} — "
                f"risk {rk['score']}/100 ({rk['band']}), event confidence {c['confidence']}%. "
                + (f"Strongest signal: {top['label']} at {top['current']} {top['unit']} ({top['band']}, score {top['score']}/100). " if top else "")
                + f"{c['signal_count']} signal types are active together. Signals increased in sequence — a temporal association, not a confirmed cause.")
        return dict(level=rk["band"], headline=f"{rk['band']} risk — {c.get('event_label', c['label'])} in {c['zone']}",
                    zone=c["zone"], confidence=c["confidence"], state=d["state"] if d else "CORRELATED",
                    trend=d.get("trend", "developing") if d else "stable", risk=rk,
                    event_type=c.get("event_type"), event_label=c.get("event_label"),
                    signals=signals, recommendations=recs, early_warnings=warnings,
                    text=text, simulated=True)

    # ------------------------------------------------- event timeline
    def timeline(self):
        """Chronological timeline built from ACTUAL detection records (no invented entries)."""
        items = []
        for a in self.anoms.values():
            items.append(dict(t=a["timestamp"], kind="anomaly", zone=zone_label(a["zone"]),
                              title=f"{LBL[a['metric']]} anomaly detected",
                              text=(f"{a['current']} {a['unit']} vs baseline {a['baseline']} (z = {a['z_score']}, "
                                    f"score {a.get('anomaly_score', '—')}/100)"),
                              severity=a["severity"], ref=a["id"]))
            if a.get("resolved_at"):
                items.append(dict(t=a["resolved_at"], kind="resolved", zone=zone_label(a["zone"]),
                                  title=f"{LBL[a['metric']]} anomaly resolved",
                                  text=f"{LBL[a['metric']]} returned toward its baseline in {zone_label(a['zone'])}.",
                                  severity="low", ref=a["id"]))
        for d in self.disr.values():
            for state, when in d.get("lifecycle", {}).items():
                items.append(dict(t=when, kind="event", zone=d["zone"],
                                  title=f"{d.get('event_label', 'Civic event')} — {state}",
                                  text=(f"Event Confidence {d['confidence']}%, risk {d.get('risk', '—')} "
                                        f"({d.get('risk_band', '—')}). Temporal association — not a confirmed cause."),
                                  severity=d.get("severity", "moderate"), ref=d["id"]))
        for al in self.alerts.values():
            sev = {"CRITICAL": "critical", "WARNING": "high", "WATCH": "moderate"}.get(al["level"], "low")
            items.append(dict(t=al["timestamp"], kind="alert", zone=al["zone"], title=al["title"],
                              text=al["message"], severity=sev, ref=al["id"]))
        items.sort(key=lambda x: x["t"] or "")
        return items[-80:]

    # ------------------------------------------------- AI Civic Analyst
    def analyst(self, event_id: Optional[str] = None):
        """
        AI Civic Analyst: explains a DETECTED event in plain language, from
        structured evidence only. Detection decides whether an event exists;
        this layer never invents metrics or causal claims. Deterministic template
        by default; CITYPULSE_LLM_URL (optional) renders the same payload via LLM.
        """
        if event_id:
            d = self.disr.get(event_id)
            if not d:
                raise ValueError(f"unknown event: {event_id}")
            z = next((zz for zz in ZONES if zone_label(zz) == d["zone"]), "Zone A")
            c = self.corrs.get(z)
        else:
            z, c, d = self.target()
        if not z or not c:
            return dict(event=None, narrative="No active multi-signal event. City signals are within expected ranges.",
                        generated_at=self.ts(), engine="deterministic analyst template", simulated=True)
        rk = self.risk(z)
        att = self.attention()
        live = [a for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z]
        pred_items = [p for p in self.predict(z)["items"] if p.get("trend") != "flat"][:3]
        payload = dict(
            event_id=d["id"] if d else c["id"], zone=c["zone"],
            event_type=c.get("event_type"), event_label=c.get("event_label"),
            state=d["state"] if d else "CORRELATED", trend=d.get("trend", "developing") if d else "stable",
            confidence=c["confidence"], confidence_breakdown=c.get("confidence_breakdown"),
            confidence_kind=c.get("confidence_kind"),
            risk=rk["score"], risk_band=rk["band"], risk_parts=rk["parts"],
            detected_at=(d["started"] if d else c.get("timestamp")),
            signals=[dict(label=LBL[a["metric"]], current=a["current"], baseline=a["baseline"],
                          unit=a["unit"], z=a["z_score"], score=a.get("anomaly_score"),
                          band=a.get("score_band")) for a in
                     sorted(live, key=lambda a: -a.get("anomaly_score", 0))],
            relationships=[p["sentence"] for p in c.get("lagged", []) if abs(p["r"]) >= 0.4][:3],
            forecast=[dict(label=p["label"], value=p.get("value"), unit=p["unit"],
                           horizon_min=p.get("horizon_min", 30), confidence=p.get("confidence"),
                           model=p.get("model"), text=p["text"]) for p in pred_items],
            generated_at=self.ts(), simulated=True,
        )
        sig_txt = ", ".join(f"{s['label']} {s['current']} {s['unit']} vs baseline {s['baseline']} "
                            f"(z = {s['z']}, score {s['score']}/100)" for s in payload["signals"][:4])
        lines = [
            f"What happened: {payload['event_label']} in {payload['zone']} — {payload['state'].title()} "
            f"({payload['trend']}), detected at {payload['detected_at']}.",
            f"Why it was flagged: {sig_txt or 'no live signals'}." ,
            "Event Confidence " + str(payload["confidence"]) + "% (" + str(payload["confidence_kind"]) +
            ") — breakdown: " + ", ".join(f"{k} {v}" for k, v in (payload["confidence_breakdown"] or {}).items()) + ".",
            f"Zone risk is {payload['risk']}/100 ({payload['risk_band']}).",
        ]
        if payload["relationships"]:
            lines.append("Relationships observed: " + " ".join(payload["relationships"]) +
                         " — correlation, not proof of cause.")
        if att.get("recommendations"):
            lines.append("Investigate next: " + att["recommendations"][0])
        if payload["forecast"]:
            lines.append("Forecast: " + " ".join(f["text"] for f in payload["forecast"][:2]) + " Not a certainty.")
        lines.append("Next step: confirm on the ground, then acknowledge or resolve the event so the timeline stays accurate.")
        narrative = " ".join(lines)
        engine = "deterministic analyst template"
        url = os.getenv("CITYPULSE_LLM_URL")
        if url:
            try:
                import httpx
                r = httpx.post(url, json=dict(role="Civic Analyst", payload=payload, task="explain"), timeout=8.0)
                if r.status_code == 200 and r.text.strip():
                    narrative, engine = r.text.strip()[:4000], "LLM (configured endpoint)"
            except Exception as e:  # fallback keeps the demo honest and working
                log.warning("LLM analyst unavailable, using template: %s", e)
        return dict(event=payload, narrative=narrative, engine=engine,
                    generated_at=self.ts(), simulated=True,
                    disclaimer="Generated from simulated telemetry. Detection decides whether an event exists; "
                               "this explanation never invents metrics or causal claims.")

    def meta(self):
        """Machine-readable configuration so every number in the UI is explainable."""
        return dict(
            product="CityPulse", version="2.1.0", data_mode="simulation", simulated=True,
            zones=[dict(zone=zone_label(z), latitude=ZONES[z][0], longitude=ZONES[z][1]) for z in ZONES],
            metrics=[dict(metric=m, label=LBL[m], unit=c["unit"], source=c["src"], baseline=c["base"],
                          practical_floor=c["floor"], direction="above" if c["sign"] > 0 else "below")
                     for m, c in M.items()],
            anomaly=dict(method="EWMA baseline mean/variance learned only from non-anomalous readings",
                         z_threshold=ANOMALY_Z_THRESHOLD, extra_persistence_ticks=ANOMALY_PERSISTENCE,
                         floors={m: M[m]["floor"] for m in M},
                         rolling_windows_minutes=[15, 30, 60],
                         score=dict(method="0-100 weighted blend: statistical z, rolling deviation, "
                                           "persistence, and Isolation Forest ML layer",
                                    weights_with_ml=dict(statistical=0.45, rolling=0.25, persistence=0.15, ml=0.15),
                                    weights_without_ml=dict(statistical=0.55, rolling=0.30, persistence=0.15),
                                    bands=ANOMALY_BANDS,
                                    labels=[lbl for _, lbl in ANOMALY_BAND_LABELS]),
                         ml=dict(model="sklearn.ensemble.IsolationForest", available=SKLEARN,
                                 contamination=IFOREST_CONTAMINATION, window_min=IFOREST_WINDOW,
                                 min_rows=IFOREST_MIN_ROWS, refit_ticks=IFOREST_REFIT,
                                 features=[m for m in M]),
                         note="A reading is reported when z >= threshold AND value >= practical floor; "
                              "missing readings never create anomalies."),
            correlation=dict(method="Pearson r on lagged pairs within one zone",
                             pairs=[["rainfall", "traffic"], ["rainfall", "complaints"], ["traffic", "complaints"]],
                             lags_minutes=list(LAGS), min_samples=8,
                             note="Temporal association inside a zone — not evidence of causation."),
            events=dict(min_signals=3, min_mean_z=2.5, min_confidence=60, hold_confidence=45,
                        confidence_weights=CONF_W,
                        confidence_breakdown_keys=list(CONF_W),
                        classification=dict(rules="evidence-driven from the active metric set (extensible registry)",
                                            types=EVENT_TYPES),
                        states=["DETECTED", "MONITORING", "ESCALATING", "PEAK", "RECOVERING", "RESOLVED"],
                        statuses=["active", "acknowledged", "resolved"],
                        trend_values=["escalating", "stable", "recovering", "developing"],
                        confidence_kind="CityPulse Event Confidence (prototype, not a probability)"),
            risk=dict(method="weighted blend of anomaly severity, event confidence, signal count, "
                             "persistence, incident severity and spatial share (separate from health)",
                      bands=RISK_BANDS, band_names=["LOW", "MODERATE", "HIGH", "CRITICAL"],
                      note="Prototype risk index for decision support — not an official rating."),
            health=dict(weights=W,
                        bands={"HEALTHY": ">=85", "STABLE": ">=70", "DEGRADED": ">=50", "CRITICAL": "<50"},
                        penalties=dict(per_anomaly=1.5, per_anomaly_cap=15, per_event=5, per_event_cap=10),
                        note="Components are 0-100 (higher = healthier); weights re-normalise when a feed is offline."),
            sources=SOURCES, scenarios=list(SCEN),
            scenario_registry=[dict(value=k, label=SCEN_META.get(k, {}).get("label", k),
                                    description=SCEN_META.get(k, {}).get("description", ""),
                                    channels=SCEN[k],
                                    duration_min=max((CH[c][0][-1] for c in SCEN[k]), default=0))
                               for k in SCEN],
            speeds=[0.5, 1, 2, 5, 10],
            tick_minutes=1, tick_seconds=1.0,
            disclaimer="Prototype indicators. Correlations are shown as possible links, never as causes.",
        )

    def status_(self):
        return dict(simulation_time=self.ts(), tick=self.t, speed=self.speed, scenario=self.scenario,
                    scenario_time=self.t - self.t0, phase=self.phase(), seed=self.seed, status=self.status,
                    offline_sources=sorted(self.offline), simulated=True)

    def dash(self):
        act = [a for a in self.anoms.values() if a["status"] == "active"]
        cs = [c for c in self.corrs.values() if c.get("status") == "active"]
        ds = [d for d in self.disr.values() if d["state"] != "RESOLVED"]
        al = [a for a in self.alerts.values() if a["status"] == "active"]
        src = self.sources()
        recent = sorted(self.disr.values(), key=lambda d: d["id"], reverse=True)[:25]
        return dict(sim=self.status_(), health=self.health(),
                    kpis=dict(disruptions=len(ds), anomalies=len(act), correlations=len(cs), alerts=len(al),
                              sources_live=sum(1 for x in src if x["status"] == "LIVE"), sources_total=len(src),
                              events_total=len(self.events),
                              events_acknowledged=sum(1 for d in self.disr.values() if d.get("status") == "acknowledged"),
                              events_resolved=sum(1 for d in self.disr.values() if d.get("status") == "resolved")),
                    zones=self.zones(), anomalies=act[-120:], correlations=cs, disruptions=ds,
                    recent_events=recent, alerts=al[-40:], sources=src,
                    events=list(self.events)[-40:][::-1], summary=self.summary(),
                    what_changed=self.what_changed(), predictions=self.predict(),
                    attention=self.attention(), timeline=self.timeline(),
                    risk=self.risk_global(),
                    trend=list(self.hist)[-180:], coverage=self.coverage(),
                    generated_at=self.ts(), simulated=True)

    def step(self):
        self.observe()
        self.correlate()
        self.disrupt()
        self.score()
        self.record()
        self.t += 1
        self.push("metric_updated", {"t": self.ts(), "zones": {z: {m: round(self.cur.get((z, m), 0), 2) for m in M} for z in ZONES}})
        self.push("score_updated", self.dash())


def zone_label(z: str) -> str:
    return z  # zones are already labelled "Zone A/B/C"


# ---------------------------------------------------------------------------
# FastAPI app: REST + WebSocket broadcast of the live engine
# ---------------------------------------------------------------------------

sim = Sim()
clients: set = set()


async def bcast():
    msgs = sim.drain()
    for w in list(clients):
        try:
            for m in msgs:
                await w.send_json(m)
        except Exception:
            clients.discard(w)


async def ctl(typ="simulation_status_changed"):
    sim.push(typ, sim.status_())
    sim.push("score_updated", sim.dash())
    await bcast()


async def loop():
    while True:
        if sim.status == "running":
            sim.step()
            await bcast()
        await asyncio.sleep(1.0 / sim.speed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(loop())
    log.info("CityPulse engine started (scenario=%s speed=%sx, synthetic data)", sim.scenario, sim.speed)
    yield
    task.cancel()
    log.info("CityPulse engine stopped")


app = FastAPI(title="CityPulse", version="2.1.0",
              description="Live civic intelligence API — synthetic data for a fictional city. "
                          "Correlations are possible links, never causes.",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Lightweight request logging + never leak an unhandled 500 as a raw traceback."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # pragma: no cover - defensive
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500,
                            content={"detail": "internal error", "path": request.url.path})
    ms = (time.perf_counter() - started) * 1000
    if not request.url.path.startswith("/api/health"):
        log.info("%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Domain validation failures (invalid lifecycle transitions) become 409/400, not 500."""
    log.warning("validation error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=409, content={"detail": str(exc), "path": request.url.path})


class Seed(BaseModel):
    seed: Optional[int] = Field(default=None, ge=0, le=2 ** 31 - 1)


class Scen(BaseModel):
    scenario: str = Field(min_length=1, max_length=40)


class Spd(BaseModel):
    speed: float = Field(ge=0.25, le=20)


class Src(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    status: str = Field(pattern="^(live|offline)$")


class Demo(BaseModel):
    speed: float = 5


@app.get("/api/health")
def api_health():
    """Liveness + data-mode probe used by the frontend connection indicator."""
    return {"status": "ok", "service": "CityPulse", "version": app.version, "simulated": True,
            "data_mode": "simulation", "clients": len(clients), "tick": sim.t,
            "simulation_status": sim.status, "scenario": sim.scenario, "speed": sim.speed,
            "server_time": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/config")
def api_config():
    """Explainability metadata: thresholds, weights, floors, scenarios and disclaimers."""
    return sim.meta()


@app.get("/api/dashboard")
def api_dash():
    return sim.dash()


@app.get("/api/events")
def api_events(zone: Optional[str] = None, source: Optional[str] = None, severity: Optional[str] = None,
               event_type: Optional[str] = None, q: Optional[str] = None,
               minutes: Optional[int] = Query(default=None, ge=1, le=6000),
               limit: int = Query(default=200, ge=1, le=1000)):
    """Signal-level readings (one row per anomalous measurement) with search + filters."""
    needle = (q or "").strip().lower()
    tmin = (sim.t - minutes) if minutes else None
    ev = [e for e in sim.events
          if (not zone or e["zone"] == zone) and (not source or e["source"] == source)
          and (not severity or e["severity"] == severity) and (not event_type or e["event_type"] == event_type)
          and (tmin is None or e["timestamp"] >= sim.ts(tmin))
          and (not needle or needle in f"{e['id']} {e['event_type']} {e['zone']} {e['severity']} {e['source']}".lower())]
    return ev[-limit:][::-1]


@app.get("/api/events/{eid}")
def api_event(eid: str):
    e = sim.event_get(eid)
    if not e:
        raise HTTPException(404, f"unknown event {eid}")
    a = sim.anoms.get((e.get("metadata") or {}).get("anomaly_id"))
    return {**e, "anomaly": a}


@app.get("/api/anomalies")
def api_anoms(status: Optional[str] = "active", zone: Optional[str] = None, metric: Optional[str] = None,
              severity: Optional[str] = None, source: Optional[str] = None,
              limit: int = Query(default=200, ge=1, le=1000)):
    rows = [a for a in sim.anoms.values()
            if (not status or a["status"] == status) and (not zone or a["zone"] == zone)
            and (not metric or a["metric"] == metric) and (not severity or a["severity"] == severity)
            and (not source or a["source"] == source)]
    rows.sort(key=lambda a: (-a["strength"], a["metric"]))
    return rows[:limit]


@app.get("/api/correlations")
def api_corr(status: Optional[str] = None):
    return [c for c in sim.corrs.values() if c and (not status or c.get("status") == status)]


@app.get("/api/disruptions")
def api_disr(status: Optional[str] = None, zone: Optional[str] = None, severity: Optional[str] = None,
             state: Optional[str] = None, metric: Optional[str] = None, q: Optional[str] = None,
             limit: int = Query(default=200, ge=1, le=1000)):
    """Civic events (disruption lifecycle) with server-side search + filters."""
    return sim.disruption_view(status=status, zone=zone, severity=severity, state=state,
                               metric=metric, q=q, limit=limit)


@app.get("/api/disruptions/{did}")
async def api_disr_one(did: str):
    d = sim.disruption_get(did)
    if not d:
        raise HTTPException(404, f"unknown civic event {did}")
    c = sim.corrs.get(sim._zk(d["zone"]))
    return {**d, "correlation": c if c and c.get("status") == "active" else None,
            "evidence": d.get("evidence") or (c.get("evidence") if c else [])}


@app.post("/api/disruptions/{did}/{action}")
async def api_disr_act(did: str, action: str):
    """Validated lifecycle transitions for a civic event: acknowledge | resolve."""
    if action not in ("acknowledge", "resolve"):
        raise HTTPException(400, "action must be acknowledge or resolve")
    d = sim.disruption_act(did, action)
    if not d:
        raise HTTPException(404, f"unknown civic event {did}")
    await ctl()
    return d


@app.get("/api/alerts")
def api_alerts(status: Optional[str] = None, level: Optional[str] = None, zone: Optional[str] = None,
               q: Optional[str] = None, limit: int = Query(default=200, ge=1, le=1000)):
    return sim.alert_view(status=status, level=level, zone=zone, q=q, limit=limit)


@app.post("/api/alerts/{aid}/{action}")
async def api_alert_act(aid: str, action: str):
    if action not in ("acknowledge", "resolve"):
        raise HTTPException(400, "action must be acknowledge or resolve")
    a = sim.alert_act(aid, action)
    if not a:
        raise HTTPException(404, f"unknown alert {aid}")
    await ctl()
    return a


@app.get("/api/sources")
def api_sources():
    return sim.sources()


@app.get("/api/zones")
def api_zones():
    return sim.zones()


@app.get("/api/metrics")
def api_metrics():
    return {z: {m: round(sim.cur.get((z, m), 0), 2) for m in M} for z in ZONES}


@app.get("/api/trends")
def api_trends(minutes: int = Query(default=60, ge=1, le=180)):
    return list(sim.hist)[-minutes:]


@app.get("/api/progression")
def api_progression():
    """Scenario progression: intensity curves + current phase for the active scenario."""
    return sim.progression()


@app.get("/api/replay")
def api_replay(limit: int = Query(default=600, ge=1, le=2000)):
    """Recorded run frames (one per simulated minute) so the UI can scrub the run."""
    frames = list(sim.replay)[-limit:]
    return dict(count=len(sim.replay), frames=frames,
                first_tick=sim.replay[0]["tick"] if sim.replay else None,
                last_tick=sim.replay[-1]["tick"] if sim.replay else None,
                generated_at=sim.ts(), simulated=True)


@app.get("/api/replay/{tick}")
def api_replay_frame(tick: int):
    """A single recorded frame by tick."""
    frame = next((f for f in reversed(sim.replay) if f["tick"] == tick), None)
    if not frame:
        raise HTTPException(404, f"no recorded frame for tick {tick}")
    return frame


@app.get("/api/summary")
def api_summary():
    return {"summary": sim.summary(), "what_changed": sim.what_changed(), "predictions": sim.predict()}


@app.get("/api/attention")
def api_attention():
    """What Needs Attention? — prioritised, actionable view built from live evidence."""
    return sim.attention()


@app.get("/api/timeline")
def api_timeline(limit: int = Query(default=80, ge=1, le=300)):
    """Event timeline built from actual detection records."""
    return sim.timeline()[-limit:]


@app.get("/api/risk")
def api_risk():
    """Risk engine: city-wide plus per-zone scores/bands (separate from health)."""
    return {"city": sim.risk_global(), "zones": {z: sim.risk(z) for z in ZONES}}


@app.get("/api/analyst")
def api_analyst(event_id: Optional[str] = Query(default=None)):
    """AI Civic Analyst: plain-language explanation of a detected event (never invents data)."""
    try:
        return sim.analyst(event_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/simulation/status")
def api_status():
    return sim.status_()


@app.post("/api/simulation/start")
async def sim_start():
    sim.status = "running"
    await ctl()
    return sim.status_()


@app.post("/api/simulation/pause")
async def sim_pause():
    sim.status = "paused"
    await ctl()
    return sim.status_()


@app.post("/api/simulation/resume")
async def sim_resume():
    """Explicit alias for start (kept so the UI can offer both Resume and Restart)."""
    sim.status = "running"
    await ctl()
    return sim.status_()


@app.post("/api/simulation/step")
async def sim_step():
    sim.step()
    await bcast()
    return sim.status_()


@app.post("/api/simulation/reset")
async def sim_reset(b: Seed = Seed()):
    sim.reset(b.seed)
    await ctl()
    return sim.status_()


@app.post("/api/simulation/restart")
async def sim_restart(b: Seed = Seed()):
    sim.reset(b.seed, sim.scenario, True)
    await ctl()
    return sim.status_()


@app.post("/api/simulation/scenario")
async def sim_scen(b: Scen):
    if b.scenario not in SCEN:
        raise HTTPException(400, f"unknown scenario; choose from {list(SCEN)}")
    sim.reset(None, b.scenario, sim.status == "running")
    await ctl()
    return sim.status_()


@app.post("/api/simulation/speed")
async def sim_speed(b: Spd):
    if b.speed not in (0.5, 1, 2, 5, 10):
        raise HTTPException(400, "speed must be 0.5, 1, 2, 5 or 10")
    sim.speed = b.speed
    await ctl()
    return sim.status_()


@app.post("/api/simulation/demo")
async def sim_demo(b: Demo = Demo()):
    sim.speed = b.speed if b.speed in (0.5, 1, 2, 5, 10) else 5
    sim.reset(None, "full_disruption", True)
    await ctl()
    return sim.status_()


@app.post("/api/simulation/source")
async def sim_source(b: Src):
    if b.source not in SOURCES:
        raise HTTPException(400, "unknown source")
    (sim.offline.add if b.status == "offline" else sim.offline.discard)(b.source)
    if b.status == "offline":
        for a in sim.anoms.values():
            if a["source"] == b.source and a["status"] == "active":
                a["status"] = "resolved"
                sim.act.pop((a["zone"], a["metric"]), None)
    await ctl("source_status_changed")
    return sim.sources()


@app.websocket("/ws/citypulse")
async def ws(w: WebSocket):
    """
    Live push channel: metric_updated / anomaly_detected / event_created /
    correlation_detected / disruption_created|updated / alert_created|updated /
    score_updated / simulation_status_changed. Clients may send "ping" and get a
    "pong" heartbeat; the server also emits its own heartbeat so idle proxies do
    not silently drop the socket.
    """
    await w.accept()
    clients.add(w)
    log.info("websocket connected (%d client(s))", len(clients))

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await w.send_json({"type": "heartbeat", "data": {"tick": sim.t, "city_time": sim.ts(),
                                                             "clients": len(clients)}})

    hb = asyncio.create_task(heartbeat())
    try:
        await w.send_json({"type": "hello", "data": {"version": app.version, "simulated": True,
                                                     "config": sim.meta(), "snapshot": sim.dash()}})
        while True:
            msg = await w.receive_text()
            if msg == "ping":
                await w.send_json({"type": "pong", "data": {"tick": sim.t}})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # pragma: no cover - defensive
        log.warning("websocket error: %s", e)
    finally:
        hb.cancel()
        clients.discard(w)
        log.info("websocket disconnected (%d client(s))", len(clients))


# ---------------------------------------------------------------------------
# Single-origin hosting: serve the built React app (frontend/dist) from the
# same FastAPI process so ONE public URL runs the whole project in Chrome.
# Local dev is unaffected (Vite :5173 + VITE_API_URL still work).
# ---------------------------------------------------------------------------
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST_DIR.joinpath("index.html").exists():
    ASSETS_DIR = DIST_DIR / "assets"
    if ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_spa_root():
        return FileResponse(str(DIST_DIR / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith(("api/", "ws/", "docs", "openapi.json", "redoc")):
            raise HTTPException(404, "not found")
        candidate = DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(DIST_DIR / "index.html"))

"""CityPulse backend: simulator -> events -> anomalies -> correlations -> civic events -> health -> API/WS.
All data is SIMULATED (fictional city: Zone A / Zone B / Zone C). Correlations are never
presented as causation; confidence is labelled "CityPulse Event Confidence (prototype)".

Architecture adapted from the reference FastAPI+WS design; the analytics brain keeps the
CityPulse rules: mean+2*std with practical floors, event confidence from signal strength +
diversity + temporal proximity + persistence, weighted civic health score, and causal-safe
language everywhere.
"""
import asyncio
import math
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
        self.health_hist = deque(maxlen=300)
        self.offline: set = set()
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

    def detect(self, z: str, m: str, v: float, quiet: bool):
        """
        Anomaly rule: value > baseline_mean + 2 * baseline_std AND value >= a
        practical floor. The baseline learns ONLY from non-anomalous data
        (EWMA), so a storm is never absorbed into 'normal' while it is active.
        Insufficient history / zero std / missing values are all handled.
        """
        c = M[m]
        k = (z, m)
        d = self.det.setdefault(k, dict(mean=v, var=(c["floor"] * 0.35) ** 2, streak=0))
        std = max(math.sqrt(d["var"]), c["floor"] * 0.35)
        zs = (v - d["mean"]) / std
        bz = zs * c["sign"]
        base = d["mean"]

        if bz < 2:  # learn only from ordinary readings
            diff = v - d["mean"]
            d["mean"] += 0.05 * diff
            d["var"] = 0.95 * (d["var"] + 0.05 * diff * diff)
        d["streak"] = d["streak"] + 1 if bz >= 2 else 0

        a = self.anoms.get(self.act.get(k))
        floor = c["floor"]
        if bz >= 2 and v >= floor:  # statistically unusual AND practically significant
            b = base if abs(base) > 1e-6 else 1.0
            upd = dict(baseline=round(base, 2), current=round(v, 2), deviation=round(v - base, 2),
                       pct_change=round((v - base) / b * 100, 1), z_score=round(zs, 2),
                       strength=round(min(1.0, abs(zs) / 6.0), 2), severity=sevz(zs),
                       consecutive_steps=d["streak"], updated=self.ts())
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
                    self.push("anomaly_detected", a)
            if not quiet:
                self.emit(m, z, v, upd["severity"], {"simulated": True, "anomaly_id": a["id"], "z_score": upd["z_score"]})
        elif a and bz < 1.5:
            a["status"] = "resolved"
            a["resolved_at"] = self.ts()
            self.act.pop(k, None)
        if not quiet and not self._warm:
            # persist series AFTER detection so correlation windows never see the future
            pass

    # ------------------------------------------------- lagged temporal links
    def correlate(self):
        """
        Lagged temporal relationships A(t) -> B(t+lag) for lag in {0,15,30} min,
        per zone, using only observations up to the current tick. Output wording
        is direction-aware; correlation is never causation.
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
                for lag in (0, 15, 30):  # minutes (1 tick = 1 simulated minute)
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
            conf = CONF["base"]
            conf += CONF["per_extra_signal"] * max(0, n_sig - 2)
            conf += min(CONF["strength_bonus"], (zs_mean / CONF["strength_span"]) * CONF["strength_bonus"])
            streaks = [a["consecutive_steps"] for a in live if a["zone"] == z]
            conf += min(CONF["persistence_cap"], (max(streaks) - 1) * CONF["per_persistent_step"]) if streaks else 0
            conf += CONF["tight_bonus"] if co_active_min >= 30 else CONF["spread_bonus"]
            conf = float(min(CONF["cap"], max(0.0, conf)))

            c = dict(id=f"corr-{z}", zone=zone_label(z), sources=srcs, lagged=pairs_out[:6],
                     metrics=sorted({a["metric"] for a in live if a["zone"] == z}),
                     signal_count=n_sig, co_active_min=co_active_min, mean_z=round(zs_mean, 2),
                     confidence=round(conf), confidence_kind="CityPulse Event Confidence (prototype)",
                     label="Possible multi-signal civic event", status="active", updated=self.ts(),
                     note="Signals increased in sequence within the event window — a temporal association, not a confirmed cause.")
            if old and old.get("status") == "active":
                c["timestamp"] = old.get("timestamp", self.ts())
            else:
                c["timestamp"] = self.ts()
                self.push("correlation_detected", c)
            self.corrs[z] = c

    # ------------------------------------------------- disruption lifecycle
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
                d = dict(id=f"disr-{self.seq:04d}", zone=zone_label(z), state="DETECTED",
                         lifecycle={"DETECTED": self.ts()}, started=self.ts(), first_t=self.t,
                         score=round(r, 2), peak=r, severity="moderate", sources=c["sources"],
                         correlation_id=c["id"], confidence=c["confidence"], confidence_kind=c["confidence_kind"],
                         sequence=" → ".join(m.title() for m in c.get("metrics", [])),
                         note="Signals increased in sequence within the event window. Possible temporal association — not a confirmed cause.",
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
                d["duration_min"] = self.t - d["first_t"]
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

    # ------------------------------------------------- city health
    def comps(self, z: Optional[str] = None):
        """
        Health components per zone, each 0-100 where HIGHER = HEALTHIER
        (displayed as health bars in the UI). Severity scales are shifted so
        an ordinary working city is genuinely healthy: congestion 25% -> ~0
        severity, base complaint volume -> 0 severity, drizzle -> ~0 severity.
        """
        def one(zz):
            g = lambda m: self.cur.get((zz, m), M[m]["base"])
            traffic_sev = clip((g("traffic") - 25.0) * (100.0 / 75.0))
            weather_sev = clip((g("rainfall") / 40.0) * 100)
            complaints_sev = clip((g("complaints") - 4.0) * (100.0 / 16.0))
            return {
                "Traffic": round(100 - traffic_sev, 1),
                "Weather": round(100 - weather_sev, 1),
                "Complaints": round(100 - complaints_sev, 1),
            }
        if z:
            return one(z)
        per = [one(x) for x in ZONES]
        return {k: round(0.5 * float(np.mean([p[k] for p in per])) + 0.5 * min(p[k] for p in per), 1) for k in W}

    def health(self):
        c = self.comps()
        base = sum(c[k] * W[k] for k in W) / sum(W.values())
        na = sum(1 for a in self.anoms.values() if a["status"] == "active")
        nd = sum(1 for d in self.disr.values() if d["state"] != "RESOLVED")
        score = max(0.0, base - min(15, 1.5 * na) - min(10, 5 * nd))
        prev = self.health_hist[-10] if len(self.health_hist) >= 10 else (self.health_hist[0] if self.health_hist else score)
        st = "HEALTHY" if score >= 85 else "STABLE" if score >= 70 else "DEGRADED" if score >= 50 else "CRITICAL"
        return dict(score=round(score, 1), status=st,
                    trend_pct=round((score - prev) / prev * 100, 1) if prev else 0.0,
                    components={k: round(v) for k, v in c.items()})

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
                              range_low=round(max(0.0, projected - band), 1), range_high=round(projected + band, 1),
                              trend_strength=strength,
                              text=(f"{LBL[m]} may continue to rise in {zone_label(z)} over the next 30 minutes." if slope > 0.05 else
                                    f"{LBL[m]} may ease in {zone_label(z)} over the next 30 minutes." if slope < -0.05 else
                                    f"{LBL[m]} looks roughly stable in {zone_label(z)}.")))
        return dict(items=items, note="Prototype trend-based prediction — not a certainty.")

    # ------------------------------------------------- views
    def zones(self):
        out = []
        for z, (la, lo) in ZONES.items():
            c = self.comps(z)
            na = sum(1 for a in self.anoms.values() if a["status"] == "active" and a["zone"] == z)
            h = max(0.0, sum(c[k] * W[k] for k in W) / sum(W.values()) - 1.5 * na)
            ev = self.corrs.get(z)
            out.append(dict(zone=zone_label(z), latitude=la, longitude=lo, health=round(h, 1), risk=round(100 - h, 1),
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

    def status_(self):
        return dict(simulation_time=self.ts(), tick=self.t, speed=self.speed, scenario=self.scenario,
                    scenario_time=self.t - self.t0, seed=self.seed, status=self.status,
                    offline_sources=sorted(self.offline), simulated=True)

    def dash(self):
        act = [a for a in self.anoms.values() if a["status"] == "active"]
        cs = [c for c in self.corrs.values() if c.get("status") == "active"]
        ds = [d for d in self.disr.values() if d["state"] != "RESOLVED"]
        al = [a for a in self.alerts.values() if a["status"] == "active"]
        src = self.sources()
        return dict(sim=self.status_(), health=self.health(),
                    kpis=dict(disruptions=len(ds), anomalies=len(act), correlations=len(cs), alerts=len(al),
                              sources_live=sum(1 for x in src if x["status"] == "LIVE"), sources_total=len(src)),
                    zones=self.zones(), anomalies=act[-120:], correlations=cs, disruptions=ds, alerts=al[-40:],
                    sources=src, events=list(self.events)[-40:][::-1], summary=self.summary(),
                    what_changed=self.what_changed(), predictions=self.predict(),
                    trend=list(self.hist)[-180:], simulated=True)

    def step(self):
        self.observe()
        self.correlate()
        self.disrupt()
        self.score()
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
    yield
    task.cancel()


app = FastAPI(title="CityPulse", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Seed(BaseModel):
    seed: Optional[int] = None


class Scen(BaseModel):
    scenario: str


class Spd(BaseModel):
    speed: float


class Src(BaseModel):
    source: str
    status: str


class Demo(BaseModel):
    speed: float = 5


@app.get("/api/health")
def api_health():
    return {"status": "ok", "simulated": True, "clients": len(clients)}


@app.get("/api/dashboard")
def api_dash():
    return sim.dash()


@app.get("/api/events")
def api_events(zone: Optional[str] = None, source: Optional[str] = None, severity: Optional[str] = None, limit: int = 200):
    ev = [e for e in sim.events if (not zone or e["zone"] == zone) and (not source or e["source"] == source)
          and (not severity or e["severity"] == severity)]
    return ev[-limit:][::-1]


@app.get("/api/anomalies")
def api_anoms(status: Optional[str] = None, zone: Optional[str] = None):
    return [a for a in sim.anoms.values() if (not status or a["status"] == status) and (not zone or a["zone"] == zone)]


@app.get("/api/correlations")
def api_corr():
    return [c for c in sim.corrs.values() if c]


@app.get("/api/disruptions")
def api_disr():
    return list(sim.disr.values())


@app.get("/api/alerts")
def api_alerts():
    return list(sim.alerts.values())


@app.post("/api/alerts/{aid}/{action}")
async def api_alert_act(aid: str, action: str):
    a = sim.alerts.get(aid)
    if not a or action not in ("acknowledge", "resolve"):
        raise HTTPException(404)
    a["status"] = "acknowledged" if action == "acknowledge" else "resolved"
    await ctl("score_updated")
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
def api_trends(minutes: int = 60):
    return list(sim.hist)[-minutes:]


@app.get("/api/summary")
def api_summary():
    return {"summary": sim.summary(), "what_changed": sim.what_changed(), "predictions": sim.predict()}


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
    await w.accept()
    clients.add(w)
    try:
        await w.send_json({"type": "score_updated", "data": sim.dash()})
        while True:
            await w.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(w)

"""
CityPulse backend verification suite.

Runs with plain Python (no pytest required):
    cd backend
    python tests/test_citypulse.py

Every check is also a `test_*` function, so `pytest tests/test_citypulse.py`
works too if pytest is installed later (it is not a project dependency).
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as cp                                   # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402

RESULTS = []


def check(cond, label, extra=""):
    RESULTS.append((bool(cond), label, extra))
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"  [{extra}]" if extra else ""))
    return bool(cond)


def expect_raises(fn, exc, label):
    try:
        fn()
    except exc as e:
        return check(True, label, type(e).__name__)
    except Exception as e:
        return check(False, label, f"raised {type(e).__name__}: {e}")
    return check(False, label, "no exception raised")


# ---------------------------------------------------------------- engine checks
def test_engine_anomaly_detection_is_deterministic_and_explainable():
    a, b = cp.Sim(seed=7), cp.Sim(seed=7)
    for _ in range(30):
        a.step()
        b.step()
    check(a.health()["score"] == b.health()["score"], "same seed -> identical health score",
          str(a.health()["score"]))
    peak = 0
    for _ in range(140):
        a.step()
        peak = max(peak, sum(1 for x in a.anoms.values() if x["status"] == "active"))
    check(peak >= 1, "anomalies detected during full_disruption", str(peak))
    a1 = next((x for x in a.anoms.values() if x["metric"] == "rainfall"), None)
    check(a1 is not None and a1.get("baseline") is not None, "anomaly carries a baseline")
    check(a1 is not None and abs(float(a1["z_score"])) >= cp.ANOMALY_Z_THRESHOLD,
          "anomaly z-score respects the configured threshold", str(a1 and a1["z_score"]))
    check(a1 is not None and bool(a1.get("explanation")), "anomaly exposes a human explanation")
    check(a1 is not None and a1["current"] >= cp.M["rainfall"]["floor"],
          "anomaly respects the practical significance floor")


def test_missing_readings_never_create_anomalies():
    s = cp.Sim(seed=3)
    for _ in range(20):
        s.step()
    before = sum(1 for x in s.anoms.values() if x["status"] == "active")
    for _ in range(5):
        s.detect("Zone A", "rainfall", float("nan"), quiet=True)
        s.detect("Zone A", "traffic", None, quiet=True)
    after = sum(1 for x in s.anoms.values() if x["status"] == "active")
    check(after == before, "NaN / None readings do not raise anomalies", f"{before} -> {after}")


def test_flat_signal_stays_normal():
    s = cp.Sim(seed=11)
    for _ in range(120):
        s.detect("Zone C", "complaints", 4.0, quiet=True)
    live = [x for x in s.anoms.values() if x["status"] == "active" and x["metric"] == "complaints"]
    check(len(live) == 0, "a flat, on-baseline series raises no complaints anomaly", str(len(live)))


# MARKER-ENGINE
def test_full_pipeline_event_lifecycle_engine():
    s = cp.Sim(seed=42)
    s.reset(None, "full_disruption", True)
    kinds = {}
    for _ in range(420):
        s.step()
        for m in s.drain():
            kinds[m["type"]] = kinds.get(m["type"], 0) + 1
    check(kinds.get("anomaly_detected", 0) > 0, "anomaly_detected broadcast", str(kinds.get("anomaly_detected")))
    check(kinds.get("correlation_detected", 0) > 0, "correlation_detected broadcast")
    check(kinds.get("disruption_created", 0) >= 1, "disruption_created broadcast")
    check(kinds.get("alert_created", 0) >= 3, "alerts raised across the demo story", str(kinds.get("alert_created")))
    d = max(s.disr.values(), key=lambda x: x["score"])
    check(d["severity"] in ("moderate", "high", "critical"), "event severity computed", d["severity"])
    check(0 < d["confidence"] <= 100, "CityPulse Event Confidence bounded 0-100", str(d["confidence"]))
    check(d["state"] in ("DETECTED", "MONITORING", "ESCALATING", "PEAK", "RECOVERING", "RESOLVED"),
          "event state is a known lifecycle state", d["state"])
    check(len(d.get("evidence", [])) >= 1, "event carries supporting evidence")
    healths = [r["health"] for r in s.hist]
    check(min(healths) < 60 <= max(healths), "health score degrades then recovers", f"{min(healths)}..{max(healths)}")
    check(0 <= s.health()["score"] <= 100, "health score stays inside 0-100")


def test_engine_lifecycle_transition_validation():
    s = cp.Sim(seed=42)
    s.reset(None, "full_disruption", True)
    for _ in range(120):
        s.step()
    d = max((x for x in s.disr.values() if x["state"] != "RESOLVED"), key=lambda x: x["score"])
    check(d["status"] == "active", "event starts as active")
    s.disruption_act(d["id"], "acknowledge")
    check(d["status"] == "acknowledged" and bool(d.get("acknowledged_at")), "acknowledge sets status + timestamp")
    expect_raises(lambda: s.disruption_act(d["id"], "acknowledge"), ValueError, "double acknowledge rejected")
    s.disruption_act(d["id"], "resolve")
    check(d["state"] == "RESOLVED" and d["status"] == "resolved", "resolve closes the event")
    expect_raises(lambda: s.disruption_act(d["id"], "acknowledge"), ValueError,
                  "acknowledging a resolved event rejected")
    expect_raises(lambda: s.disruption_act(d["id"], "resolve"), ValueError, "double resolve rejected")


def test_alert_and_offline_feed_handling():
    s = cp.Sim(seed=42)
    s.reset(None, "urban_flooding", True)
    for _ in range(160):
        s.step()
    aid = next(iter(s.alerts))
    s.alert_act(aid, "acknowledge")
    check(s.alerts[aid]["status"] == "acknowledged", "alert acknowledged")
    expect_raises(lambda: s.alert_act(aid, "acknowledge"), ValueError, "double alert acknowledge rejected")
    s.alert_act(aid, "resolve")
    check(s.alerts[aid]["status"] == "resolved", "alert resolved")
    expect_raises(lambda: s.alert_act(aid, "resolve"), ValueError, "double alert resolve rejected")
    s.offline.add("weather")
    h = s.health()
    check("Weather" not in h["components"] and h["partial"], "offline feed removed from health components")
    check(abs(sum(h["weights_used"].values()) - 1.0) < 1e-9, "weights re-normalised when a feed is offline")
    check("weather" in s.coverage()["offline_sources"] and s.coverage()["coverage_pct"] < 100,
          "coverage reflects the outage")
    s.offline.clear()


# MARKER-API
# ---------------------------------------------------------------- API checks
def test_api_surface_and_schemas():
    with TestClient(cp.app) as c:
        c.post("/api/simulation/pause")
        r = c.get("/api/health")
        check(r.status_code == 200 and r.json()["simulated"] is True, "GET /api/health ok")
        cfg = c.get("/api/config").json()
        check(cfg["data_mode"] == "simulation" and cfg["simulated"] is True, "GET /api/config declares simulation")
        check(len(cfg["metrics"]) == len(cp.M) and cfg["anomaly"]["z_threshold"] > 0,
              "config exposes metrics + thresholds")
        check(set(cfg["health"]["weights"]) == set(cp.W), "config exposes health weights")
        d = c.get("/api/dashboard").json()
        for key in ("health", "kpis", "zones", "anomalies", "correlations", "disruptions", "alerts",
                    "sources", "events", "summary", "trend", "coverage", "sim", "what_changed", "predictions"):
            check(key in d, f"dashboard has '{key}'")
        check(0 <= d["health"]["score"] <= 100, "dashboard health bounded")
        check(d["coverage"]["coverage_pct"] > 0, "dashboard reports data coverage")
        z = d["zones"][0]
        check(all(k in z for k in ("zone", "latitude", "longitude", "health", "risk", "anomalies", "metrics")),
              "zone payload complete")
        check(all(-90 <= zz["latitude"] <= 90 and -180 <= zz["longitude"] <= 180 for zz in d["zones"]),
              "zone coordinates are valid")
        check(c.get("/api/anomalies").status_code == 200, "GET /api/anomalies ok")
        check(c.get("/api/anomalies?metric=rainfall&severity=critical").status_code == 200,
              "anomaly filters accepted")
        check(c.get("/api/events?limit=5").status_code == 200, "GET /api/events ok")
        check(isinstance(c.get("/api/correlations").json(), list), "GET /api/correlations ok")
        check(isinstance(c.get("/api/disruptions").json(), list), "GET /api/disruptions ok")
        check(isinstance(c.get("/api/alerts").json(), list), "GET /api/alerts ok")
        check(isinstance(c.get("/api/sources").json(), list), "GET /api/sources ok")
        check(isinstance(c.get("/api/metrics").json(), dict), "GET /api/metrics ok")
        check(isinstance(c.get("/api/trends?minutes=30").json(), list), "GET /api/trends ok")
        check("summary" in c.get("/api/summary").json(), "GET /api/summary ok")
        check(c.get("/api/simulation/status").json()["simulated"] is True, "GET /api/simulation/status ok")
        check(c.get("/api/events?limit=0").status_code == 422, "invalid limit rejected with 422")
        check(c.get("/api/trends?minutes=99999").status_code == 422, "out-of-range minutes rejected with 422")
        check(c.get("/api/disruptions/nope").status_code == 404, "unknown civic event -> 404")
        check(c.get("/api/events/nope").status_code == 404, "unknown event -> 404")
        check(c.get("/api/alerts?status=active").status_code == 200, "alert status filter ok")


# MARKER-FLOW
def test_api_end_to_end_simulation_flow():
    """Simulation -> ingestion -> analytics -> event -> API -> acknowledge -> resolve."""
    with TestClient(cp.app) as c:
        c.post("/api/simulation/pause")
        st = c.post("/api/simulation/scenario", json={"scenario": "full_disruption"}).json()
        check(st["scenario"] == "full_disruption" and st["status"] == "paused", "scenario set while paused", st["status"])
        check(c.post("/api/simulation/resume").json()["status"] == "running", "resume starts the engine")
        c.post("/api/simulation/pause")
        for _ in range(150):
            c.post("/api/simulation/step")
        d = c.get("/api/dashboard").json()
        check(d["kpis"]["anomalies"] > 0, "simulation produced anomalies", str(d["kpis"]["anomalies"]))
        check(d["kpis"]["correlations"] > 0, "simulation produced correlations", str(d["kpis"]["correlations"]))
        check(d["kpis"]["disruptions"] > 0, "simulation produced a civic event", str(d["kpis"]["disruptions"]))
        check(d["kpis"]["alerts"] > 0, "simulation produced alerts", str(d["kpis"]["alerts"]))
        check(d["health"]["score"] < 85, "city health degraded during disruption", str(d["health"]["score"]))
        check(bool(d["summary"]["headline"]) and bool(d["summary"]["lines"]), "narrative summary available")

        ev = c.get("/api/disruptions?status=active").json()[0]
        check(ev["id"].startswith("disr-"), "civic event id present", ev["id"])
        detail = c.get(f"/api/disruptions/{ev['id']}").json()
        check(len(detail.get("evidence", [])) > 0, "event detail exposes evidence")
        check(bool(detail["latitude"]) and bool(detail["longitude"]), "event detail has coordinates")

        ack = c.post(f"/api/disruptions/{ev['id']}/acknowledge")
        check(ack.status_code == 200 and ack.json()["status"] == "acknowledged", "POST acknowledge updates backend")
        check(c.post(f"/api/disruptions/{ev['id']}/acknowledge").status_code == 409, "double acknowledge -> 409")
        check(c.get("/api/disruptions?status=acknowledged").json()[0]["id"] == ev["id"],
              "filtered search finds acked event")

        res = c.post(f"/api/disruptions/{ev['id']}/resolve")
        check(res.status_code == 200 and res.json()["state"] == "RESOLVED", "POST resolve closes the event")
        check(c.post(f"/api/disruptions/{ev['id']}/resolve").status_code == 409, "double resolve -> 409")
        check(c.get("/api/disruptions?status=resolved").json()[0]["id"] == ev["id"],
              "resolved event still searchable")
        fresh = c.get("/api/dashboard").json()
        check(fresh["kpis"]["disruptions"] == 0, "dashboard count syncs after resolve", str(fresh["kpis"]["disruptions"]))
        check(any(a["id"].startswith("alert-") for a in c.get("/api/alerts").json()), "event actions raise audit alerts")
        check(c.post("/api/disruptions/disr-9999/resolve").status_code == 404, "unknown event action -> 404")
        check(c.post("/api/alerts/alert-9999/resolve").status_code == 404, "unknown alert action -> 404")

        al = c.get("/api/alerts?status=active").json()
        check(len(al) > 0, "active alerts available", str(len(al)))
        if al:
            a1 = al[0]["id"]
            check(c.post(f"/api/alerts/{a1}/acknowledge").json()["status"] == "acknowledged", "alert ack via API")
            check(c.post(f"/api/alerts/{a1}/acknowledge").status_code == 409, "double alert ack -> 409")
            check(c.post(f"/api/alerts/{a1}/resolve").json()["status"] == "resolved", "alert resolve via API")
            check(all(x["id"] != a1 for x in c.get("/api/alerts?status=active").json()),
                  "resolved alert leaves the active list")

        check(c.post("/api/simulation/scenario", json={"scenario": "bogus"}).status_code == 400, "unknown scenario -> 400")
        check(c.post("/api/simulation/speed", json={"speed": 2}).json()["speed"] == 2, "speed endpoint ok")
        check(c.post("/api/simulation/source", json={"source": "weather", "status": "offline"}).status_code == 200,
              "source outage accepted")
        src = c.get("/api/sources").json()
        check(any(s["source"] == "weather" and s["status"] == "OFFLINE" for s in src), "offline source reported")
        check(c.get("/api/dashboard").json()["coverage"]["coverage_pct"] < 100, "coverage drops with an outage")
        c.post("/api/simulation/source", json={"source": "weather", "status": "live"})
        check(c.post("/api/simulation/source", json={"source": "weather", "status": "nope"}).status_code == 422,
              "bad source status rejected")
        check(c.post("/api/simulation/restart", json={"seed": 42}).json()["tick"] == 0, "restart resets the tick")
        check(c.post("/api/simulation/reset", json={"seed": 5}).status_code == 200, "reset accepted")


# MARKER-WS
def test_websocket_channel():
    with TestClient(cp.app) as c:
        c.post("/api/simulation/pause")
        with c.websocket_connect("/ws/citypulse") as ws:
            hello = ws.receive_json()
            check(hello["type"] == "hello" and hello["data"]["simulated"] is True, "WS hello handshake")
            check("config" in hello["data"] and "snapshot" in hello["data"], "WS hello carries config + snapshot")
            ws.send_text("ping")
            check(ws.receive_json()["type"] == "pong", "WS ping/pong heartbeat")
            c.post("/api/simulation/step")
            got = []
            for _ in range(12):
                got.append(ws.receive_json()["type"])
                if "score_updated" in got:
                    break
            check("score_updated" in got, "WS pushes dashboard updates on tick", ",".join(sorted(set(got))))
    with TestClient(cp.app) as c:
        check(c.get("/api/health").json()["clients"] == 0, "client count cleaned up after WS close")


def main_():
    groups = [
        ("engine", [test_engine_anomaly_detection_is_deterministic_and_explainable,
                    test_missing_readings_never_create_anomalies,
                    test_flat_signal_stays_normal,
                    test_full_pipeline_event_lifecycle_engine,
                    test_engine_lifecycle_transition_validation,
                    test_alert_and_offline_feed_handling]),
        ("api", [test_api_surface_and_schemas, test_api_end_to_end_simulation_flow, test_websocket_channel]),
    ]
    for name, fns in groups:
        print(f"\n=== {name} ===")
        for fn in fns:
            print(f"\n- {fn.__name__}")
            try:
                fn()
            except Exception:
                RESULTS.append((False, f"{fn.__name__} crashed", ""))
                traceback.print_exc()
    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = [(lab, extra) for ok, lab, extra in RESULTS if not ok]
    print("\n" + "=" * 70)
    print(f"{passed}/{len(RESULTS)} checks passed")
    for lab, extra in failed:
        print(f"  FAILED: {lab} {extra}")
    print("=" * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main_())





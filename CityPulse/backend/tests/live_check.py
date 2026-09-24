"""
Live end-to-end verification against a *running* CityPulse backend.

Start the server first:
    cd backend
    uvicorn main:app --port 8000
Then:
    python tests/live_check.py

It exercises real HTTP + a real WebSocket connection (network level, not in-process),
drives the simulation, and walks a civic event through acknowledge → resolve.
"""
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("CITYPULSE_URL", "http://127.0.0.1:8000")
WS = BASE.replace("http", "ws") + "/ws/citypulse"
RESULTS = []


def req(path, method="GET", body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "null")


def check(cond, label, extra=""):
    RESULTS.append((bool(cond), label))
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"  [{extra}]" if extra else ""))
    return bool(cond)


async def ws_check():
    import websockets
    async with websockets.connect(WS, open_timeout=10) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        check(hello.get("type") == "hello" and hello["data"].get("simulated") is True,
              "live WS hello handshake")
        await ws.send("ping")
        pong = json.loads(await asyncio.wait_for(ws.recv(), 10))
        check(pong.get("type") == "pong", "live WS ping/pong")
        req("/api/simulation/step", "POST", {})
        seen = {"score_updated": False, "metric_updated": False}
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            except asyncio.TimeoutError:
                break
            if msg.get("type") in seen:
                seen[msg["type"]] = True
            if all(seen.values()):
                break
        check(all(seen.values()), "live WS push after a manual step", str(seen))


def main():
    try:
        status, health = req("/api/health")
    except urllib.error.URLError as e:
        print(f"FAILED to reach {BASE}: {e}\nStart the backend first (uvicorn main:app --port 8000).")
        return 2
    check(status == 200 and health["status"] == "ok", "live GET /api/health", f"v{health.get('version')}")
    check(health.get("data_mode") == "simulation", "live health declares simulation mode")

    _, cfg = req("/api/config")
    check(cfg.get("metrics") and cfg["anomaly"]["z_threshold"] > 0, "live GET /api/config")

    req("/api/simulation/pause", "POST", {})
    _, st = req("/api/simulation/scenario", "POST", {"scenario": "full_disruption"})
    check(st["scenario"] == "full_disruption", "scenario switch over HTTP")
    _, st = req("/api/simulation/speed", "POST", {"speed": 10})
    check(st["speed"] == 10, "speed switch over HTTP")
    req("/api/simulation/resume", "POST", {})

    print("  … letting the engine run at 10x for ~12 s")
    import time as _t
    _t.sleep(12)
    req("/api/simulation/pause", "POST", {})
    _, dash = req("/api/dashboard")
    k = dash["kpis"]
    check(k["anomalies"] > 0, "live anomalies produced", str(k["anomalies"]))
    check(k["correlations"] > 0, "live correlations produced", str(k["correlations"]))
    check(k["disruptions"] > 0, "live civic event produced", str(k["disruptions"]))
    check(k["alerts"] > 0, "live alerts produced", str(k["alerts"]))
    check(dash["coverage"]["coverage_pct"] == 100.0, "coverage complete", str(dash["coverage"]["coverage_pct"]))
    check(dash["generated_at"] and dash["sim"]["tick"] > 0, "payload carries timestamp + tick")

    _, events = req("/api/disruptions?status=active")
    check(isinstance(events, list) and len(events) > 0, "live event search returns records")
    ev = events[0]
    _, detail = req(f"/api/disruptions/{ev['id']}")
    check(len(detail.get("evidence", [])) > 0, "live event detail carries evidence")
    s1, acked = req(f"/api/disruptions/{ev['id']}/acknowledge", "POST", {})
    check(s1 == 200 and acked["status"] == "acknowledged", "live acknowledge writes backend state")
    try:
        req(f"/api/disruptions/{ev['id']}/acknowledge", "POST", {})
        check(False, "second acknowledge rejected")
    except urllib.error.HTTPError as e:
        check(e.code == 409, "second acknowledge rejected with 409", str(e.code))
    s2, resolved = req(f"/api/disruptions/{ev['id']}/resolve", "POST", {})
    check(s2 == 200 and resolved["state"] == "RESOLVED", "live resolve writes backend state")
    _, after = req("/api/dashboard")
    check(after["kpis"]["disruptions"] < k["disruptions"], "dashboard count updates after resolve",
          f"{k['disruptions']} -> {after['kpis']['disruptions']}")
    _, al = req("/api/alerts?status=active")
    check(isinstance(al, list) and len(al) > 0, "live alert queue available", str(len(al)))
    s3, a = req(f"/api/alerts/{al[0]['id']}/acknowledge", "POST", {})
    check(s3 == 200 and a["status"] == "acknowledged", "live alert acknowledge")

    asyncio.run(ws_check())

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [lab for ok, lab in RESULTS if not ok]
    print("\n" + "=" * 70)
    print(f"live checks: {passed}/{len(RESULTS)} passed")
    for lab in failed:
        print(f"  FAILED: {lab}")
    print("=" * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

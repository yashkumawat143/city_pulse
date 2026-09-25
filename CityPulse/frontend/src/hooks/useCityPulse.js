import { useCallback, useEffect, useRef, useState } from "react";
import api, { wsUrl } from "../lib/api";

const POLL_MS = 5000;        // REST fallback cadence while the socket is down
const PING_MS = 20000;       // client heartbeat
const MAX_BACKOFF = 15000;

/**
 * One live data pipeline for the whole app:
 *  - REST snapshot on mount, so the dashboard works even if WebSockets never connect
 *  - WebSocket for push updates (hello snapshot, score_updated, heartbeats)
 *  - automatic reconnection with exponential backoff
 *  - REST polling fallback + resume-on-tab-focus while the socket is unavailable
 * All listeners/timers are cleaned up on unmount (no leaks, no duplicate sockets).
 */
export function useCityPulse() {
  const [snapshot, setSnapshot] = useState(null);
  const [config, setConfig] = useState(null);
  const [conn, setConn] = useState("CONNECTING");
  const [lastUpdate, setLastUpdate] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const ws = useRef(null);
  const timers = useRef({ ping: null, poll: null, retry: null });
  const tries = useRef(0);
  const alive = useRef(true);
  const restOk = useRef(false);

  /**
   * Accept only structurally valid snapshots. A dev server returning index.html
   * for /api, a proxy hiccup, or a partial WS frame must never reach the UI as
   * state — a malformed snapshot used to crash the dashboard on `kpis.events_total`.
   */
  const applySnapshot = useCallback((data) => {
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    if (!data.kpis || typeof data.kpis !== "object") return;      // core shape check
    if (!Array.isArray(data.zones) || data.zones.length === 0) return;
    setSnapshot(data);
    setLastUpdate(new Date());
    setError(null);
    setLoading(false);
  }, []);

  const fetchSnapshot = useCallback(async () => {
    try {
      const d = await api.dashboard();
      if (!alive.current) return null;
      restOk.current = true;
      applySnapshot(d);
      return d;
    } catch (e) {
      if (!alive.current) return null;
      restOk.current = false;
      setError(e.message);
      setLoading(false);
      return null;
    }
  }, [applySnapshot]);

  const stopPolling = useCallback(() => {
    if (timers.current.poll) { clearInterval(timers.current.poll); timers.current.poll = null; }
  }, []);

  const startPolling = useCallback(() => {
    if (timers.current.poll || !alive.current) return;
    timers.current.poll = setInterval(() => {
      if (document.hidden) return;
      fetchSnapshot();
    }, POLL_MS);
  }, [fetchSnapshot]);

  useEffect(() => {
    alive.current = true;

    api.config().then((c) => { if (alive.current) setConfig(c); }).catch(() => {});
    fetchSnapshot();

    const open = () => {
      if (!alive.current) return;
      const socket = new WebSocket(wsUrl());
      ws.current = socket;

      socket.onopen = () => {
        tries.current = 0;
        restOk.current = true;
        setConn("LIVE");
        setError(null);
        stopPolling();
        if (timers.current.ping) clearInterval(timers.current.ping);
        timers.current.ping = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, PING_MS);
      };

      socket.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (!msg || typeof msg !== "object") return;
        if (msg.type === "hello") {
          if (msg.data?.config) setConfig((c) => c || msg.data.config);
          applySnapshot(msg.data?.snapshot);
        } else if (msg.type === "score_updated") {
          applySnapshot(msg.data);
        } else if (msg.type === "heartbeat" || msg.type === "pong") {
          setLastUpdate((t) => t || new Date());
          setConn((c) => (c === "LIVE" ? c : "LIVE"));
        }
        // granular events (anomaly_detected, alert_created, …) arrive between
        // score_updated frames; the dashboard snapshot stays the source of truth so
        // repeated messages can never duplicate rows in the UI.
      };

      socket.onerror = () => { try { socket.close(); } catch { /* noop */ } };

      socket.onclose = () => {
        if (!alive.current) return;
        if (timers.current.ping) { clearInterval(timers.current.ping); timers.current.ping = null; }
        tries.current += 1;
        setConn(restOk.current ? "POLLING" : tries.current > 2 ? "OFFLINE" : "RECONNECTING");
        startPolling();
        const delay = Math.min(1000 * 2 ** (tries.current - 1), MAX_BACKOFF);
        timers.current.retry = setTimeout(open, delay);
      };
    };

    open();

    const onVisible = () => { if (!document.hidden) fetchSnapshot(); };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      alive.current = false;
      document.removeEventListener("visibilitychange", onVisible);
      if (timers.current.ping) clearInterval(timers.current.ping);
      if (timers.current.retry) clearTimeout(timers.current.retry);
      if (timers.current.poll) clearInterval(timers.current.poll);
      timers.current = { ping: null, poll: null, retry: null };
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.onmessage = null;
        ws.current.onerror = null;
        try { ws.current.close(); } catch { /* noop */ }
        ws.current = null;
      }
    };
  }, [applySnapshot, fetchSnapshot, startPolling, stopPolling]);

  /** Force an immediate REST re-sync (used after every mutating action). */
  const refresh = useCallback(() => fetchSnapshot(), [fetchSnapshot]);

  return { snapshot, config, conn, lastUpdate, error, loading, refresh,
           live: conn === "LIVE", restFallback: conn === "POLLING" || conn === "OFFLINE" };
}

export default useCityPulse;

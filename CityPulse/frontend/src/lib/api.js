/**
 * Single source of truth for CityPulse backend configuration + REST access.
 * Set VITE_API_URL / VITE_WS_URL in frontend/.env to point at another host.
 */
const env = import.meta.env || {};

export const API_BASE = (env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export function wsUrl() {
  if (env.VITE_WS_URL) return env.VITE_WS_URL;
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws/citypulse`;
}

export const REQUEST_TIMEOUT = 10000;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, { method = "GET", body, timeout = REQUEST_TIMEOUT, signal } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  if (signal) signal.addEventListener("abort", () => ctrl.abort(), { once: true });
  try {
    const res = await fetch(API_BASE + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body ?? {}) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { data = { detail: text }; }
    }
    if (!res.ok) {
      const detail = data && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      throw new ApiError(detail || `Request failed (${res.status})`, res.status);
    }
    return data;
  } catch (e) {
    if (e.name === "AbortError") throw new ApiError("Request timed out — is the CityPulse backend running?", 0);
    if (e instanceof ApiError) throw e;
    throw new ApiError("Cannot reach the CityPulse backend at " + API_BASE, 0);
  } finally {
    clearTimeout(timer);
  }
}

const qs = (params = {}) => {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "all") sp.set(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => request("/api/health"),
  config: () => request("/api/config"),
  dashboard: (opts) => request("/api/dashboard", opts),
  summary: () => request("/api/summary"),
  metrics: () => request("/api/metrics"),
  trends: (minutes = 60) => request(`/api/trends?minutes=${minutes}`),
  zones: () => request("/api/zones"),
  sources: () => request("/api/sources"),
  anomalies: (params, opts) => request(`/api/anomalies${qs(params)}`, opts),
  events: (params, opts) => request(`/api/events${qs(params)}`, opts),
  event: (id) => request(`/api/events/${encodeURIComponent(id)}`),
  correlations: (params) => request(`/api/correlations${qs(params)}`),
  disruptions: (params, opts) => request(`/api/disruptions${qs(params)}`, opts),
  disruption: (id) => request(`/api/disruptions/${encodeURIComponent(id)}`),
  disruptionAct: (id, action) => request(`/api/disruptions/${encodeURIComponent(id)}/${action}`, { method: "POST", body: {} }),
  alerts: (params, opts) => request(`/api/alerts${qs(params)}`, opts),
  alertAct: (id, action) => request(`/api/alerts/${encodeURIComponent(id)}/${action}`, { method: "POST", body: {} }),
  simStatus: () => request("/api/simulation/status"),
  /** action: start | resume | pause | step | reset | restart | demo */
  sim: (action, body) => request(`/api/simulation/${action}`, { method: "POST", body: body ?? {} }),
  simScenario: (scenario) => request("/api/simulation/scenario", { method: "POST", body: { scenario } }),
  simSpeed: (speed) => request("/api/simulation/speed", { method: "POST", body: { speed } }),
  simSource: (source, status) => request("/api/simulation/source", { method: "POST", body: { source, status } }),
};

export default api;

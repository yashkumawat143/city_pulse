/** Formatting + presentation helpers shared by every CityPulse view. */

export const SEVERITIES = ["low", "moderate", "high", "critical"];
export const STATUSES = ["active", "acknowledged", "resolved"];
export const LEVELS = ["INFO", "WATCH", "WARNING", "CRITICAL"];

/** Severity is never colour-only: each entry carries a label, icon and colour. */
export const SEV_META = {
  low: { label: "Low", icon: "•", color: "#38bdf8" },
  moderate: { label: "Moderate", icon: "▲", color: "#f59e0b" },
  high: { label: "High", icon: "▲", color: "#fb7185" },
  critical: { label: "Critical", icon: "◆", color: "#ef4444" },
  normal: { label: "Normal", icon: "•", color: "#22c55e" },
};

export const LEVEL_META = {
  INFO: { label: "Info", color: "#38bdf8" },
  WATCH: { label: "Watch", color: "#f59e0b" },
  WARNING: { label: "Warning", color: "#fb7185" },
  CRITICAL: { label: "Critical", color: "#ef4444" },
};

export const sevMeta = (s) => SEV_META[s] || SEV_META.low;

export function healthBand(score) {
  if (score >= 85) return { label: "HEALTHY", color: "#22c55e" };
  if (score >= 70) return { label: "STABLE", color: "#eab308" };
  if (score >= 50) return { label: "DEGRADED", color: "#f97316" };
  return { label: "CRITICAL", color: "#ef4444" };
}

export const healthColor = (h) => healthBand(h).color;

/** ISO timestamp (simulated city clock) -> HH:MM:SS. Never throws on bad input. */
export function clock(ts) {
  if (!ts || typeof ts !== "string") return "—";
  const m = ts.match(/T(\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : ts.slice(0, 19);
}

export function stamp(ts) {
  if (!ts || typeof ts !== "string") return "—";
  return `${ts.slice(0, 10)} ${clock(ts)}`;
}

export function cityTime(ts) {
  if (!ts || typeof ts !== "string") return "—";
  return ts.slice(0, 16).replace("T", " ");
}

/** "12 minutes ago" style relative time from the simulated clock. */
export function relMinutes(min) {
  if (min === null || min === undefined || Number.isNaN(min)) return "—";
  if (min <= 0) return "now";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return h < 48 ? `${h} h` : `${Math.floor(h / 24)} d`;
}

export const num = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

export const int = (v) => (v === null || v === undefined ? "—" : String(Math.round(Number(v))));

export const pctText = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : `${v > 0 ? "+" : ""}${num(v, 0)}%`);

export const metricLabel = (m) => ({ rainfall: "Rainfall", traffic: "Traffic congestion", complaints: "Complaint volume", incidents: "Road incidents" }[m] || m);

export const metricUnit = (m) => ({ rainfall: "mm", traffic: "congestion %", complaints: "reports/15min", incidents: "per 15min" }[m] || "");

export const statusLabel = (s) =>
  ({ active: "Active", acknowledged: "Acknowledged", resolved: "Resolved", DETECTED: "Detected" }[s] || s || "—");

/** Map coords are validated before they reach Leaflet. */
export function validCoords(lat, lon) {
  return typeof lat === "number" && typeof lon === "number" &&
    Number.isFinite(lat) && Number.isFinite(lon) &&
    Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
}

export function eventAgeMinutes(event, nowTick, tickMinutes = 15) {
  if (!event || nowTick === undefined || event.first_t === undefined) return null;
  return Math.max(0, (nowTick - event.first_t) * tickMinutes);
}

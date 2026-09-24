import { useEffect, useRef } from "react";
import { LEVEL_META, SEV_META, healthBand, sevMeta } from "../lib/format";

export function Card({ title, subtitle, badge, actions, children, className = "", id }) {
  return (
    <section className={`card ${className}`} id={id}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          <div className="card-actions">
            {badge}
            {actions}
          </div>
        </header>
      )}
      {children}
    </section>
  );
}

/** Severity is always icon + text + colour (never colour alone). */
export function Tag({ children, tone = "neutral", title }) {
  return <span className={`tag tag-${tone}`} title={title}>{children}</span>;
}

export function SevBadge({ severity, compact = false }) {
  const m = sevMeta(severity);
  return (
    <span className="sev" style={{ "--sev": m.color }} title={`Severity: ${m.label}`}>
      <i aria-hidden="true">{m.icon}</i>
      <span>{compact ? m.label : `Sev: ${m.label}`}</span>
    </span>
  );
}

export function LevelBadge({ level }) {
  const m = LEVEL_META[level] || { label: level, color: "#94a3b8" };
  return (
    <span className="sev" style={{ "--sev": m.color }} title={`Alert level: ${m.label}`}>
      <i aria-hidden="true">◉</i>
      <span>{m.label}</span>
    </span>
  );
}

export function StatusPill({ status }) {
  const map = { active: "active", acknowledged: "info", resolved: "muted", LIVE: "active", OFFLINE: "muted",
                POLLING: "warn", RECONNECTING: "warn", CONNECTING: "warn" };
  const label = { active: "Active", acknowledged: "Acknowledged", resolved: "Resolved", LIVE: "Live",
                  OFFLINE: "Offline", POLLING: "REST fallback", RECONNECTING: "Reconnecting",
                  CONNECTING: "Connecting" }[status] || status;
  return <span className={`pill pill-${map[status] || "muted"}`}>{label}</span>;
}

export function HealthPill({ score, status }) {
  const band = healthBand(score ?? 0);
  return (
    <span className="sev" style={{ "--sev": band.color }} title={`City health band: ${band.label}`}>
      <i aria-hidden="true">⬤</i>
      <span>{status || band.label} · {score ?? "—"}/100</span>
    </span>
  );
}

export function Meter({ value, max = 100, color, label }) {
  const pct = Math.max(0, Math.min(100, ((value ?? 0) / max) * 100));
  return (
    <div className="meter" role="meter" aria-valuenow={value ?? 0} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
      <i style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export function Loading({ label = "Loading CityPulse data…", rows = 3 }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <p>{label}</p>
      <div className="skeleton" aria-hidden="true">{Array.from({ length: rows }, (_, i) => <i key={i} />)}</div>
    </div>
  );
}

export function Empty({ title = "Nothing to show", hint, children }) {
  return (
    <div className="state empty">
      <p className="state-title">{title}</p>
      {hint && <p className="muted">{hint}</p>}
      {children}
    </div>
  );
}

export function ErrorState({ message, onRetry, hint }) {
  return (
    <div className="state error" role="alert">
      <p className="state-title">CityPulse could not load this data</p>
      <p className="muted">{message || "Unknown error."}</p>
      {hint && <p className="muted small">{hint}</p>}
      {onRetry && <button type="button" className="btn" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Select({ label, value, onChange, options, allLabel = "All", ariaLabel }) {
  return (
    <Field label={label}>
      <select aria-label={ariaLabel || label} value={value ?? "all"} onChange={(e) => onChange(e.target.value)}>
        {allLabel && <option value="all">{allLabel}</option>}
        {options.map((o) => {
          const val = typeof o === "string" ? o : o.value;
          const text = typeof o === "string" ? o : o.label;
          return <option key={val} value={val}>{text}</option>;
        })}
      </select>
    </Field>
  );
}

export function SearchBox({ value, onChange, placeholder, label = "Search" }) {
  return (
    <Field label={label}>
      <span className="search">
        <input type="search" value={value} placeholder={placeholder}
               aria-label={label} onChange={(e) => onChange(e.target.value)} />
        {value && (
          <button type="button" className="link-btn" onClick={() => onChange("")} aria-label="Clear search">✕</button>
        )}
      </span>
    </Field>
  );
}

export function FilterBar({ children, onReset, active }) {
  return (
    <div className="filters" role="search">
      {children}
      {onReset && <button type="button" className="btn ghost" onClick={onReset} disabled={!active}>Reset filters</button>}
    </div>
  );
}


/** Accessible modal used for the event detail / explanation view. */
export function Drawer({ open, title, subtitle, onClose, children, footer }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.activeElement;
    ref.current?.focus();
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="drawer-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          <button type="button" className="btn ghost" onClick={onClose} aria-label="Close details">✕ Close</button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-foot">{footer}</footer>}
      </aside>
    </div>
  );
}

export function KeyValue({ items }) {
  return (
    <dl className="kv">
      {items.filter(Boolean).map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v ?? "—"}</dd></div>
      ))}
    </dl>
  );
}

export function SeverityLegend() {
  return (
    <span className="legend" aria-label="Severity legend">
      {["low", "moderate", "high", "critical"].map((s) => (
        <span key={s}><i aria-hidden="true" style={{ background: SEV_META[s].color }} />{SEV_META[s].label}</span>
      ))}
    </span>
  );
}


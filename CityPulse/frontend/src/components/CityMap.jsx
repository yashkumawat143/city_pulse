import { useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from "react-leaflet";
import { clock, healthColor, metricLabel, sevMeta, validCoords } from "../lib/format";

const CITY_CENTER = [17.7, 78.48];
const CITY_ZOOM = 13;

/**
 * Live city map. Coordinates come from the backend zone registry and anomaly /
 * event records (never randomised on render); invalid coordinates are skipped.
 */
export default function CityMap({ zones = [], anomalies = [], events = [], onSelectEvent, height = 460 }) {
  const [layers, setLayers] = useState({ zones: true, anomalies: true, events: true });

  const validZones = useMemo(
    () => zones.filter((z) => validCoords(z.latitude, z.longitude)),
    [zones],
  );
  const validAnoms = useMemo(
    () => anomalies.filter((a) => validCoords(a.latitude, a.longitude)),
    [anomalies],
  );
  const validEvents = useMemo(() => {
    const byZone = new Map(validZones.map((z) => [z.zone, z]));
    return events
      .map((e) => {
        const z = byZone.get(e.zone);
        const lat = validCoords(e.latitude, e.longitude) ? e.latitude : z?.latitude;
        const lon = validCoords(e.latitude, e.longitude) ? e.longitude : z?.longitude;
        return validCoords(lat, lon) ? { ...e, lat, lon } : null;
      })
      .filter(Boolean);
  }, [events, validZones]);

  const missing = zones.length + anomalies.length + events.length - validZones.length - validAnoms.length - validEvents.length;

  return (
    <div className="map-wrap">
      <div className="map-toggles" role="group" aria-label="Map layers">
        {[["zones", "Zones"], ["anomalies", "Anomalies"], ["events", "Civic events"]].map(([k, label]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} />
            <span>{label}</span>
          </label>
        ))}
        <span className="muted small">Synthetic coordinates · fictional city</span>
      </div>

      <MapContainer center={CITY_CENTER} zoom={CITY_ZOOM} scrollWheelZoom
                    style={{ height: `${height}px` }} aria-label="Live city map">
        <TileLayer attribution="&copy; OpenStreetMap contributors"
                   url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />

        {layers.zones && validZones.map((z) => (
          <Circle key={z.zone} center={[z.latitude, z.longitude]} radius={1400}
                  pathOptions={{ color: healthColor(z.health), fillColor: healthColor(z.health), fillOpacity: 0.18, weight: 2 }}>
            <Tooltip direction="top">{z.zone} · health {z.health}/100</Tooltip>
            <Popup>
              <strong>{z.zone} — zone intelligence</strong>
              <div>Health {z.health}/100 · risk {z.risk}</div>
              <div>Active anomalies: {z.anomalies}</div>
              {z.event_confidence != null && <div>Event confidence (prototype): {z.event_confidence}%</div>}
              <div className="pop-list">
                {Object.entries(z.metrics || {}).map(([k, v]) => <div key={k}>{metricLabel(k)}: {v}</div>)}
              </div>
            </Popup>
          </Circle>
        ))}

        {layers.events && validEvents.map((e) => (
          <Circle key={e.id} center={[e.lat, e.lon]} radius={1900}
                  pathOptions={{ color: sevMeta(e.severity).color, dashArray: "8 6", fillOpacity: 0.06, weight: 2 }}>
            <Tooltip direction="top">{e.zone} · {e.state} · confidence {e.confidence}%</Tooltip>
            <Popup>
              <strong>Possible civic event · {e.zone}</strong>
              <div>State {e.state} · status {e.status}</div>
              <div>{e.sequence}</div>
              <div>Event confidence (prototype): {Math.round(e.confidence)}%</div>
              <button type="button" className="link-btn" onClick={() => onSelectEvent?.(e)}>
                Open evidence & lifecycle →
              </button>
            </Popup>
          </Circle>
        ))}

        {layers.anomalies && validAnoms.map((a) => (
          <CircleMarker key={a.id} center={[a.latitude, a.longitude]}
                        radius={5 + Math.min(1, a.strength ?? 0) * 8}
                        pathOptions={{ color: sevMeta(a.severity).color, fillColor: sevMeta(a.severity).color, fillOpacity: 0.65, weight: 2 }}>
            <Tooltip direction="top">{metricLabel(a.metric)} · {a.severity}</Tooltip>
            <Popup>
              <strong>{metricLabel(a.metric)} ({a.source})</strong>
              <div>{a.current} {a.unit} vs baseline {a.baseline} {a.unit}</div>
              <div>z-score {a.z_score} · {a.severity} · {a.zone}</div>
              <div>First seen {clock(a.timestamp)}</div>
              {a.explanation && <div className="pop-list small">{a.explanation}</div>}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {missing > 0 && (
        <p className="muted small">
          {missing} record{missing === 1 ? "" : "s"} hidden: invalid or missing coordinates.
        </p>
      )}
    </div>
  );
}

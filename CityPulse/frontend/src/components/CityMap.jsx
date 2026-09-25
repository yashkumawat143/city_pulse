import { useEffect, useMemo, useRef, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, ScaleControl, TileLayer, Tooltip } from "react-leaflet";
import { clock, healthBand, healthColor, metricLabel, sevMeta, validCoords } from "../lib/format";

const CITY_CENTER = [17.7, 78.48];
const CITY_ZOOM = 13;

/**
 * Google-Maps-style basemaps — free tile providers, no API key required:
 * Streets (OSM), Satellite (Esri imagery + place labels), Terrain (OpenTopoMap)
 * and Night (CARTO dark). Switching base remounts the tile layer; Leaflet's
 * attribution control keeps every provider credited.
 */
const BASE_LAYERS = [
  {
    id: "streets",
    label: "Streets",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  {
    id: "satellite",
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    maxZoom: 19,
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  },
  {
    id: "terrain",
    label: "Terrain",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    subdomains: "abc",
    maxZoom: 18,
    maxNativeZoom: 17,
    attribution:
      'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
  },
  {
    // Esri Dark Gray Canvas: free, no API key (CARTO's dark tiles now require
    // one and render "API KEY REQUIRED" watermarks instead of map tiles).
    id: "night",
    label: "Night",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    maxZoom: 16,
    maxNativeZoom: 15,
    attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
  },
];

/**
 * Live city map with Google-Maps-style chrome: a basemap switcher (Streets /
 * Satellite / Terrain / Night), zone search that flies to the selection, zoom
 * + fit + locate + fullscreen controls, a cursor coordinate / zoom readout, a
 * legend and a selected-zone place card. Coordinates always come from the
 * backend zone registry and anomaly / event records (never randomised on
 * render); invalid coordinates are skipped.
 */
export default function CityMap({ zones = [], anomalies = [], events = [], onSelectEvent, height = 460 }) {
  const [layers, setLayers] = useState({ zones: true, anomalies: true, events: true });
  const [baseId, setBaseId] = useState("streets");
  const [legendOpen, setLegendOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedName, setSelectedName] = useState(null);
  const [loc, setLoc] = useState(null);
  const [notice, setNotice] = useState(null);
  const [isFs, setIsFs] = useState(false);

  const stageRef = useRef(null);
  const wrapRef = useRef(null);
  const mapRef = useRef(null);
  const readoutRef = useRef(null);
  const cursorRef = useRef(null);
  const zonesRef = useRef(zones);
  const fittedRef = useRef(false);
  const wiredRef = useRef(false);
  zonesRef.current = zones;

  const validZones = useMemo(() => zones.filter((z) => validCoords(z.latitude, z.longitude)), [zones]);
  const validAnoms = useMemo(() => anomalies.filter((a) => validCoords(a.latitude, a.longitude)), [anomalies]);
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

  const missing =
    zones.length + anomalies.length + events.length - validZones.length - validAnoms.length - validEvents.length;
  const base = BASE_LAYERS.find((b) => b.id === baseId) || BASE_LAYERS[0];
  const selected = validZones.find((z) => z.zone === selectedName) || null;
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return validZones.filter((z) => z.zone.toLowerCase().includes(q));
  }, [query, validZones]);
  const fsSupported =
    typeof document !== "undefined" &&
    (document.fullscreenEnabled !== false || !!document.webkitFullscreenEnabled);
  /* --- readout is written straight to the DOM so mousemove never re-renders --- */
  const writeReadout = () => {
    const m = mapRef.current;
    const el = readoutRef.current;
    if (!m || !el) return;
    const c = cursorRef.current || m.getCenter();
    el.textContent = `${c.lat.toFixed(5)}, ${c.lng.toFixed(5)} · z${m.getZoom()}`;
  };

  /**
   * Wire map events once, then fit the initial viewport to the zone registry.
   * whenReady can fire before the forwarded ref is attached, so the same guard
   * is retried from an effect after every render until the map is picked up.
   */
  const wire = (m) => {
    if (!m || wiredRef.current) return;
    wiredRef.current = true;
    m.on("mousemove", (e) => {
      cursorRef.current = e.latlng;
      writeReadout();
    });
    m.on("mouseout", () => {
      cursorRef.current = null;
      writeReadout();
    });
    m.on("move zoomend", writeReadout);
    const pts = zonesRef.current
      .filter((z) => validCoords(z.latitude, z.longitude))
      .map((z) => [z.latitude, z.longitude]);
    if (!fittedRef.current && pts.length) {
      fittedRef.current = true;
      m.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
    }
    writeReadout();
    setTimeout(writeReadout, 120); // overlays may not have refs on the first pass
  };

  const handleReady = () => wire(mapRef.current);
  useEffect(() => {
    wire(mapRef.current); // retries until the imperative ref exposes the map
  });

  /* Keep Leaflet in sync when the dashboard grid (or fullscreen) resizes us. */
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || typeof ResizeObserver === "undefined") return undefined;
    let lastW = 0;
    let lastH = 0;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height: h } = entry.contentRect;
      if (Math.abs(width - lastW) < 1 && Math.abs(h - lastH) < 1) return;
      lastW = width;
      lastH = h;
      mapRef.current?.invalidateSize();
    });
    ro.observe(stage);
    return () => ro.disconnect();
  }, []);

  /* Fullscreen toggle (standard + webkit prefixes) and the resize that follows. */
  useEffect(() => {
    const onChange = () => {
      setIsFs(!!(document.fullscreenElement || document.webkitFullscreenElement));
      requestAnimationFrame(() => mapRef.current?.invalidateSize());
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, []);

  /* Transient notices (geolocation errors, empty fit) clear themselves. */
  useEffect(() => {
    if (!notice) return undefined;
    const id = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(id);
  }, [notice]);

  const zoomBy = (delta) => {
    const m = mapRef.current;
    if (!m) return;
    if (delta > 0) m.zoomIn();
    else m.zoomOut();
  };

  const flyTo = (lat, lon, zoom) => {
    const m = mapRef.current;
    if (!m || !validCoords(lat, lon)) return;
    m.flyTo([lat, lon], zoom ?? Math.max(m.getZoom(), 15), { duration: 0.7 });
  };

  const flyToZone = (z, zoom) => {
    if (!z) return;
    setSelectedName(z.zone);
    setQuery("");
    setSearchOpen(false);
    flyTo(z.latitude, z.longitude, zoom);
  };

  /** Fit every visible marker — the "fit results" behaviour of a maps search. */
  const fitAll = () => {
    const m = mapRef.current;
    if (!m) return;
    const pts = [];
    if (layers.zones) validZones.forEach((z) => pts.push([z.latitude, z.longitude]));
    if (layers.anomalies) validAnoms.forEach((a) => pts.push([a.latitude, a.longitude]));
    if (layers.events) validEvents.forEach((e) => pts.push([e.lat, e.lon]));
    if (!pts.length) {
      setNotice("No visible markers to fit.");
      return;
    }
    if (pts.length === 1) {
      flyTo(pts[0][0], pts[0][1], 15);
      return;
    }
    m.fitBounds(pts, { padding: [40, 40], maxZoom: 15 });
  };

  const locate = () => {
    if (!navigator.geolocation) {
      setNotice("Geolocation is not supported by this browser.");
      return;
    }
    setNotice(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        setLoc({ lat: latitude, lng: longitude, acc: accuracy || 30 });
        flyTo(latitude, longitude, 15);
      },
      (err) => setNotice(`Location unavailable: ${err.message}`),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  };

  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    try {
      const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
      if (!fsEl) (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
      else (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    } catch {
      setNotice("Fullscreen is not available in this browser.");
    }
  };

  return (
    <div className="map-wrap" ref={wrapRef}>
      <div className="map-toggles" role="group" aria-label="Map layers">
        {[["zones", "Zones"], ["anomalies", "Anomalies"], ["events", "Civic events"]].map(([k, label]) => (
          <label key={k} className="check">
            <input
              type="checkbox"
              checked={layers[k]}
              onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))}
            />
            <span>{label}</span>
          </label>
        ))}
        <span className="muted small">Synthetic coordinates · fictional city</span>
      </div>

      <div className="map-stage" ref={stageRef} style={{ height: `${height}px` }} role="region" aria-label="Live city map">
        <MapContainer
          ref={mapRef}
          center={CITY_CENTER}
          zoom={CITY_ZOOM}
          scrollWheelZoom
          zoomControl={false}
          whenReady={handleReady}
          style={{ height: "100%" }}
        >
          <TileLayer
            key={base.id}
            url={base.url}
            attribution={base.attribution}
            maxZoom={base.maxZoom}
            // Only forward subdomains/maxNativeZoom when the layer defines them:
            // passing `undefined` overrides Leaflet's defaults ("abc") and crashes
            // tile loading (_getSubdomain reads .length of undefined).
            {...(base.subdomains ? { subdomains: base.subdomains } : {})}
            {...(base.maxNativeZoom ? { maxNativeZoom: base.maxNativeZoom } : {})}
          />
          {base.labels && (
            <TileLayer key={`${base.id}-labels`} url={base.labels} attribution="Labels &copy; Esri" maxZoom={19} />
          )}
          <ScaleControl position="bottomleft" imperial={false} />

          {layers.zones && validZones.map((z) => (
            <Circle
              key={z.zone}
              center={[z.latitude, z.longitude]}
              radius={1400}
              pathOptions={{
                color: healthColor(z.health),
                fillColor: healthColor(z.health),
                fillOpacity: 0.18,
                weight: 2,
              }}
              eventHandlers={{ click: () => setSelectedName(z.zone) }}
            >
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

          {selected && (
            <Circle
              center={[selected.latitude, selected.longitude]}
              radius={1750}
              interactive={false}
              pathOptions={{ color: "#e9eeff", weight: 3, fill: false, dashArray: "6 8" }}
            />
          )}

          {layers.events && validEvents.map((e) => (
            <Circle
              key={e.id}
              center={[e.lat, e.lon]}
              radius={1900}
              pathOptions={{ color: sevMeta(e.severity).color, dashArray: "8 6", fillOpacity: 0.06, weight: 2 }}
            >
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
            <CircleMarker
              key={a.id}
              center={[a.latitude, a.longitude]}
              radius={5 + Math.min(1, a.strength ?? 0) * 8}
              pathOptions={{
                color: sevMeta(a.severity).color,
                fillColor: sevMeta(a.severity).color,
                fillOpacity: 0.65,
                weight: 2,
              }}
            >
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

          {loc && (
            <>
              <Circle
                center={[loc.lat, loc.lng]}
                radius={Math.max(25, loc.acc || 25)}
                pathOptions={{ color: "#38bdf8", weight: 1, fillOpacity: 0.12 }}
              >
                <Tooltip direction="top">Your location (±{Math.round(loc.acc)} m)</Tooltip>
              </Circle>
              <CircleMarker
                center={[loc.lat, loc.lng]}
                radius={7}
                pathOptions={{ color: "#ffffff", fillColor: "#38bdf8", fillOpacity: 1, weight: 2 }}
              >
                <Popup>
                  You are here · {loc.lat.toFixed(5)}, {loc.lng.toFixed(5)}
                  <br />
                  <button type="button" className="link-btn" onClick={() => setLoc(null)}>Clear location</button>
                </Popup>
              </CircleMarker>
            </>
          )}
        </MapContainer>
        {/* Google-style zone search — filters the registry and flies to the hit. */}
        <div className="map-search map-ctl">
          <div className="map-search-box map-card">
            <span aria-hidden="true" className="muted">⌕</span>
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); }}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => setSearchOpen(false)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches[0]) flyToZone(matches[0]);
                if (e.key === "Escape") { setQuery(""); setSearchOpen(false); }
              }}
              placeholder="Search zones…"
              aria-label="Search zones"
            />
            {query && (
              <button type="button" className="map-x" onClick={() => setQuery("")} aria-label="Clear search">✕</button>
            )}
          </div>
          {searchOpen && query.trim() && (
            <ul className="map-results map-card" role="listbox" aria-label="Zone search results">
              {matches.length === 0 && <li className="muted small" style={{ padding: "8px 10px" }}>No zone matches “{query}”.</li>}
              {matches.map((z) => (
                <li key={z.zone} role="option" aria-selected={z.zone === selectedName}>
                  <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => flyToZone(z)}>
                    <b>{z.zone}</b>
                    <span className="muted small">{healthBand(z.health).label} {z.health}/100 · risk {z.risk}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Basemap switcher (Google-Maps-style segmented control) + tools. */}
        <div className="map-topright map-ctl">
          <div className="map-seg" role="group" aria-label="Map style">
            {BASE_LAYERS.map((b) => (
              <button
                key={b.id}
                type="button"
                className={b.id === baseId ? "active" : ""}
                aria-pressed={b.id === baseId}
                title={`${b.label} basemap`}
                onClick={() => setBaseId(b.id)}
              >
                {b.label}
              </button>
            ))}
          </div>
          <div className="map-icons">
            <button
              type="button"
              className={legendOpen ? "active" : ""}
              aria-pressed={legendOpen}
              onClick={() => setLegendOpen((v) => !v)}
              title="Map legend"
              aria-label="Toggle map legend"
            >
              ▤
            </button>
            <button type="button" onClick={locate} title="Find my location" aria-label="Find my location">◎</button>
            {fsSupported && (
              <button
                type="button"
                onClick={toggleFullscreen}
                title={isFs ? "Exit fullscreen" : "Fullscreen"}
                aria-label="Toggle fullscreen"
              >
                {isFs ? "⤡" : "⛶"}
              </button>
            )}
          </div>
        </div>

        {/* Zoom / fit stack — bottom right, above the attribution strip. */}
        <div className="map-zoom map-ctl" role="group" aria-label="Map navigation">
          <button type="button" onClick={() => zoomBy(1)} aria-label="Zoom in" title="Zoom in">＋</button>
          <button type="button" onClick={() => zoomBy(-1)} aria-label="Zoom out" title="Zoom out">－</button>
          <span className="map-zoom-sep" />
          <button type="button" onClick={fitAll} aria-label="Fit all markers" title="Fit all markers">⊞</button>
        </div>

        {/* Cursor coordinates + zoom level, written straight to the DOM. */}
        <div className="map-readout map-ctl">
          <span ref={readoutRef}>—</span>
        </div>
        {/* Legend — colour has a label everywhere in CityPulse. */}
        {legendOpen && (
          <div className="map-legend map-card" role="note" aria-label="Map legend">
            <div className="row between">
              <b>Legend</b>
              <button type="button" className="map-x" onClick={() => setLegendOpen(false)} aria-label="Close legend">✕</button>
            </div>
            <div className="legend-title muted small">Zone health</div>
            {[
              [healthBand(95), "Healthy (85–100)"],
              [healthBand(80), "Stable (70–84)"],
              [healthBand(60), "Degraded (50–69)"],
              [healthBand(40), "Critical (<50)"],
            ].map(([band, label]) => (
              <div key={label} className="legend-row">
                <i className="legend-dot" style={{ background: band.color }} />
                <span>{label}</span>
              </div>
            ))}
            <div className="legend-title muted small">Anomaly severity</div>
            {["low", "moderate", "high", "critical"].map((s) => (
              <div key={s} className="legend-row">
                <i className="legend-dot" style={{ background: sevMeta(s).color }} />
                <span>{sevMeta(s).icon} {sevMeta(s).label}</span>
              </div>
            ))}
            <div className="legend-row">
              <i className="legend-dot legend-dot--event" />
              <span>Possible civic event footprint</span>
            </div>
            {loc && (
              <div className="legend-row">
                <i className="legend-dot" style={{ background: "#38bdf8", boxShadow: "0 0 0 2px #fff inset" }} />
                <span>Your location</span>
              </div>
            )}
          </div>
        )}

        {/* Selected-zone place card (Google Maps "place" panel behaviour). */}
        {selected && (
          <div className="map-place map-card" role="region" aria-label={`Selected ${selected.zone}`}>
            <div className="row between">
              <b>{selected.zone}</b>
              <button type="button" className="map-x" onClick={() => setSelectedName(null)} aria-label="Close zone card">✕</button>
            </div>
            <div className="row wrap" style={{ gap: 6 }}>
              <span className="map-chip" style={{ color: healthBand(selected.health).color }}>
                {selected.health}/100 · {healthBand(selected.health).label}
              </span>
              <span className="map-chip">
                Risk {selected.risk}{selected.risk_band ? ` · ${selected.risk_band}` : ""}
              </span>
              <span className="map-chip">
                {selected.anomalies} active anomal{selected.anomalies === 1 ? "y" : "ies"}
              </span>
            </div>
            <div className="map-place-metrics">
              {Object.entries(selected.metrics || {}).map(([k, v]) => (
                <div key={k}><span>{metricLabel(k)}</span><b>{v}</b></div>
              ))}
            </div>
            <div className="row between wrap" style={{ gap: 8 }}>
              <button type="button" className="map-btn" onClick={() => flyTo(selected.latitude, selected.longitude, 16)}>
                Zoom in
              </button>
              {selected.event_confidence != null && (
                <span className="muted small">Event confidence {selected.event_confidence}%</span>
              )}
            </div>
          </div>
        )}

        {/* Transient notices: geolocation errors, empty fit, fullscreen failures. */}
        {notice && (
          <div className="map-notice map-card" role="status">
            <span>{notice}</span>
            <button type="button" className="map-x" onClick={() => setNotice(null)} aria-label="Dismiss notice">✕</button>
          </div>
        )}
      </div>

      {missing > 0 && (
        <p className="muted small">
          {missing} record{missing === 1 ? "" : "s"} hidden: invalid or missing coordinates.
        </p>
      )}
    </div>
  );
}

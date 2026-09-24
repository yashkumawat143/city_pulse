import { useCallback, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import api from "./lib/api";
import { useCityPulse } from "./hooks/useCityPulse";
import { Footer, TopBar } from "./components/Shell";
import EventDrawer from "./components/EventDrawer";
import ErrorBoundary from "./components/ErrorBoundary";
import { Card, Empty, ErrorState, Loading, Tag } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Events from "./pages/Events";
import Anomalies from "./pages/Anomalies";
import Alerts from "./pages/Alerts";
import Sources from "./pages/Sources";
import Simulation from "./pages/Simulation";

export default function App() {
  const { snapshot, config, conn, lastUpdate, error, loading, refresh, live } = useCityPulse();
  const [eventId, setEventId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [notice, setNotice] = useState(null);

  const inspectEvent = useCallback((id) => { setNotice(null); setEventId(id); }, []);

  /** Lifecycle actions always re-sync from the backend so the UI reflects real state. */
  const onEventAction = useCallback(async (id, action) => {
    setBusyId(id);
    setNotice(null);
    try {
      const updated = await api.disruptionAct(id, action);
      setNotice({ kind: "ok", text: `${id} → ${updated.status} (state ${updated.state})` });
      await refresh();
    } catch (e) {
      setNotice({ kind: "error", text: `${id}: ${e.message}` });
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <TopBar conn={conn} lastUpdate={lastUpdate} snapshot={snapshot} onRefresh={refresh} />
      {snapshot && !live && (
        <p className="banner warn" role="status">
          Live WebSocket unavailable — showing REST fallback data ({String(conn).toLowerCase()}). Monitoring stays
          usable; lifecycle actions still write to the backend.
        </p>
      )}
      {notice && (
        <p className={notice.kind === "ok" ? "banner ok" : "banner error"} role="status">
          {notice.text}
          <button type="button" className="link-btn" onClick={() => setNotice(null)} aria-label="Dismiss notification">✕</button>
        </p>
      )}

      <main id="main">
        {!snapshot && loading && <Loading label="Connecting to the CityPulse backend…" rows={4} />}
        {!snapshot && !loading && (
          <Card title="Backend unavailable">
            <ErrorState
              message={error || "No response from the CityPulse API."}
              onRetry={refresh}
              hint="Start the backend with: cd backend && uvicorn main:app --reload (see README). This page resumes automatically once the API responds."
            />
          </Card>
        )}
        {snapshot && (
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Dashboard snapshot={snapshot} onInspectEvent={inspectEvent}
                                                  onEventAction={onEventAction} busyId={busyId} />} />
              <Route path="/events" element={<Events snapshot={snapshot} onInspectEvent={inspectEvent}
                                                    onEventAction={onEventAction} busyId={busyId} />} />
              <Route path="/anomalies" element={<Anomalies config={config} />} />
              <Route path="/alerts" element={<Alerts refresh={refresh} onInspectEvent={inspectEvent} />} />
              <Route path="/sources" element={<Sources snapshot={snapshot} config={config} conn={conn} refresh={refresh} />} />
              <Route path="/simulation" element={<Simulation snapshot={snapshot} config={config} conn={conn} refresh={refresh} />} />
              <Route path="*" element={(
                <Card title="Page not found">
                  <Empty title="This CityPulse view does not exist"
                         hint="Use the navigation above to reach the dashboard, events, anomalies, alerts, sources or simulation.">
                    <Link to="/" className="btn">Back to dashboard</Link>
                  </Empty>
                </Card>
              )} />
            </Routes>
          </ErrorBoundary>
        )}
        {snapshot && (
          <p className="status-line">
            <Tag tone="warn">SIMULATED DATA</Tag>
            <span className="muted small">
              {snapshot.coverage?.metric_streams_live}/{snapshot.coverage?.metric_streams_total} metric streams live ·
              coverage {snapshot.coverage?.coverage_pct}% · tick {snapshot.sim?.tick} · {snapshot.sim?.scenario} @{" "}
              {snapshot.sim?.speed}x · delivery {live ? "WebSocket" : conn}
            </span>
          </p>
        )}
      </main>

      <EventDrawer eventId={eventId} onClose={() => setEventId(null)} onChanged={refresh} />
      <Footer />
    </>
  );
}

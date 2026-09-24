"""
app.py
------
The "frontend" of CityPulse v2.0 — Live Civic Intelligence & Event Detection.

This file is ONLY responsible for the Streamlit interface, the replay/demo
controls, and presentation mode. All analysis logic lives in pipeline.py, so
the UI stays thin and the "brain" stays testable.

Run with:
    streamlit run app.py
"""

import time

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import pipeline
import utils
from config import (
    CITY_CENTER,
    DEMO_SPEEDS,
    DEMO_STEP_SECONDS,
    SEVERITY_EMOJI,
    STATUS_COLORS,
    TREND_ARROW,
    ZONE_COORDS,
)

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="CityPulse — Live Civic Intelligence",
    page_icon="🌆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# DATA LOADING (cached — CSV reading and full-dataset anomaly pre-compute
# happen ONCE; replay-time filtering is done fresh on every slider move in
# pipeline.get_current_state, so replay results are never stale)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Loading city feeds…")
def load_prepared() -> dict[str, pd.DataFrame]:
    return pipeline.prepare_data()


prepared = load_prepared()

weather_df, traffic_df, complaints_df = prepared["weather"], prepared["traffic"], prepared["complaints"]

if weather_df.empty and traffic_df.empty and complaints_df.empty:
    st.error(
        "⚠️ No data found in the `data/` folder. Run `python generate_data.py` first, "
        "then restart this app from the CityPulse folder."
    )
    st.stop()

all_timestamps = pipeline.get_available_timestamps(prepared)
if not all_timestamps:
    st.error("⚠️ Data files were found but contained no valid timestamps. Re-run `python generate_data.py`.")
    st.stop()

# ---------------------------------------------------------------------------
# SESSION STATE (safe initialization — the slider stays the single source of
# truth for replay time; everything else is a plain session key)
# ---------------------------------------------------------------------------

if "replay_index" not in st.session_state:
    st.session_state.replay_index = len(all_timestamps) - 1  # start at the latest moment
if "playing" not in st.session_state:
    st.session_state.playing = False
if "speed" not in st.session_state:
    st.session_state.speed = "1x"
if "presentation_mode" not in st.session_state:
    st.session_state.presentation_mode = False
if "selected_zone" not in st.session_state:
    st.session_state.selected_zone = None
if "map_reset" not in st.session_state:
    st.session_state.map_reset = 0
if "chat" not in st.session_state:
    st.session_state.chat = []

P = st.session_state.presentation_mode  # shorthand used across the UI
last_index = len(all_timestamps) - 1

# DEMO PLAYBACK: advance one step at the very START of each rerun, BEFORE any
# widget with the replay key is instantiated (Streamlit forbids writing to a
# widget-bound session key afterwards). The frame renders fully, then a
# st.rerun() at the bottom of the script schedules the next tick.
if st.session_state.playing:
    if st.session_state.replay_index < last_index:
        st.session_state.replay_index += 1
    else:
        st.session_state.playing = False  # end of recording reached

# ---------------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------------

header_l, header_r = st.columns([4, 1])
with header_l:
    st.markdown("## 🌆 CITYPULSE")
    st.markdown("**Live Civic Intelligence Dashboard** — multi-signal civic event detection for your city")
with header_r:
    st.markdown(
        "<div style='text-align:right'>"
        "<span style='color:#2ecc71;font-weight:600'>🟢 SYSTEM ONLINE</span>"
        "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# RUN THE PIPELINE for the current replay moment (needed early: the city
# status banner sits above the controls)
# ---------------------------------------------------------------------------

replay_time = all_timestamps[st.session_state.replay_index]
st.session_state.replay_time = replay_time  # spec-named session key

state = pipeline.get_current_state(prepared, replay_time)
health_scores = state["health_scores"]
zone_names = list(health_scores.keys())
city_status = state["city_status"]
civic_events = state["civic_events"]

# ---------------------------------------------------------------------------
# CITY STATUS BANNER (Upgrade 6) — prototype label, not an official class
# ---------------------------------------------------------------------------

status_color = "#f1c40f" if city_status["level"] == "ATTENTION REQUIRED" else "#2ecc71"
stable_n = len(city_status["stable_zones"])
risk_n = len(city_status["at_risk_zones"])
st.markdown(
    f"""
    <div style='border:1px solid {status_color}55; border-radius:10px; padding:0.6rem 1rem; background:{status_color}11'>
      <span style='font-weight:800;font-size:1.05rem;color:{status_color}'>{city_status['emoji']} CITY STATUS: {city_status['level']}</span>
      <span style='color:gray'>·</span>
      🏘 Stable zones: <b>{stable_n}</b> · At-risk zones: <b>{risk_n}</b> ·
      🚨 Alerts: <b>{city_status['active_alerts']}</b> ·
      🌧 Weather events: <b>{city_status['weather_events']}</b> ·
      🚗 Traffic anomalies: <b>{city_status['traffic_anomalies']}</b> ·
      📢 Complaint spikes: <b>{city_status['complaint_spikes']}</b>
      <span style='color:gray;font-size:0.85rem'>(CityPulse prototype status — not an official classification)</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# REPLAY + DEMO CONTROLS (Upgrades: replay preserved + Demo Mode added)
# ---------------------------------------------------------------------------

st.markdown("### ⏱ CITY REPLAY  ·  🎬 DEMO MODE")

nav1, nav2, nav3, nav4, nav5, speed_col, slider_col = st.columns([1, 1, 1, 1, 1, 1.2, 8])

with nav1:
    if st.button("⏮ Previous", width="stretch"):
        st.session_state.replay_index = max(0, st.session_state.replay_index - 1)
        st.session_state.playing = False
with nav2:
    if st.button("⏭ Next", width="stretch"):
        st.session_state.replay_index = min(last_index, st.session_state.replay_index + 1)
        st.session_state.playing = False
with nav3:
    play_label = "⏸ Pause" if st.session_state.playing else "▶ Play"
    if st.button(play_label, width="stretch"):
        # Pressing Play at the end of the recording rewinds to the start so a
        # presenter can always press Play and watch the full story unfold.
        if not st.session_state.playing and st.session_state.replay_index >= last_index:
            st.session_state.replay_index = 0
        st.session_state.playing = not st.session_state.playing
with nav4:
    if st.button("↻ Reset", width="stretch"):
        st.session_state.replay_index = 0
        st.session_state.playing = False
with nav5:
    if st.button("↺ Latest", width="stretch"):
        st.session_state.replay_index = last_index
        st.session_state.playing = False
with speed_col:
    st.selectbox("Speed", [f"{s}x" for s in DEMO_SPEEDS], key="speed", label_visibility="collapsed")

label_map = {i: ts.strftime("%H:%M") for i, ts in enumerate(all_timestamps)}
# The slider is THE single source of truth for replay time (bound to
# st.session_state.replay_index), so buttons and playback stay in sync with it.
st.select_slider(
    "Drag to move through city time",
    options=list(range(len(all_timestamps))),
    key="replay_index",
    format_func=lambda i: label_map[i],
    label_visibility="collapsed",
)

st.caption(
    f"🕓 Viewing city state as of **{replay_time.strftime('%H:%M')}** — every panel uses ONLY data received up to "
    "this moment (no future data)." + ("" if P else " · Playback speed affects demo pacing only.")
)

st.divider()

# ---------------------------------------------------------------------------
# ZONE CARDS + CITY SCORE
# ---------------------------------------------------------------------------

st.markdown("### 🏙️ Zones at a glance")
if not zone_names:
    st.info("No zone data available yet at this point in the replay.")
else:
    city_score = sum(i["health_score"] for i in health_scores.values()) / len(health_scores)
    card_cols = st.columns(len(zone_names) + 1)
    for col, zone in zip(card_cols, zone_names):
        info = health_scores[zone]
        color = STATUS_COLORS.get(info["status"], "#95a5a6")

        # Live anomaly notes (only metrics flagged at THIS replay moment).
        live_flags = [
            title
            for metric, title in (("rainfall", "rain"), ("traffic", "traffic"), ("complaints", "complaints"))
            if state["latest_anomalies"].get((zone, metric), {}).get("is_anomaly")
            and state["latest_anomalies"][(zone, metric)]["timestamp"] == replay_time
        ]
        flag_note = f"<br><span style='color:{color}'>⚠ Unusual: {' + '.join(live_flags)}</span>" if live_flags else ""

        with col:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style='line-height:1.5'>
                      <span style='font-size:1.05rem;font-weight:700'>{zone}</span>
                      <span style='float:right;font-weight:600;color:{color}'>{info['status_emoji']} {info['status']}</span>
                      <div style='font-size:2rem;font-weight:800;margin:0.2rem 0'>{info['health_score']:.0f}
                        <span style='font-size:1rem;font-weight:400;color:gray'>/ 100 ❤️</span>
                      </div>
                      🌧 {info['condition']} · {info['rainfall_mm']:.1f} mm<br>
                      🚗 {info['congestion_pct']:.0f}% congestion · {info['incidents']} incident(s)<br>
                      📢 {info['total_complaints']} complaints this window
                      {flag_note}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    with card_cols[-1]:
        with st.container(border=True):
            st.markdown(
                f"""
                <div style='line-height:1.5'>
                  <span style='font-size:1.05rem;font-weight:700'>🏙 City Score</span>
                  <div style='font-size:2rem;font-weight:800;margin:0.2rem 0'>{city_score:.0f}
                    <span style='font-size:1rem;font-weight:400;color:gray'>/ 100 avg</span>
                  </div>
                  {stable_n} stable · {risk_n} at risk<br>
                  {len(civic_events)} active civic event(s)
                </div>
                """,
                unsafe_allow_html=True,
            )

if not P:
    st.caption(
        "ℹ️ Civic Health Score is a CityPulse-generated prototype indicator — not an official government metric."
    )
st.divider()

# ---------------------------------------------------------------------------
# CITY RISK MAP (Upgrade 18: popups now include incidents, anomalies, event
# confidence; clicking a zone selects it for the whole dashboard)
# ---------------------------------------------------------------------------

map_l, map_r = st.columns([7, 5])

with map_l:
    st.markdown("### 🗺️ City Risk Map")
    if not P:
        st.caption("Illustrative layout of a fictional city — zone positions are schematic, not real coordinates. Click a zone to select it.")

    fmap = folium.Map(location=CITY_CENTER, zoom_start=13, tiles="OpenStreetMap", control_scale=False)
    folium.Circle(
        CITY_CENTER, radius=2600, color="#4a4a4a", weight=1.5, fill=False, tooltip="City boundary (illustrative)"
    ).add_to(fmap)

    for zone in zone_names:
        info = health_scores[zone]
        color = STATUS_COLORS.get(info["status"], "#95a5a6")
        ev = civic_events.get(zone)
        ev_line = (
            f"<br>🚨 Civic event: <b>{ev['signal_titles_str']}</b><br>🎯 Event confidence: <b>{ev['confidence']}%</b> (prototype)"
            if ev
            else ""
        )
        active_anoms = [m for m in state["anomalies_now"].get(zone, {})]
        anom_line = (
            f"<br>⚠ Active anomalies: <b>{', '.join(active_anoms)}</b>" if active_anoms else "<br>✅ No active anomalies"
        )
        popup_html = f"""
            <div style="font-family:sans-serif;min-width:240px">
              <b>{zone}</b> — {info['status_emoji']} {info['status']}<br>
              ❤️ Civic Health: <b>{info['health_score']:.0f}/100</b><br>
              🌧 Rainfall: {info['rainfall_mm']:.1f} mm ({info['condition']})<br>
              🚗 Traffic: {info['congestion_pct']:.0f}% · {info['incidents']} incident(s)<br>
              📢 Complaints: {info['total_complaints']}
              {anom_line}{ev_line}
            </div>"""
        folium.CircleMarker(
            location=ZONE_COORDS.get(zone, CITY_CENTER),
            radius=18 + (100 - info["health_score"]) / 6,  # worse health -> bigger marker
            color="#ffffff",
            weight=1.5,
            fill=True,
            fill_color=color,
            fill_opacity=0.65,
            tooltip=f"{zone} — {info['status']} (Health {info['health_score']:.0f}/100). Click to select.",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(fmap)

    map_result = st_folium(
        fmap,
        key=f"city_map_{st.session_state.map_reset}",
        height=430,
        width="stretch",
        returned_objects=["last_object_clicked"],
    )

with map_r:
    # --- Zone selection: map click OR the selectbox, kept in sync ----------
    # The key-bound selectbox is the single source of truth (same pattern as
    # the replay slider). A map click updates st.session_state.selected_zone
    # BEFORE the widget is instantiated, which is the only safe moment.
    clicked_zone = None
    if map_result and map_result.get("last_object_clicked"):
        lat = map_result["last_object_clicked"]["lat"]
        lon = map_result["last_object_clicked"]["lng"]
        clicked_zone = min(
            zone_names,
            key=lambda z: (ZONE_COORDS[z][0] - lat) ** 2 + (ZONE_COORDS[z][1] - lon) ** 2,
        )

    if clicked_zone:
        st.session_state.selected_zone = clicked_zone

    if not zone_names:
        selected_zone = None
    else:
        if st.session_state.selected_zone not in zone_names:
            st.session_state.selected_zone = min(zone_names, key=lambda z: health_scores[z]["health_score"])
        st.selectbox("Selected zone", zone_names, key="selected_zone")
        selected_zone = st.session_state.selected_zone

    if selected_zone:
        info = health_scores[selected_zone]
        ev = civic_events.get(selected_zone)
        st.markdown(f"#### 📍 {selected_zone}")
        st.markdown(f"**{info['status_emoji']} {info['status']}** — Civic Health Score **{info['health_score']:.0f}/100**")
        st.markdown(
            f"- 🌧 **Rainfall:** {info['rainfall_mm']:.1f} mm ({info['condition']})\n"
            f"- 🚗 **Traffic:** {info['congestion_pct']:.0f}% congestion · {info['incidents']} incident(s)\n"
            f"- 📢 **Complaints:** {info['total_complaints']} in the latest window"
        )
        active_anoms = list(state["anomalies_now"].get(selected_zone, {}).keys())
        st.markdown(
            f"- ⚠ **Active anomalies:** {', '.join(active_anoms) if active_anoms else 'none'}\n"
            f"- 🎯 **Event confidence:** {ev['confidence']}% (prototype)" if ev else "- 🎯 **Event confidence:** — (no active civic event)"
        )
        zone_alerts = [a for a in state["alerts"] if a["zone"] == selected_zone]
        if zone_alerts:
            st.markdown("**🚨 Active alerts for this zone:**")
            for a in zone_alerts[:4]:
                st.markdown(f"- {SEVERITY_EMOJI.get(a['severity'], '')} *{a['severity']}* — {a['message']}")
        else:
            st.markdown("✅ No active alerts for this zone.")

st.divider()

# ---------------------------------------------------------------------------
# ACTIVE CIVIC EVENT (Upgrades 1 + 5 + 20 panel) + ANOMALY DIAGNOSTIC CARDS
# ---------------------------------------------------------------------------

st.markdown("### 🚨 Active Civic Event")
if civic_events:
    top_zone, top_ev = max(civic_events.items(), key=lambda kv: kv[1]["confidence"])
    evc1, evc2 = st.columns([2, 3])
    with evc1:
        with st.container(border=True):
            conf_color = "#e74c3c" if top_ev["confidence"] >= 70 else "#e67e22"
            st.markdown(
                f"""
                <div style='line-height:1.6'>
                  <span style='font-weight:800;font-size:1.1rem'>🌧️ CIVIC EVENT DETECTED</span><br>
                  <b>{top_ev['zone']}</b><br>
                  {top_ev['signal_titles_str']}<br><br>
                  <span style='font-weight:700'>CityPulse Event Confidence</span><br>
                  <span style='font-size:2rem;font-weight:800;color:{conf_color}'>{top_ev['confidence']}%</span><br>
                  <span style='color:gray'>Signals detected: {len(top_ev['signals'])} ·
                  Time window: ~{top_ev['window_minutes']} min ·
                  Status: {top_ev['status']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with evc2:
        st.markdown(f"**Event explanation — {top_ev['zone']}**")
        st.markdown(f"- **Signals:** {', '.join(top_ev['signals'])}")
        st.markdown(f"- **Started:** {top_ev['started'].strftime('%H:%M')} · **Last signal:** {top_ev['last_signal_time'].strftime('%H:%M')}")
        st.markdown(f"- **Possible temporal sequence:** {top_ev['sequence']}")
        st.markdown(
            f"- **Signal strength:** mean deviation {top_ev['mean_z']:.1f}σ above baselines · "
            f"longest persistence {top_ev['max_persistence']} step(s) · signals clustered within {top_ev['spread_minutes']} min"
        )
        st.caption(
            "CityPulse Event Confidence is an internal prototype score (signal strength + diversity + timing + persistence). "
            "It is NOT a probability and not statistical certainty. Possible temporal association — not a confirmed cause."
        )
        if len(civic_events) > 1:
            st.caption(f"Also active in: {', '.join(z for z in civic_events if z != top_zone)}")
else:
    st.success("✅ No multi-signal civic event detected right now. The system keeps monitoring all zones.")

# Anomaly diagnostic cards (Upgrade 10) — shown whenever live anomalies exist.
if state["anomalies_now"]:
    st.markdown("#### ⚠️ Active Anomalies")
    metric_titles = {"rainfall": "🌧 Rainfall", "traffic": "🚗 Traffic", "complaints": "📢 Complaints"}
    anom_cols = st.columns(max(len(state["anomalies_now"]), 1))
    for col, (zone, metrics) in zip(anom_cols, state["anomalies_now"].items()):
        with col:
            with st.container(border=True):
                st.markdown(f"**{zone}** — {len(metrics)} unusual signal(s)")
                for metric, a in metrics.items():
                    title = metric_titles.get(metric, metric)
                    baseline = a["baseline_mean"]
                    if baseline is None:
                        st.markdown(f"{title}: **{a['value']:.1f}** (baseline unavailable)")
                        continue
                    pct = utils.safe_pct_difference(a["value"], baseline)
                    pct_bit = utils.pct_text(pct) if pct is not None else utils.format_signed(a["value"] - baseline)
                    st.markdown(
                        f"{title}<br>"
                        f"<span style='color:gray'>Current <b>{a['value']:.1f}</b> · Baseline {baseline:.1f} · "
                        f"Deviation <b style='color:#e67e22'>{pct_bit}</b></span>",
                        unsafe_allow_html=True,
                    )
elif not civic_events:
    st.caption("All monitored metrics are within their recent baselines.")

st.divider()

# ---------------------------------------------------------------------------
# ALERTS + SUMMARY
# ---------------------------------------------------------------------------

alert_col, summary_col = st.columns([3, 2])

with alert_col:
    st.markdown("### 🚨 Active Civic Alerts")
    alerts = state["alerts"]
    if alerts:
        for a in alerts:
            sev_color = {
                "Low": "#2ecc71",
                "Moderate": "#f1c40f",
                "High": "#e67e22",
                "Critical": "#e74c3c",
            }.get(a["severity"], "#95a5a6")
            with st.container(border=True):
                st.markdown(
                    f"<span style='color:{sev_color};font-weight:700'>{SEVERITY_EMOJI.get(a['severity'], '')} "
                    f"{a['severity'].upper()}</span> &nbsp;·&nbsp; <b>{a['type']}</b> &nbsp;·&nbsp; {a['zone']}",
                    unsafe_allow_html=True,
                )
                st.markdown(a["message"])
    else:
        st.success("✅ No active alerts — all zones are within normal ranges.")

with summary_col:
    st.markdown("### 🧠 CityPulse Summary")
    if not P:
        st.caption("Automated rule-based summary — no external AI service.")
    st.info(state["summary"])

st.divider()

# ---------------------------------------------------------------------------
# WHAT HAPPENED? (Upgrade 7 — dynamic narrative, no hard-coded story)
# ---------------------------------------------------------------------------

st.markdown("### 📖 What Happened?")
narrative = state["narrative"]
if narrative:
    visible_narrative = narrative if P else narrative
    shown = visible_narrative[-12:]
    for e in shown:
        st.markdown(f"**{e['time'].strftime('%H:%M')}** {e['icon']} {e['text']}")
    if len(narrative) > 12 and not P:
        with st.expander("Show full event log"):
            for e in narrative[:-12]:
                st.markdown(f"**{e['time'].strftime('%H:%M')}** {e['icon']} {e['text']}")
else:
    st.info("Not enough processed history yet to describe recent changes — advance the replay a few steps.")

st.divider()

# ---------------------------------------------------------------------------
# WHY AT RISK? + PREDICTION (Upgrades 5 + 16)
# ---------------------------------------------------------------------------

risk_col, pred_col = st.columns([3, 2])

with risk_col:
    st.markdown(f"### 🔎 Why is {selected_zone or 'this zone'} at risk?")
    reasons = state["zone_risk_reasons"].get(selected_zone, [])
    for i, r in enumerate(reasons, 1):
        st.markdown(f"{i}. {r}")
    if not reasons:
        st.caption("Select a zone to see its dynamic risk explanation.")

with pred_col:
    st.markdown("### 🔮 Prototype Trend-Based Prediction")
    pred_items = [
        i for i in state["predictions"]["items"]
        if i["trend"] != "flat" and (selected_zone is None or i["zone"] == selected_zone)
    ] or [i for i in state["predictions"]["items"] if i["trend"] != "flat"]
    if pred_items:
        for item in pred_items[:4]:
            st.markdown(
                f"- {TREND_ARROW[item['trend']]} **{item['zone']} — {item['metric_title']}**: current {item['current']}, "
                f"estimated next 30 min **{item['range_low']}–{item['range_high']}**"
            )
            if not P:
                st.caption(f"Reason: {item['reason']} ({item['confidence']})")
    else:
        st.caption("No strong short-term trends detected — metrics look stable.")
    st.caption(f"_{state['predictions']['note']}_")

st.divider()

# ---------------------------------------------------------------------------
# ANALYTICS (all charts respect the replay timestamp)
# ---------------------------------------------------------------------------

st.markdown("### 📊 Analytics")
if not zone_names:
    analytics_zone = None
else:
    default_analytics = min(zone_names, key=lambda z: health_scores[z]["health_score"])
    analytics_zone = st.selectbox("Zone", zone_names, index=zone_names.index(default_analytics), key="analytics_zone")

chart1, chart2 = st.columns(2)

with chart1:
    st.markdown(f"**🌧 Rainfall vs 🚗 Traffic — {analytics_zone or '—'}**")
    z_weather = state["visible_weather"][state["visible_weather"]["zone"] == analytics_zone].sort_values("timestamp") if analytics_zone else pd.DataFrame()
    z_traffic = state["visible_traffic"][state["visible_traffic"]["zone"] == analytics_zone].sort_values("timestamp") if analytics_zone else pd.DataFrame()
    if not z_weather.empty and not z_traffic.empty:
        fig_rt = go.Figure()
        fig_rt.add_trace(
            go.Scatter(
                x=z_weather["timestamp"], y=z_weather["rainfall_mm"], name="Rainfall (mm)",
                line=dict(color="#3498db", width=3), fill="tozeroy", fillcolor="rgba(52,152,219,0.15)",
            )
        )
        fig_rt.add_trace(
            go.Scatter(
                x=z_traffic["timestamp"], y=z_traffic["congestion_pct"], name="Congestion (%)",
                yaxis="y2", line=dict(color="#e67e22", width=3),
            )
        )
        fig_rt.update_layout(
            yaxis=dict(title="Rainfall (mm)"),
            yaxis2=dict(title="Congestion (%)", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.12),
            margin=dict(l=10, r=10, t=10, b=10),
            height=330,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rt, width="stretch")
        if not P:
            # Show the strongest LAGGED relationship with direction-aware wording.
            zone_lagged = state["lagged_relationships"].get(analytics_zone, [])
            if zone_lagged:
                top = zone_lagged[0]
                st.caption(f"⏱ {top['sentence']}")
            else:
                st.caption("⚠️ Not enough historical observations to calculate a reliable lagged relationship yet.")
    else:
        st.caption("Not enough data at this point in the replay.")

with chart2:
    st.markdown(f"**📢 Complaints by category — {analytics_zone or '—'}**")
    z_complaints = state["visible_complaints"][state["visible_complaints"]["zone"] == analytics_zone] if analytics_zone else pd.DataFrame()
    if not z_complaints.empty:
        cat_pivot = (
            z_complaints.pivot_table(index="timestamp", columns="category", values="count", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        fig_cat = go.Figure()
        for category in cat_pivot.columns:
            fig_cat.add_trace(go.Scatter(x=cat_pivot.index, y=cat_pivot[category], name=str(category), stackgroup="one", line=dict(width=1)))
        totals = cat_pivot.sum(axis=1)
        fig_cat.add_trace(go.Scatter(x=totals.index, y=totals.values, name="TOTAL", line=dict(color="white", width=2, dash="dot")))
        fig_cat.update_layout(
            legend=dict(orientation="h", y=1.12),
            margin=dict(l=10, r=10, t=10, b=10),
            height=330,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_cat, width="stretch")
    else:
        st.caption("No complaint data at this point in the replay.")

# ---------------------------------------------------------------------------
# CITY HEALTH TREND (Upgrade 19) with auto-detected milestones
# ---------------------------------------------------------------------------

st.markdown("**❤️ City-wide Health Trend**")
health_history = state["health_history"]
if not health_history.empty and health_history["timestamp"].nunique() >= 3:
    city_avg = health_history.groupby("timestamp")["health_score"].mean().reset_index(name="city_avg")

    fig_trend = go.Figure()
    for zone in zone_names:
        zh = health_history[health_history["zone"] == zone]
        if not zh.empty:
            fig_trend.add_trace(go.Scatter(x=zh["timestamp"], y=zh["health_score"], name=zone, line=dict(width=1.5, color="#57606f"), opacity=0.55))
    fig_trend.add_trace(
        go.Scatter(x=city_avg["timestamp"], y=city_avg["city_avg"], name="City average", line=dict(width=4, color="#00d1ff"))
    )

    # Auto-detect Event Start / Peak / Recovery from the city average curve.
    avg = city_avg.sort_values("timestamp").reset_index(drop=True)
    if len(avg) >= 6 and avg["city_avg"].std() > 1e-6:
        peak_idx = int(avg["city_avg"].idxmin())
        pre = avg.loc[: max(peak_idx - 1, 0), "city_avg"]
        post = avg.loc[peak_idx:, "city_avg"]
        start_idx = int((pre < pre.iloc[0] - 3).idxmax()) if (pre < pre.iloc[0] - 3).any() else None
        rec_idx_rel = (post > avg["city_avg"].iloc[peak_idx] + 5)
        rec_idx = int(rec_idx_rel.idxmax()) if rec_idx_rel.any() else None
        milestones = []
        if start_idx is not None:
            milestones.append((avg.loc[start_idx, "timestamp"], "Event start", "#f1c40f"))
        milestones.append((avg.loc[peak_idx, "timestamp"], "Peak stress", "#e74c3c"))
        if rec_idx is not None and rec_idx > peak_idx:
            milestones.append((avg.loc[rec_idx, "timestamp"], "Recovery", "#2ecc71"))
        for ts, label, color in milestones:
            fig_trend.add_trace(
                go.Scatter(
                    x=[ts], y=[avg.loc[avg["timestamp"] == ts, "city_avg"].iloc[0]],
                    name=label, mode="markers+text", text=[label], textposition="top center",
                    marker=dict(size=12, color=color, symbol="diamond"),
                )
            )
    fig_trend.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=300,
        legend=dict(orientation="h", y=1.12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_trend, width="stretch")
else:
    st.info("Not enough replay history yet for a city-wide health trend — advance the replay a few steps.")

chart3, chart4 = st.columns(2)

with chart3:
    st.markdown("**❤️ Civic Health Score by zone**")
    if zone_names:
        score_df = pd.DataFrame(
            [
                {"Zone": z, "Health Score": health_scores[z]["health_score"], "Status": health_scores[z]["status"]}
                for z in zone_names
            ]
        )
        fig_scores = px.bar(
            score_df, x="Zone", y="Health Score", range_y=[0, 100], color="Status",
            color_discrete_map=STATUS_COLORS, text="Health Score",
        )
        fig_scores.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=330,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_scores, width="stretch")
    else:
        st.caption("No zone data yet.")

with chart4:
    st.markdown("**🔥 Correlation heatmap**")
    if not P:
        st.caption(f"Correlations within the most recent {pipeline.CORRELATION_WINDOW} steps for {analytics_zone or '—'} (possible links, not causes).")
    if analytics_zone:
        pivot = pipeline.prepare_correlation_data(prepared["normalized"], replay_time).get(analytics_zone, pd.DataFrame())
        metrics = [m for m in ("rainfall", "traffic", "complaints") if m in pivot.columns]
        if len(metrics) >= 2:
            corr_matrix = pivot[metrics].corr()
            fig_heat = px.imshow(
                corr_matrix, text_auto=".2f", zmin=-1, zmax=1, color_continuous_scale="RdBu_r", aspect="auto"
            )
            fig_heat.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=330,
                coloraxis_showscale=False,
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_heat, width="stretch")
        else:
            st.caption("⚠️ Not enough historical data to calculate the heatmap yet.")
    else:
        st.caption("No zone selected.")

st.divider()

# ---------------------------------------------------------------------------
# CITYPULSE ASSISTANT (rule-based Q&A, fully local — Upgrade 17)
# ---------------------------------------------------------------------------

st.markdown("### 💬 CityPulse Assistant")
if not P:
    st.caption("Rule-based answers built from the current replay state — no external API.")

suggestion_cols = st.columns(5)
suggestions = [
    "What's happening?",
    f"Why is {selected_zone or 'Zone A'} at risk?",
    "Which zone needs attention?",
    "What changed recently?",
    "What might happen next?",
]
pending_question = None
for col, q in zip(suggestion_cols, suggestions):
    if col.button(q, width="stretch", key=f"suggest_{q[:20]}"):
        pending_question = q

for role, text in st.session_state.chat[-8:]:
    if role == "user":
        with st.chat_message("user", avatar="🧑"):
            st.markdown(text)
    else:
        with st.chat_message("assistant", avatar="🌆"):
            st.markdown(text)

user_q = st.chat_input("Ask about zones, alerts, possible links, risk reasons, or predictions…")
if user_q:
    pending_question = user_q

if pending_question:
    # One shared handler: suggestion chips and typed questions both get an
    # answer generated from the CURRENT replay state and selected zone.
    st.session_state.chat.append(("user", pending_question))
    st.session_state.chat.append(
        ("assistant", pipeline.answer_question(pending_question, state, selected_zone=selected_zone))
    )
    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# FOOTER / DISCLOSURES
# ---------------------------------------------------------------------------

if P:
    st.caption(
        "🌆 CityPulse prototype · synthetic fictional city · correlations are possible links, not causes · "
        "health score & event confidence are prototype indicators, not official metrics."
    )
else:
    st.caption(
        "🌆 **CityPulse** — hackathon prototype. Synthetic data for a fictional city · correlations are possible links, "
        "not proven causes · the Civic Health Score and CityPulse Event Confidence are prototype indicators, not official "
        "metrics or probabilities · predictions are prototype trend estimates, not forecasts · no personal data is used or identified."
    )

# ---------------------------------------------------------------------------
# PRESENTATION MODE TOGGLE (kept away from the demo flow) + PLAYBACK TICK
# (must be the LAST statements: the frame above has fully rendered, then we
# pause according to demo speed and schedule the next replay step)
# ---------------------------------------------------------------------------

top_toggle = st.columns([10, 2])
with top_toggle[1]:
    st.toggle("🎤 Presentation mode", key="presentation_mode")

if st.session_state.playing:
    time.sleep(DEMO_STEP_SECONDS.get(int(st.session_state.speed.rstrip("x")), 3.0))
    st.rerun()

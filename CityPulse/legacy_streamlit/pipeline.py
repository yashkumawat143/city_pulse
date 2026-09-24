"""
pipeline.py
-----------
The "backend" of CityPulse. Everything here is pure data logic — no
Streamlit, no UI code. app.py imports these functions and renders them.

Responsibilities:
    1.  load_data()                - read the three CSVs off disk
    2.  normalize_*()              - convert each dataset into a shared schema
    3.  detect_anomalies()         - flag values that are unusual vs. history
    4.  calculate_correlations()   - look for metrics moving together
    5.  calculate_health_scores()  - combine everything into a 0-100 score
    6.  generate_alerts()          - turn anomalies/correlations/risk into alerts
    7.  generate_summary()         - 1-2 sentence plain-language summary
    8.  generate_predictions()     - "what might happen next" estimates
    9.  build_timeline()           - dynamic event timeline for the replay
    10. get_current_state()        - ONE call that returns everything the UI needs
    11. answer_question()          - rule-based CityPulse Assistant

REPLAY DESIGN (very important):
    All functions that "run the pipeline as of time T" accept a
    replay_timestamp and only ever look at rows with
    timestamp <= replay_timestamp. The anomaly baseline itself is built from
    strictly-PRIOR observations only (never the current point, never the
    future), so replaying the city hour-by-hour shows exactly what a live
    system would have known at each moment — no future-data leakage.

IMPORTANT LANGUAGE RULE (do not remove):
    This pipeline never claims one metric CAUSED another. Synthetic data was
    built so rainfall, traffic, and complaints move together in Zone A, but
    correlation is not causation. All alert/summary text uses "coincides
    with", "possible link", "moving together" — never "caused", "because of",
    "resulted in", "led to".
"""

from __future__ import annotations

import os
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    ANOMALY_STD_MULTIPLIER,
    COMPLAINTS_CAP,
    CORRELATION_WINDOW,
    DATA_DIR,
    EVENT_CONFIDENCE,
    EVENT_MIN_SIGNALS,
    EVENT_WINDOW_MINUTES,
    HEALTH_BANDS,
    HEALTH_WEIGHTS,
    LAG_MINUTES,
    MIN_ANOMALY_VALUE,
    MIN_HISTORY_FOR_BASELINE,
    MODERATE_CORR,
    RAINFALL_CAP_MM,
    STRONG_CORR,
    TRAFFIC_CAP,
)
from utils import (
    classify_correlation,
    format_signed,
    pct_text,
    relationship_sentence as _relationship_sentence,
    safe_pct_difference,
    sequence_sentence as _sequence_sentence,
    strength_label as _strength_label,  # shared helper (name kept for app.py)
)

# NOTE: every tunable number used below lives in config.py, with comments
# explaining why each value was chosen. This file contains only LOGIC.

FUTURE_UPGRADE_NOTE = (
    "FUTURE UPGRADE (not needed for this MVP): Isolation Forest "
    "(sklearn.ensemble.IsolationForest) could replace the mean + 2*std rule to "
    "catch more complex, multivariate anomaly patterns (e.g. 'each signal is "
    "normal alone, but the COMBINATION is unusual'). We use a transparent "
    "statistical rule here because it is easy to explain in one sentence, which "
    "matters more for a 24-hour MVP than raw model power."
)


# ---------------------------------------------------------------------------
# 1. LOADING
# ---------------------------------------------------------------------------

def load_data(data_dir: str = DATA_DIR) -> dict[str, pd.DataFrame]:
    """
    Load weather, traffic, and complaints CSVs from disk.

    Missing or malformed files are handled gracefully: a missing file
    produces an empty DataFrame with the right columns instead of crashing
    the whole dashboard. The UI shows a friendly message instead.
    """
    expected_columns = {
        "weather": ["timestamp", "zone", "temperature", "rainfall_mm", "condition"],
        "traffic": ["timestamp", "zone", "congestion_pct", "incidents"],
        "complaints": ["timestamp", "zone", "category", "count"],
    }

    data: dict[str, pd.DataFrame] = {}
    for name, cols in expected_columns.items():
        path = os.path.join(data_dir, f"{name}.csv")
        try:
            df = pd.read_csv(path)
            if df.empty:
                df = pd.DataFrame(columns=cols)
            # Unparseable timestamps become NaT; drop those rows instead of
            # letting one bad line crash the dashboard. Parsing is kept
            # format-flexible (any reasonable timestamp style is accepted);
            # the warnings context just keeps the console output clean.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
            missing_cols = set(cols) - set(df.columns)
            if missing_cols:
                # File exists but has the wrong shape -> treat as missing.
                df = pd.DataFrame(columns=cols)
        except (FileNotFoundError, pd.errors.EmptyDataError, pd.errors.ParserError):
            df = pd.DataFrame(columns=cols)

        data[name] = df.reset_index(drop=True)

    return data


def get_available_timestamps(data: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    """All replayable timestamps, sorted, from every feed combined."""
    stamps: set[pd.Timestamp] = set()
    for df in data.values():
        if not df.empty and "timestamp" in df.columns:
            stamps.update(pd.DatetimeIndex(df["timestamp"]).dropna())
    return sorted(stamps)


def get_latest_timestamp(data: dict[str, pd.DataFrame]) -> Optional[pd.Timestamp]:
    """The newest timestamp in the data, or None if there is no data at all."""
    stamps = get_available_timestamps(data)
    return stamps[-1] if stamps else None


# ---------------------------------------------------------------------------
# 2. NORMALIZATION  (every feed -> one shared schema)
# ---------------------------------------------------------------------------
# Common schema:
#   timestamp | zone | event_type | value
#
# Example:
#   10:00 | Zone A | rainfall   | 1.5
#   10:00 | Zone A | traffic    | 32
#   10:00 | Zone A | complaints | 8
#
# With one shared schema, anomaly detection and correlation only need to be
# written ONCE, and new feeds (e.g. power outages) can be added by mapping
# them into the same shape.

def normalize_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
    """weather.csv -> common schema, using rainfall_mm as the value."""
    if weather_df.empty:
        return pd.DataFrame(columns=["timestamp", "zone", "event_type", "value"])

    out = weather_df[["timestamp", "zone", "rainfall_mm"]].copy()
    out = out.rename(columns={"rainfall_mm": "value"})
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    out["event_type"] = "rainfall"
    return out[["timestamp", "zone", "event_type", "value"]]


def normalize_traffic(traffic_df: pd.DataFrame) -> pd.DataFrame:
    """traffic.csv -> common schema, using congestion_pct as the value."""
    if traffic_df.empty:
        return pd.DataFrame(columns=["timestamp", "zone", "event_type", "value"])

    out = traffic_df[["timestamp", "zone", "congestion_pct"]].copy()
    out = out.rename(columns={"congestion_pct": "value"})
    out["value"] = pd.to_numeric(out["value"], errors="coerce").fillna(0.0)
    out["event_type"] = "traffic"
    return out[["timestamp", "zone", "event_type", "value"]]


def normalize_complaints(complaints_df: pd.DataFrame) -> pd.DataFrame:
    """
    complaints.csv -> common schema.

    Complaints arrive per-category (waterlogging, garbage, roads, ...), but
    the anomaly/correlation engines need one "how many complaints right now"
    number per (timestamp, zone). So we SUM all categories together here,
    while the raw per-category rows are kept separately in the loaded data
    for the detailed category chart in the UI.
    """
    if complaints_df.empty:
        return pd.DataFrame(columns=["timestamp", "zone", "event_type", "value"])

    grouped = (
        complaints_df.groupby(["timestamp", "zone"], as_index=False)["count"]
        .sum()
        .rename(columns={"count": "value"})
    )
    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce").fillna(0.0)
    grouped["event_type"] = "complaints"
    return grouped[["timestamp", "zone", "event_type", "value"]]


def normalize_all_data(
    weather_df: pd.DataFrame, traffic_df: pd.DataFrame, complaints_df: pd.DataFrame
) -> pd.DataFrame:
    """Combine the three normalized feeds into one long table, sorted by time."""
    frames = [
        normalize_weather(weather_df),
        normalize_traffic(traffic_df),
        normalize_complaints(complaints_df),
    ]
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return combined
    return combined.sort_values(["zone", "event_type", "timestamp"]).reset_index(drop=True)


def prepare_data(data_dir: str = DATA_DIR) -> dict[str, pd.DataFrame]:
    """
    One-call preparation: load raw feeds, normalize them, and pre-compute
    anomaly flags across the WHOLE dataset.

    Why pre-compute anomalies for all timestamps at once?
        The anomaly rule at timestamp T only uses observations strictly
        BEFORE T (an expanding baseline), so running it on the full dataset
        produces exactly the same result as running it live at each replay
        moment — but much faster. At replay time we simply filter to
        timestamp <= replay_timestamp. No future information ever flows into
        a flag, so there is no future-data leakage.
    """
    raw = load_data(data_dir)
    normalized = normalize_all_data(raw["weather"], raw["traffic"], raw["complaints"])
    anomalies = detect_anomalies(normalized)
    return {
        "weather": raw["weather"],
        "traffic": raw["traffic"],
        "complaints": raw["complaints"],
        "normalized": normalized,
        "anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# 3. ANOMALY DETECTION
# ---------------------------------------------------------------------------

def detect_anomalies(normalized_df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag anomalous readings with an EXPANDING baseline:

        baseline_mean(T) = mean of all observations BEFORE T
        baseline_std(T)  = std  of all observations BEFORE T
        anomaly          = value(T) > baseline_mean + 2 * baseline_std

    Why strictly-prior observations?
        A real civic monitoring system receives data one reading at a time
        and must never "peek into the future" to decide whether today's
        reading is unusual. Building the baseline only from prior points
        makes the replay behave exactly like a live system.

    Why mean + 2*std?
        Simple, transparent, and easy to explain to a non-technical judge:
        ~95% of a roughly normal distribution falls within 2 standard
        deviations of the mean. It is a solid MVP choice.
        {FUTURE_UPGRADE_NOTE}

    Handles edge cases:
        - insufficient history  -> never flagged (baseline too noisy)
        - zero std deviation    -> never flagged (division scale guard)
        - missing values        -> dropped before the calculation

    Adds columns: baseline_mean, baseline_std, z_score, is_anomaly
    (z_score = how many std devs above/below the baseline the value sits).
    """
    empty_with_cols = {
        "timestamp": pd.Series(dtype="datetime64[ns]"),
        "zone": pd.Series(dtype="object"),
        "event_type": pd.Series(dtype="object"),
        "value": pd.Series(dtype="float64"),
        "baseline_mean": pd.Series(dtype="float64"),
        "baseline_std": pd.Series(dtype="float64"),
        "z_score": pd.Series(dtype="float64"),
        "is_anomaly": pd.Series(dtype="bool"),
    }
    if normalized_df.empty:
        return pd.DataFrame(empty_with_cols)

    df = normalized_df.sort_values(["zone", "event_type", "timestamp"]).copy()

    mean_parts, std_parts, z_parts, flag_parts = [], [], [], []

    for (zone_key, event_type_key), group in df.groupby(["zone", "event_type"], sort=False):
        values = group["value"].astype(float)
        vals = values.reset_index(drop=True)  # clean 0..n-1 range for the math

        # shift(1) + expanding() = "statistics of everything BEFORE this row".
        # min_periods enforces our minimum-history rule automatically.
        prior_mean = vals.shift(1).expanding(min_periods=MIN_HISTORY_FOR_BASELINE).mean()
        prior_std = vals.shift(1).expanding(min_periods=MIN_HISTORY_FOR_BASELINE).std(ddof=0)

        # Guard against zero (or near-zero) std: without this, any tiny bump
        # over a perfectly flat baseline would look "infinitely" anomalous.
        usable = prior_std.notna() & (prior_std > 1e-6)
        threshold = prior_mean + ANOMALY_STD_MULTIPLIER * prior_std

        # Two-part test: statistically unusual AND practically significant.
        # See the MIN_ANOMALY_VALUE comment above for why we need both.
        min_value = MIN_ANOMALY_VALUE.get(event_type_key, 0.0)
        flag = usable & (vals > threshold) & (vals >= min_value)

        # z-score = (value - baseline_mean) / baseline_std; NaN where no baseline.
        z = (vals - prior_mean) / prior_std.where(prior_std > 1e-6)

        # Re-attach the group's original index so the final concat lines up
        # row-for-row with df (groups iterate in the same sorted order).
        idx = values.index
        mean_parts.append(prior_mean.set_axis(idx))
        std_parts.append(prior_std.set_axis(idx))
        z_parts.append(z.set_axis(idx))
        flag_parts.append(flag.set_axis(idx))

    df["baseline_mean"] = pd.concat(mean_parts)
    df["baseline_std"] = pd.concat(std_parts)
    df["z_score"] = pd.concat(z_parts)
    df["is_anomaly"] = pd.concat(flag_parts).fillna(False).astype(bool)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. CORRELATION ENGINE
# ---------------------------------------------------------------------------

def prepare_correlation_data(
    normalized_df: pd.DataFrame, current_time: pd.Timestamp, window: int = CORRELATION_WINDOW
) -> dict[str, pd.DataFrame]:
    """
    Build a per-zone pivot table (rows = timestamp, columns = rainfall /
    traffic / complaints) using only data up to current_time, restricted to
    the most recent `window` observations. Used by the correlation engine
    and by the correlation-heatmap chart in the UI.
    """
    pivots: dict[str, pd.DataFrame] = {}
    if normalized_df.empty:
        return pivots

    visible = normalized_df[normalized_df["timestamp"] <= current_time]
    for zone in sorted(visible["zone"].unique()):
        zone_df = visible[visible["zone"] == zone]
        pivot = zone_df.pivot_table(
            index="timestamp", columns="event_type", values="value", aggfunc="sum"
        )
        pivots[zone] = pivot.sort_index().tail(window)
    return pivots


def calculate_lagged_relationships(
    normalized_df: pd.DataFrame,
    current_time: pd.Timestamp,
    window: int = CORRELATION_WINDOW,
    lags_minutes: Optional[list[int]] = None,
) -> dict[str, list[dict]]:
    """
    Upgrade 2: lagged temporal relationships. For each zone and each ordered
    pair A -> B, evaluate A(t) against B(t + lag) for lag in 0 / 15 / 30
    minutes, using ONLY observations up to current_time (a lagged pair simply
    needs B's reading from `lag` minutes after A's — still never beyond
    current_time, so no future-data leakage).

    "Rainfall(t) vs Traffic(t+15)" answers: when rainfall changed, did traffic
    change ~15 minutes later? This is a TEMPORAL association, never proof of
    causation — confounders are not controlled.

    Returns {zone: [ {a, b, lag_minutes, r, n, classification, sentence}, ... ]}
    sorted by |r| descending; entries with insufficient data are omitted.
    """
    lags_minutes = lags_minutes or LAG_MINUTES
    step = pd.Timedelta(minutes=15)
    ordered_pairs = [
        ("rainfall", "traffic"),
        ("rainfall", "complaints"),
        ("traffic", "complaints"),
    ]

    results: dict[str, list[dict]] = {}
    if normalized_df.empty:
        return results

    visible = normalized_df[normalized_df["timestamp"] <= current_time]
    for zone in sorted(visible["zone"].unique()):
        zone_df = visible[visible["zone"] == zone]
        # Per-metric timestamp->value series, so we can align B at t+lag.
        # Duplicate timestamps (defensive: dirty feeds, concatenated files)
        # are collapsed to their last value — reindexing with duplicate
        # labels would otherwise raise.
        series: dict[str, pd.Series] = {}
        for metric in {m for pair in ordered_pairs for m in pair}:
            s = zone_df[zone_df["event_type"] == metric].set_index("timestamp")["value"]
            s = s[~s.index.duplicated(keep="last")]
            series[metric] = s.sort_index().tail(window + max(lags_minutes) // 15)

        zone_rows: list[dict] = []
        for a, b in ordered_pairs:
            if a not in series or b not in series:
                continue
            for lag in lags_minutes:
                shifted_b = series[b].copy()
                shifted_b.index = shifted_b.index - pd.Timedelta(minutes=lag)
                # Align A(t) with B(t+lag) on A's timestamps (union keeps the
                # pairing strict: only rows where BOTH sides exist survive).
                aligned = pd.concat([series[a], shifted_b], axis=1, join="inner").dropna()
                aligned.columns = [a, b]
                if len(aligned) >= 3 and aligned[a].std() > 1e-6 and aligned[b].std() > 1e-6:
                    r = float(aligned[a].corr(aligned[b]))
                    if not pd.isna(r):
                        zone_rows.append(
                            {
                                "a": a,
                                "b": b,
                                "lag_minutes": lag,
                                "r": round(r, 2),
                                "n": int(len(aligned)),
                                "classification": classify_correlation(r),
                                "sentence": _relationship_sentence(a, b, r, zone),
                            }
                        )
        zone_rows.sort(key=lambda row: abs(row["r"]), reverse=True)
        results[zone] = zone_rows

    return results


def calculate_correlations(
    normalized_df: pd.DataFrame, current_time: pd.Timestamp, window: int = CORRELATION_WINDOW
) -> dict[str, dict[str, Optional[float]]]:
    """
    For each zone, compute a rolling Pearson correlation (over the most
    recent `window` observations up to and INCLUDING current_time) between:

        rainfall  <-> traffic        ("rainfall_traffic")
        rainfall  <-> complaints     ("rainfall_complaints")
        traffic   <-> complaints     ("traffic_complaints")

    Returns {zone: {pair_name: r or None}}. None means there was not enough
    overlapping historical data (or one series was flat), so we refuse to
    invent a number.

    CORRELATION IS NOT CAUSATION: these numbers say two metrics moved
    together recently — nothing more. The UI and every message built on top
    of them use "possible link" wording only.
    """
    pivots = prepare_correlation_data(normalized_df, current_time, window)

    pairs = {
        "rainfall_traffic": ("rainfall", "traffic"),
        "rainfall_complaints": ("rainfall", "complaints"),
        "traffic_complaints": ("traffic", "complaints"),
    }

    results: dict[str, dict[str, Optional[float]]] = {}
    for zone, pivot in pivots.items():
        pair_results: dict[str, Optional[float]] = {key: None for key in pairs}
        for key, (col_a, col_b) in pairs.items():
            if col_a in pivot.columns and col_b in pivot.columns:
                paired = pivot[[col_a, col_b]].dropna()
                # Need a few overlapping points AND variance in both series,
                # otherwise correlation is mathematically undefined or
                # meaningless (a flat line correlates with nothing).
                if (
                    len(paired) >= 3
                    and paired[col_a].std() > 1e-6
                    and paired[col_b].std() > 1e-6
                ):
                    r = float(paired[col_a].corr(paired[col_b]))
                    if not pd.isna(r):
                        pair_results[key] = round(r, 2)
        results[zone] = pair_results

    return results


def explain_correlation(pair_key: str, r: Optional[float], zone: str) -> str:
    """Turn one correlation number into a careful plain-language sentence."""
    if r is None or pd.isna(r):
        return "⚠️ Not enough historical data to calculate this link yet."
    strength = _strength_label(r)
    direction = "moving together" if r > 0 else "moving in opposite directions"
    sentences = {
        "rainfall_traffic": f"Rainfall and traffic congestion have been {direction} in {zone}.",
        "rainfall_complaints": f"A possible link was detected between rainfall and complaint volume in {zone} — they have been {direction}.",
        "traffic_complaints": f"Traffic congestion and complaint volume have been {direction} in {zone}.",
    }
    base = sentences.get(pair_key, f"{pair_key}: {direction} in {zone}.")
    return f"{base} Recent correlation strength: **{strength}** (r = {r}). Possible link — not a confirmed cause."


# ---------------------------------------------------------------------------
# 5. EVENT CORRELATION ENGINE (multi-signal disruption detector)
# ---------------------------------------------------------------------------

def detect_event_correlations(
    anomalies_df: pd.DataFrame, current_time: pd.Timestamp, lookback_steps: int = 1
) -> dict[str, dict]:
    """
    The main event: detect when MULTIPLE signals rise around the SAME time
    in the SAME zone — the statistical fingerprint of a possible civic
    disruption:

        rainfall anomaly + traffic anomaly + complaint anomaly
            -> "possible civic disruption"

    Everything is dynamic: zone names, which signals fired, and severity
    all come from the data at replay time. Nothing is hard-coded to Zone A.

    Returns {zone: {"signals": [...], "level": "...", "timestamp": ts}} for
    zones that currently show a multi-signal pattern.
    """
    if anomalies_df.empty:
        return {}

    visible = anomalies_df[anomalies_df["timestamp"] <= current_time]
    if visible.empty:
        return {}

    cutoff = current_time - pd.Timedelta(minutes=15 * lookback_steps)
    recent = visible[visible["timestamp"] >= cutoff]
    recent = recent[recent["is_anomaly"] == True]  # noqa: E712  (dtype-safe flag check)

    events: dict[str, dict] = {}
    for zone, group in recent.groupby("zone"):
        signals = sorted(group["event_type"].unique().tolist())
        if len(signals) >= 2:
            last_ts = group["timestamp"].max()
            events[zone] = {
                "signals": signals,
                "level": "civic_disruption" if len(signals) >= 3 else "multi_signal",
                "timestamp": last_ts,
            }
    return events


# ---------------------------------------------------------------------------
# 6. CIVIC HEALTH SCORE
# ---------------------------------------------------------------------------

def calculate_health_scores(
    weather_df: pd.DataFrame,
    traffic_df: pd.DataFrame,
    complaints_df: pd.DataFrame,
    current_time: pd.Timestamp,
) -> dict[str, dict]:
    """
    CityPulse Civic Health Score — a 0-100 indicator per zone:

        100 = calm, healthy conditions      0 = severe civic stress

    Built from three severity components (each normalized to 0-100 where
    HIGHER = WORSE), combined with documented weights, then inverted:

        Traffic severity    40%  -> congestion_pct / 100
        Weather severity    30%  -> rainfall_mm / 40 mm cap
        Complaints severity 30%  -> complaints in the latest step / 20 cap

    Higher problems therefore produce a LOWER health score. The caps are
    prototype calibration choices for this synthetic city, chosen so a
    heavy-rain event clearly drops a zone into the Critical band while
    ordinary noise stays in the Healthy band.

    DISCLAIMER (shown in the UI too): a CityPulse-generated prototype
    indicator — NOT an official government metric.
    """
    scores: dict[str, dict] = {}

    zones: set[str] = set()
    for df in (weather_df, traffic_df, complaints_df):
        if not df.empty and "zone" in df.columns:
            zones.update(df["zone"].dropna().unique())

    for zone in sorted(zones):
        # --- Latest AVAILABLE observation at or before current_time ------
        # (iloc[-1] after filtering == "the most recent sensor reading a
        # live system would have received by now".)
        w = weather_df[(weather_df["zone"] == zone) & (weather_df["timestamp"] <= current_time)]
        t = traffic_df[(traffic_df["zone"] == zone) & (traffic_df["timestamp"] <= current_time)]
        c = complaints_df[(complaints_df["zone"] == zone) & (complaints_df["timestamp"] <= current_time)]

        congestion = float(t["congestion_pct"].iloc[-1]) if not t.empty else 0.0
        incidents = int(t["incidents"].iloc[-1]) if not t.empty else 0
        rainfall = float(w["rainfall_mm"].iloc[-1]) if not w.empty else 0.0
        temperature = float(w["temperature"].iloc[-1]) if not w.empty else 0.0
        condition = str(w["condition"].iloc[-1]) if not w.empty else "Unknown"

        # Complaint totals for the LATEST complaint step at/before now.
        latest_c_ts = c["timestamp"].max() if not c.empty else None
        latest_row_mask = c["timestamp"] == latest_c_ts if latest_c_ts is not None else None
        total_complaints = (
            float(c.loc[latest_row_mask, "count"].sum()) if latest_c_ts is not None else 0.0
        )
        complaints_by_category: dict[str, float] = {}
        if latest_c_ts is not None and "category" in c.columns:
            cat = c.loc[latest_row_mask].groupby("category")["count"].sum()
            complaints_by_category = {str(k): float(v) for k, v in cat.items()}

        # --- Normalize each component to 0-100 severity (higher = worse) --
        traffic_severity = float(np.clip(congestion / TRAFFIC_CAP * 100, 0, 100))
        weather_severity = float(np.clip(rainfall / RAINFALL_CAP_MM * 100, 0, 100))
        complaints_severity = float(np.clip(total_complaints / COMPLAINTS_CAP * 100, 0, 100))

        combined = (
            traffic_severity * HEALTH_WEIGHTS["traffic"]
            + weather_severity * HEALTH_WEIGHTS["weather"]
            + complaints_severity * HEALTH_WEIGHTS["complaints"]
        )
        health = float(np.clip(round(100 - combined, 1), 0, 100))

        # Interpretation bands come from config.HEALTH_BANDS (single source).
        status, emoji = next(
            (s, e) for floor, s, e in HEALTH_BANDS if health >= floor
        )

        scores[zone] = {
            "health_score": health,
            "status": status,
            "status_emoji": emoji,
            "congestion_pct": round(congestion, 1),
            "incidents": incidents,
            "rainfall_mm": round(rainfall, 1),
            "temperature": round(temperature, 1),
            "condition": condition,
            "total_complaints": int(total_complaints),
            "complaints_by_category": complaints_by_category,
            "components": {
                "traffic": round(traffic_severity, 1),
                "weather": round(weather_severity, 1),
                "complaints": round(complaints_severity, 1),
            },
        }

    return scores


# Backwards-compatible alias (earlier drafts used this name).
calculate_risk_scores = calculate_health_scores


# ---------------------------------------------------------------------------
# 7. PREDICTIONS (prototype, explainable)
# ---------------------------------------------------------------------------

def generate_predictions(
    normalized_df: pd.DataFrame,
    current_time: pd.Timestamp,
    horizon_minutes: int = 30,
) -> dict:
    """
    "What might happen next?" — a deliberately simple, explainable method:

        1. Take the last few observations up to current_time.
        2. Fit a straight line (least squares) through them.
        3. Extrapolate that line `horizon` minutes ahead.
        4. Describe the slope in words ("may continue to rise", etc.).

    A linear fit is transparent (you can draw it on a chart), needs no
    training data, and never pretends to be a forecast. Every output is
    labelled as a prototype trend estimate, NOT a certainty.

    Returns {"items": [...], "note": str} where each item is
    {zone, metric, trend, change_per_step, projected, confidence}.
    """
    lookback = 6  # last 6 steps = 90 minutes of trend
    steps_ahead = max(1, int(horizon_minutes / 15))

    trend_thresholds = {  # minimum |slope| (per 15-min step) to call a trend
        "rainfall": 1.5,
        "traffic": 2.5,
        "complaints": 0.8,
    }
    metric_titles = {"rainfall": "Rainfall", "traffic": "Traffic congestion", "complaints": "Complaint volume"}

    items: list[dict] = []
    if normalized_df.empty:
        return {"items": items, "note": "No data available for prediction."}

    visible = normalized_df[normalized_df["timestamp"] <= current_time]
    for zone in sorted(visible["zone"].unique()):
        zone_df = visible[visible["zone"] == zone]
        for metric in ("rainfall", "traffic", "complaints"):
            series = (
                zone_df[zone_df["event_type"] == metric]
                .sort_values("timestamp")["value"]
                .tail(lookback)
                .astype(float)
            )
            values = series.to_numpy()
            if len(values) < 3:
                continue

            x = np.arange(len(values), dtype=float)
            slope, _ = np.polyfit(x, values, 1)  # least-squares straight line

            # How well does the straight line explain the recent data?
            # |r| near 1 -> a clear, consistent trend; near 0 -> noisy.
            # fit_quality doubles as the displayed "trend strength".
            if np.std(values) > 1e-6:
                r = float(np.corrcoef(x, values)[0, 1])
                fit_quality = abs(r) if not pd.isna(r) else 0.0
            else:
                fit_quality = 0.0
            trend_strength = (
                "Strong" if fit_quality >= 0.8
                else "Moderate" if fit_quality >= 0.5
                else "Low"
            )

            threshold = trend_thresholds[metric]
            projected = float(values[-1] + slope * steps_ahead)
            projected = max(0.0, round(projected, 1))

            # Honest RANGE, not a single number: the estimate is projected
            # +/- 25% of the total recent move (at least +/- 1 unit), because
            # a straight-line extrapolation is a prototype estimate, not a
            # forecast. Ranges are also clipped at 0 (counts/percentages
            # cannot go negative).
            total_move = abs(slope) * steps_ahead
            band = max(1.0, 0.25 * total_move)
            range_low = max(0.0, round(projected - band, 1))
            range_high = max(0.0, round(projected + band, 1))

            # Human-readable reason: the last three interval changes.
            recent_changes = [round(values[i] - values[i - 1], 1) for i in range(len(values) - 2, len(values))]
            reason = (
                f"Recent replay intervals changed by "
                f"{', '.join(('+' if c >= 0 else '') + str(c) for c in recent_changes)}"
                f" (straight-line fit over the last {len(values)} steps)."
            )

            if slope > threshold:
                trend = "up"
                text = (
                    f"{metric_titles[metric]} in {zone} may continue to rise over the "
                    f"next {horizon_minutes} minutes (recent trend: +{slope:.1f} per 15 min)."
                )
            elif slope < -threshold:
                trend = "down"
                text = (
                    f"{metric_titles[metric]} in {zone} may start to ease over the "
                    f"next {horizon_minutes} minutes (recent trend: {slope:.1f} per 15 min)."
                )
            else:
                trend = "flat"
                text = f"{metric_titles[metric]} in {zone} is expected to remain roughly stable over the next {horizon_minutes} minutes."

            items.append(
                {
                    "zone": zone,
                    "metric": metric,
                    "metric_title": metric_titles[metric],
                    "trend": trend,
                    "change_per_step": round(float(slope), 2),
                    "projected": projected,
                    "range_low": range_low,
                    "range_high": range_high,
                    "current": round(float(values[-1]), 1),
                    "confidence": f"Trend strength: {trend_strength}",
                    "trend_strength": trend_strength,
                    "reason": reason,
                    "text": text,
                }
            )

    return {
        "items": items,
        "note": "Prototype prediction based on recent trends — not a certainty.",
    }


# ---------------------------------------------------------------------------
# 8. SMART ALERT ENGINE
# ---------------------------------------------------------------------------

def generate_alerts(
    anomalies_df: pd.DataFrame,
    correlations: dict[str, dict[str, Optional[float]]],
    health_scores: dict[str, dict],
    event_correlations: dict[str, dict],
    predictions: dict,
    current_time: pd.Timestamp,
    civic_events: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """
    Build a deduplicated, severity-sorted list of structured alerts:

        {zone, timestamp, severity, type, message}

    Types:     CivicEvent | Anomaly | Correlation | Risk | Prediction
    Severity:  Low | Moderate | High | Critical

    Language rule: correlation-based alerts use "coincides with" /
    "possible link" — never causal wording. Zone names come from the data,
    never hard-coded.
    """
    alerts: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (zone, message) -> no duplicate alerts

    def add_alert(zone: str, severity: str, alert_type: str, message: str):
        key = (zone, message)
        if key in seen:
            return
        seen.add(key)
        alerts.append(
            {
                "zone": zone,
                "timestamp": current_time,
                "severity": severity,
                "type": alert_type,
                "message": message,
            }
        )

    # --- 8a-0. CIVIC EVENT alerts (highest priority) ------------------------
    # The multi-signal civic events from detect_civic_events() become the
    # headline alerts, including the prototype confidence percentage.
    for zone, ev in (civic_events or {}).items():
        severity = "Critical" if ev["confidence"] >= 70 else "High"
        add_alert(
            zone,
            severity,
            "CivicEvent",
            f"Multi-signal civic event detected ({ev['signal_titles_str']}): "
            f"CityPulse Event Confidence {ev['confidence']:.0f}% — signals increased "
            f"in sequence within ~{ev['window_minutes']} min. Possible temporal association, "
            f"not a confirmed cause.",
        )

    # --- 8a. EVENT CORRELATION alerts (highest priority) -------------------
    # Multiple signals rising together is the headline "possible civic
    # disruption" story, so check it FIRST and word it from real data.
    signal_titles = {
        "rainfall": "heavy rainfall",
        "traffic": "increased traffic congestion",
        "complaints": "elevated complaint volume",
    }
    for zone, event in event_correlations.items():
        parts = [signal_titles[s] for s in event["signals"] if s in signal_titles]
        joined = ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else (parts[0] if parts else "multiple unusual signals")
        if event["level"] == "civic_disruption":
            message = f"Heavy rainfall coincides with increased traffic congestion and complaint volume in {zone}. A possible civic disruption may be developing."
            add_alert(zone, "Critical", "Correlation", message)
        else:
            message = f"Multiple signals — {joined} — are rising together in {zone}. A possible link was detected between these signals."
            add_alert(zone, "High", "Correlation", message)

    # --- 8b. Single-metric ANOMALY alerts -----------------------------------
    # Only the most recent reading per (zone, event_type) is considered, so
    # we don't re-alert on every historical anomaly at every replay step.
    # Magnitude floors keep the WORDING honest: a statistically anomalous but
    # tiny value (2mm rain over a near-zero baseline) should read as
    # "higher than usual", not "heavy".
    RAINFALL_HEAVY_MM = 10.0
    COMPLAINTS_NOTABLE = 5.0

    if not anomalies_df.empty:
        visible = anomalies_df[anomalies_df["timestamp"] <= current_time]
        for (zone, event_type), group in visible.groupby(["zone", "event_type"]):
            latest = group.sort_values("timestamp").iloc[-1]
            if latest["is_anomaly"] != True:  # noqa: E712  (NaN-safe flag check)
                continue
            value = float(latest["value"])
            z = latest["z_score"]

            # "Still elevated" rule: once a spike passes and the value falls
            # back toward its baseline, the anomaly flag stops firing (the
            # expanding baseline absorbs the spike), so this mostly guards
            # the transition steps. We still allow a residual value of up to
            # 60% of the floor so a RECEDING event keeps its alert visible
            # while it settles, without re-raising alerts over old noise.
            if value < MIN_ANOMALY_VALUE.get(event_type, 0.0) * 0.6:
                continue

            if event_type == "rainfall":
                if value >= RAINFALL_HEAVY_MM:
                    add_alert(zone, "Critical", "Anomaly", f"Heavy rainfall anomaly detected ({value:.1f} mm, {z:.1f} std devs above the recent baseline).")
                else:
                    add_alert(zone, "Moderate", "Anomaly", f"Rainfall is higher than usual for this time ({value:.1f} mm).")
            elif event_type == "traffic":
                add_alert(zone, "High", "Anomaly", f"Traffic congestion is significantly above its recent baseline ({value:.0f}%, {z:.1f} std devs above normal).")
            elif event_type == "complaints":
                if value >= COMPLAINTS_NOTABLE:
                    add_alert(zone, "High", "Anomaly", f"Complaint volume is unusually high ({int(value)} in the latest 15-minute window).")
                else:
                    add_alert(zone, "Moderate", "Anomaly", f"Complaint volume is slightly above its recent baseline ({int(value)} reports).")
            else:
                add_alert(zone, "Moderate", "Anomaly", f"{event_type} is significantly above its recent baseline.")

    # --- 8c. CORRELATION alerts (single strong pair, no multi-signal yet) ---
    # A rolling correlation can stay high a step or two AFTER an event, so
    # only surface these for zones that still have a live anomaly — this
    # keeps alerts aligned with what is happening RIGHT NOW.
    zones_with_live_anomaly: set[str] = set()
    if not anomalies_df.empty:
        visible = anomalies_df[anomalies_df["timestamp"] <= current_time]
        for (zone, event_type), group in visible.groupby(["zone", "event_type"]):
            if event_type in ("rainfall", "traffic"):
                latest = group.sort_values("timestamp").iloc[-1]
                if latest["is_anomaly"] == True:  # noqa: E712
                    zones_with_live_anomaly.add(zone)

    already_correlated = {a["zone"] for a in alerts if a["type"] == "Correlation"}
    for zone, pairs in correlations.items():
        if zone not in zones_with_live_anomaly or zone in already_correlated:
            continue
        strong = [name for name, r in pairs.items() if r is not None and r >= STRONG_CORR]
        if "rainfall_traffic" in strong:
            add_alert(zone, "High", "Correlation", f"Heavy rainfall coincides with increased traffic congestion in {zone}.")
        elif "rainfall_complaints" in strong:
            add_alert(zone, "High", "Correlation", f"A possible link was detected between rainfall and increased complaint volume in {zone}.")
        elif "traffic_complaints" in strong:
            add_alert(zone, "Moderate", "Correlation", f"Traffic congestion and complaint volume are moving together in {zone}.")

    # --- 8d. RISK alerts ------------------------------------------------------
    # Only Warning/Critical health scores raise alerts. The Moderate (yellow)
    # band is normal city life and is already visible on the zone cards —
    # alerting on it would cry wolf during quiet periods.
    for zone, info in health_scores.items():
        if info["status"] == "Critical":
            add_alert(zone, "Critical", "Risk", f"Civic Health Score is {info['health_score']:.0f}/100 — severe civic stress indicators in {zone}.")
        elif info["status"] == "Warning":
            add_alert(zone, "High", "Risk", f"Civic Health Score is {info['health_score']:.0f}/100 — conditions trending toward elevated risk in {zone}.")

    # --- 8e. PREDICTION alerts ------------------------------------------------
    # Only for metrics that are CURRENTLY anomalous and trending up — a
    # prediction about a calm metric is not worth an alert.
    live_anomaly_metrics: dict[str, set[str]] = {}
    if not anomalies_df.empty:
        visible = anomalies_df[anomalies_df["timestamp"] <= current_time]
        for (zone, event_type), group in visible.groupby(["zone", "event_type"]):
            latest = group.sort_values("timestamp").iloc[-1]
            if latest["is_anomaly"] == True:  # noqa: E712
                live_anomaly_metrics.setdefault(zone, set()).add(event_type)

    for item in predictions.get("items", []):
        if item["trend"] == "up" and item["metric"] in live_anomaly_metrics.get(item["zone"], set()):
            add_alert(item["zone"], "Moderate", "Prediction", item["text"])

    # Sort by severity, then by type priority, for display.
    severity_order = {"Critical": 0, "High": 1, "Moderate": 2, "Low": 3}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 4), a["type"], a["zone"]))
    return alerts


# ---------------------------------------------------------------------------
# 9. PLAIN-LANGUAGE SUMMARY (rule-based NLG — no external LLM)
# ---------------------------------------------------------------------------

def generate_summary(alerts: list[dict], health_scores: dict[str, dict]) -> str:
    """
    Produce a 1-2 sentence plain-language summary from the ACTUAL current
    alerts and scores. Rule-based: we look at which alert patterns are
    present for the worst-scoring zone and assemble sentences from fixed,
    carefully-worded templates (correlation-safe wording only).
    """
    if not health_scores:
        return "No zone data is available yet."

    if not alerts:
        return "Conditions are currently stable across all monitored zones."

    worst_zone = min(health_scores, key=lambda z: health_scores[z]["health_score"])
    zone_alerts = [a for a in alerts if a["zone"] == worst_zone] or alerts

    has_rain = any(a["type"] == "Anomaly" and "rainfall" in a["message"].lower() for a in zone_alerts)
    has_traffic = any(a["type"] == "Anomaly" and "traffic" in a["message"].lower() for a in zone_alerts)
    has_complaints = any("complaint" in a["message"].lower() for a in zone_alerts)
    has_correlation = any(a["type"] == "Correlation" for a in zone_alerts)

    parts = []
    if has_rain:
        parts.append("heavy rainfall")
    if has_traffic:
        parts.append("unusually high traffic congestion")

    if parts:
        sentence_one = f"{worst_zone} is currently experiencing " + " and ".join(parts) + "."
    else:
        score = health_scores[worst_zone]["health_score"]
        sentence_one = f"{worst_zone} currently shows the highest civic stress among monitored zones (Civic Health Score {score:.0f}/100)."

    if has_complaints and has_correlation:
        sentence_two = " Complaint volume is also elevated, with a possible link to the weather event."
    elif has_complaints:
        sentence_two = " Complaint volume is also elevated in this zone."
    elif has_correlation:
        sentence_two = " A possible link between recent weather and traffic conditions was detected."
    else:
        sentence_two = " Monitoring continues for early signs of escalation."

    return (sentence_one + sentence_two).strip()


# ---------------------------------------------------------------------------
# 10. EVENT TIMELINE (dynamic)
# ---------------------------------------------------------------------------

def build_narrative_timeline(
    anomalies_df: pd.DataFrame,
    health_history: pd.DataFrame,
    civic_events: dict[str, dict],
    current_time: pd.Timestamp,
    lookback_minutes: int = 360,
) -> list[dict]:
    """
    Upgrade 7 — "What happened?": a human-readable event log generated from
    the ACTUAL data (no hard-coded story). For every replay step in the
    lookback window we compare each zone/metric against the previous step
    and produce plain sentences for meaningful transitions:

        rainfall/traffic/complaints rose or fell notably
        anomaly flags fired
        multi-signal civic events were detected
        zone health dropped or recovered

    Returns [{time, icon, text}] sorted by time (ascending).
    """
    events: list[dict] = []
    start = current_time - pd.Timedelta(minutes=lookback_minutes)

    metric_titles = {"rainfall": "🌧 Rainfall", "traffic": "🚗 Traffic congestion", "complaints": "📢 Complaint volume"}
    rise_threshold = {"rainfall": 2.0, "traffic": 8.0, "complaints": 3.0}

    if not anomalies_df.empty:
        vis = anomalies_df[(anomalies_df["timestamp"] > start) & (anomalies_df["timestamp"] <= current_time)]
        for (zone, metric), group in vis.groupby(["zone", "metric"] if "metric" in vis.columns else ["zone", "event_type"]):
            col = "metric" if "metric" in vis.columns else "event_type"
            g = group.sort_values("timestamp")
            # Defensive: collapse duplicate timestamps (dirty feeds) to the
            # last value, otherwise index lookups below return Series.
            g = g.drop_duplicates(subset=["timestamp"], keep="last")
            vals = g.set_index("timestamp")["value"]
            prev = vals.shift(1)
            for ts, val in vals.items():
                p = prev.get(ts)
                if p is None or pd.isna(p):
                    continue
                title = metric_titles.get(metric, metric)
                if val - p >= rise_threshold.get(metric, 0):
                    events.append({"time": ts, "icon": "📈", "text": f"{title} increased in {zone} ({p:.0f} → {val:.0f})."})
                elif p - val >= rise_threshold.get(metric, 0):
                    icon = "📉" if metric != "rainfall" else "🌤"
                    events.append({"time": ts, "icon": icon, "text": f"{title} decreased in {zone} ({p:.0f} → {val:.0f})."})

        # Anomaly flag firings (only when a flag STARTS after unflagged steps).
        for (zone, metric), group in vis.groupby(["zone", "event_type"]):
            g = group.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
            prev_flag = g["is_anomaly"].shift(1).fillna(False)
            for row in g.itertuples():
                was_flagged = bool(prev_flag.get(row.Index, False)) if hasattr(row, "Index") else False
                if row.is_anomaly and not was_flagged:
                    title = metric_titles.get(metric, metric)
                    events.append({"time": row.timestamp, "icon": "⚠️", "text": f"{title} anomaly detected in {zone} ({row.value:.1f})."})

    # Civic events.
    for zone, ev in civic_events.items():
        events.append(
            {
                "time": ev.get("started", current_time),
                "icon": "🚨",
                "text": f"Multi-signal civic event detected in {zone} ({ev['signal_titles_str']}) — Event Confidence {ev['confidence']:.0f}%.",
            }
        )

    # Health transitions.
    if health_history is not None and not health_history.empty:
        hh = health_history[(health_history["timestamp"] > start) & (health_history["timestamp"] <= current_time)]
        for zone, group in hh.groupby("zone"):
            g = group.sort_values("timestamp")
            prev_score = g["health_score"].shift(1)
            for row in g.itertuples():
                p = prev_score.get(row.Index)
                if p is None or pd.isna(p):
                    continue
                delta = row.health_score - p
                if delta <= -10:
                    events.append({"time": row.timestamp, "icon": "🚨", "text": f"{zone} health score decreased sharply ({p:.0f} → {row.health_score:.0f})."})
                elif delta >= 10:
                    events.append({"time": row.timestamp, "icon": "🌤", "text": f"{zone} began recovering (health {p:.0f} → {row.health_score:.0f})."})

    # Deduplicate per (time, text), keep only meaningful entries, sort by time.
    seen: set[tuple] = set()
    unique: list[dict] = []
    for e in sorted(events, key=lambda x: x["time"]):
        key = (e["time"], e["text"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[-40:]  # cap for readability


def build_timeline(anomalies_df: pd.DataFrame, current_time: pd.Timestamp) -> list[dict]:
    """
    Build the replay's event timeline dynamically from detected anomalies.

    For every replay step we look at which anomaly flags fired at that exact
    moment (remember: flags never used future data, so the timeline is a
    faithful "what the system would have seen" log) and assign a level:

        normal      -> 🟢 Normal conditions
        single      -> 🟡/🌧 one unusual signal
        multi       -> 🟠 several signals rising together
        disruption  -> 🚨 possible civic disruption (3 signals, one zone)

    Consecutive steps with the same story are MERGED into segments
    ({start, end, level, label}) so the UI can draw a clean timeline bar
    instead of 24 near-identical rows.
    """
    if anomalies_df.empty:
        return []

    visible = anomalies_df[anomalies_df["timestamp"] <= current_time]
    flagged = visible[visible["is_anomaly"] == True]  # noqa: E712
    flags_by_ts: dict[pd.Timestamp, dict[str, list[str]]] = {}
    for ts, group in flagged.groupby("timestamp"):
        flags_by_ts[ts] = {zone: sorted(g["event_type"].tolist()) for zone, g in group.groupby("zone")}

    segments: list[dict] = []
    for ts in sorted(flags_by_ts.keys() | set(visible["timestamp"].unique())):
        zones_flags = flags_by_ts.get(ts, {})
        disruption_zones = [z for z, sig in zones_flags.items() if len(sig) >= 3]
        multi_zones = [z for z, sig in zones_flags.items() if 1 < len(sig) < 3]
        single_flags = [(z, sig[0]) for z, sig in zones_flags.items() if len(sig) == 1]

        if disruption_zones:
            level = "disruption"
            label = "🚨 Possible civic disruption — " + ", ".join(disruption_zones)
        elif multi_zones:
            level = "multi"
            label = "🟠 Multiple signals rising together — " + ", ".join(multi_zones)
        elif single_flags:
            icons = {"rainfall": "🌧", "traffic": "🚗", "complaints": "📢"}
            level = "single"
            bits = [f"{icons.get(sig, '⚠️')} {sig} unusual in {z}" for z, sig in single_flags[:2]]
            label = "🟡 " + "; ".join(bits) + (" …" if len(single_flags) > 2 else "")
        else:
            level = "normal"
            label = "🟢 Normal conditions across monitored zones"

        if segments and segments[-1]["label"] == label:
            segments[-1]["end"] = ts  # extend the current segment
        else:
            segments.append({"start": ts, "end": ts, "level": level, "label": label})

    return segments


# ---------------------------------------------------------------------------
# 11. CITYPULSE ASSISTANT (rule-based Q&A, no external API)
# ---------------------------------------------------------------------------

def answer_question(question: str, current_state: dict, selected_zone: Optional[str] = None) -> str:
    """
    The CityPulse Assistant: keyword-matched, rule-based answers built from
    the CURRENT replay state. Runs 100% locally — no external API, no LLM.
    """
    q = question.lower().strip()
    scores = current_state["health_scores"]
    alerts = current_state["alerts"]
    summary = current_state["summary"]
    predictions = current_state["predictions"]
    correlations = current_state["correlations"]
    civic_events = current_state.get("civic_events", {})
    narrative = current_state.get("narrative", [])
    zone_risk_reasons = current_state.get("zone_risk_reasons", {})
    lagged = current_state.get("lagged_relationships", {})

    zones_mentioned = [z for z in scores if z.lower() in q]
    focus_zone = zones_mentioned[0] if zones_mentioned else selected_zone

    # --- Zone-specific "why" question (v2: uses the dynamic risk reasons) ----
    if any(k in q for k in ("why", "risk", "reason")) and (zones_mentioned or focus_zone):
        zone = focus_zone
        if zone not in scores:
            return f"I don't have data for {zone} at this replay moment."
        info = scores[zone]
        lines = [f"**Why is {zone} at {info['health_score']:.0f}/100 ({info['status_emoji']} {info['status']})?**"]
        lines += [f"{i}. {r}" for i, r in enumerate(zone_risk_reasons.get(zone, ["No unusual signals."]), 1)]
        zone_alerts = [a for a in alerts if a["zone"] == zone]
        if zone_alerts:
            lines.append("")
            lines.append("**Current alerts for this zone:**")
            lines += [f"- {a['severity']}: {a['message']}" for a in zone_alerts[:4]]
        return "\n".join(lines)

    # --- Which zone needs attention? -----------------------------------------
    if any(k in q for k in ("which zone", "attention", "worst", "needs help", "focus")):
        worst = min(scores, key=lambda z: scores[z]["health_score"])
        info = scores[worst]
        return (
            f"**{worst}** needs the most attention right now "
            f"(Civic Health Score {info['health_score']:.0f}/100 — {info['status_emoji']} {info['status']}).\n\n"
            f"{summary}\n\n"
            "Civic Health Score is a CityPulse-generated prototype indicator, not an official metric."
        )

    # --- Alerts ---------------------------------------------------------------
    if "alert" in q:
        if not alerts:
            return "There are no active alerts right now — all zones are within their normal ranges."
        lines = ["**Current active alerts:**"]
        lines += [f"- {a['severity']}: {a['message']}" for a in alerts[:6]]
        return "\n".join(lines)

    # --- What changed recently? ------------------------------------------------
    if any(k in q for k in ("what changed", "changed recently", "recent change", "latest change", "history", "timeline", "what happened")):
        if not narrative:
            return "Not enough processed history yet to describe recent changes — advance the replay a few steps."
        recent = narrative[-6:]
        lines = [f"**Recent changes (latest at {recent[-1]['time']:%H:%M}):**"]
        lines += [f"- {e['time']:%H:%M} {e['icon']} {e['text']}" for e in recent]
        return "\n".join(lines)

    # --- Predictions ------------------------------------------------------------
    if any(k in q for k in ("predict", "next", "forecast", "future", "might happen")):
        items = predictions.get("items", [])
        if focus_zone:
            items = [i for i in items if i["zone"] == focus_zone] or items
        interesting = [i for i in items if i["trend"] != "flat"] or items
        lines = ["**Prototype trend-based prediction (not a certainty):**"]
        lines += [
            f"- {i['text']} Estimated range in 30 min: {i['range_low']}–{i['range_high']} ({i['confidence']})."
            for i in interesting[:5]
        ]
        return "\n".join(lines)

    # --- Correlations -----------------------------------------------------------
    if any(k in q for k in ("correl", "link", "related", "relationship")):
        lines = ["**Possible links detected (correlation, not causation):**"]
        any_found = False
        for zone, pairs in correlations.items():
            for pair, r in pairs.items():
                if r is not None and abs(r) >= MODERATE_CORR:
                    pair_name = pair.replace("_", " ↔ ")
                    lines.append(f"- {zone}: {pair_name} — r = {r} ({_strength_label(r)})")
                    any_found = True
        if not any_found:
            lines.append("- ⚠️ Not enough historical data to calculate meaningful links yet at this point in the replay.")
        return "\n".join(lines)

    # --- Zone status --------------------------------------------------------------
    if zones_mentioned:
        zone = zones_mentioned[0]
        info = scores[zone]
        corr = correlations.get(zone, {})
        strongest = max((v for v in corr.values() if v is not None), default=None)
        corr_bit = (
            f" The strongest recent correlation in this zone is r = {strongest} (a possible link, not a confirmed cause)."
            if strongest is not None else ""
        )
        return (
            f"**{zone} right now:** {info['status_emoji']} {info['status']} — Civic Health Score {info['health_score']:.0f}/100.\n"
            f"- 🌧 Weather: {info['condition']}, {info['rainfall_mm']:.1f} mm rain\n"
            f"- 🚗 Traffic: {info['congestion_pct']:.0f}% congestion, {info['incidents']} incident(s)\n"
            f"- 📢 Complaints: {info['total_complaints']} in the latest window{corr_bit}"
        )

    # --- What is happening? (v2: civic-event aware) --------------------------------
    if any(k in q for k in ("happening", "current", "situation", "status", "overview", "summary")) or q:
        if civic_events:
            lines = [summary, ""]
            for zone, ev in civic_events.items():
                lines.append(
                    f"🚨 **Civic event in {zone}** — {ev['signal_titles_str']}: these signals overlap within the current "
                    f"event window (CityPulse Event Confidence {ev['confidence']}%, status: {ev['status']}). "
                    f"Signals increased in sequence — a temporal association, not a confirmed cause."
                )
            lines.append("")
            lines.append("*Ask \"Why is this zone at risk?\", \"What changed recently?\" or \"What might happen next?\" for detail.*")
            return "\n".join(lines)
        return summary + "\n\n*Ask about a specific zone (e.g. \"Why is Zone B at risk?\"), alerts, predictions, or possible links for more detail.*"

    return "I can answer questions about zone status, active alerts, possible links, risk reasons, and short-term predictions. Try: *\"What is happening in Zone A?\"*"


# ---------------------------------------------------------------------------
# 11b. V2.0 ANALYSIS: baselines, civic events, zone risk, city status
# ---------------------------------------------------------------------------

def get_historical_data(df: pd.DataFrame, current_time: pd.Timestamp) -> pd.DataFrame:
    """
    Upgrade 8: the ONLY way analysis code sees history. Returns rows with
    timestamp <= current_time (empty-safe). Every v2.0 feature routes
    through this helper so future-data leakage is structurally impossible.
    """
    if df is None or df.empty or "timestamp" not in df.columns:
        return df
    return df[df["timestamp"] <= current_time]


def collect_anomalies_now(
    latest_anomalies: dict[tuple[str, str], dict], current_time: pd.Timestamp
) -> dict[str, dict[str, dict]]:
    """
    Keep only LIVE anomalies: the zone/metric's most recent observation is
    exactly at the replay moment AND flagged. Grouped {zone: {metric: info}}
    for the diagnostic cards, city status counters, and zone-risk reasons.
    """
    out: dict[str, dict[str, dict]] = {}
    for (zone, metric), info in latest_anomalies.items():
        if info["is_anomaly"] and info["timestamp"] == current_time:
            out.setdefault(zone, {})[metric] = {
                "value": info["value"],
                "baseline_mean": info["baseline_mean"],
                "z_score": info["z_score"],
            }
    return out


def baseline_comparisons(
    latest_anomalies: dict[tuple[str, str], dict], zone: str, current_time: pd.Timestamp
) -> dict[str, dict]:
    """
    Upgrades 9 + 10 data layer: for every metric of one zone, compare the
    CURRENT value against its NORMAL BASELINE (the mean of prior
    observations) with a safe difference and percentage. Percentage is None
    when the baseline is ~0 (a % on a zero baseline would mislead; we show
    the absolute deviation instead). Never divides by zero.
    """
    units = {"rainfall": " mm", "traffic": "%", "complaints": ""}
    out: dict[str, dict] = {}
    for (z, metric), info in latest_anomalies.items():
        if z != zone or info["timestamp"] != current_time:
            continue
        baseline = info["baseline_mean"]
        current = info["value"]
        pct = safe_pct_difference(current, baseline) if baseline is not None else None
        out[metric] = {
            "current": current,
            "baseline": baseline,
            "difference": None if baseline is None else current - baseline,
            "pct": pct,
            "z_score": info["z_score"],
            "is_anomaly": info["is_anomaly"],
            "unit": units.get(metric, ""),
        }
    return out


def detect_civic_events(
    df: pd.DataFrame, current_time: pd.Timestamp, active_zones: Optional[list[str]] = None
) -> dict[str, dict]:
    """
    Upgrade 1 — CIVIC EVENT DETECTION.

    Detects a higher-level civic event: multiple anomalous SIGNALS in the
    SAME zone, within ~30 minutes of each other, across different types
    (rainfall / traffic / complaints / incidents). Four explainable factors
    feed the CityPulse Event Confidence (an INTERNAL PROTOTYPE score —
    explicitly NOT a probability of any real-world event):

        1. Anomaly strength    mean |z-score| of the signals
        2. Signal diversity    2 signals = base evidence, 3+ = stronger
        3. Temporal proximity  tightly clustered signals add confidence
        4. Persistence         repeatedly abnormal steps beat a lone spike

    All analysis uses get_historical_data (timestamp <= current_time) — the
    event detection itself can never peek into the future.

    Returns {zone: event_dict} for zones with >= EVENT_MIN_SIGNALS signals.
    """
    if df is None or df.empty or not {"timestamp", "zone", "event_type", "value"}.issubset(df.columns):
        return {}

    flags = detect_anomalies(get_historical_data(df, current_time))
    if flags.empty:
        return {}

    flagged = flags[flags["is_anomaly"] == True]  # noqa: E712
    window_start = current_time - pd.Timedelta(minutes=EVENT_WINDOW_MINUTES)
    recent = flagged[flagged["timestamp"] >= window_start]
    if recent.empty:
        return {}

    events: dict[str, dict] = {}
    titles = {"rainfall": "Rainfall", "traffic": "Traffic", "complaints": "Complaints", "incidents": "Incidents"}
    conf_c = EVENT_CONFIDENCE

    for zone, group in recent.groupby("zone"):
        if active_zones is not None and zone not in active_zones:
            continue
        metrics = sorted(group["event_type"].unique())
        if len(metrics) < EVENT_MIN_SIGNALS:
            continue

        # --- Per-signal diagnostics (strength + persistence) ---------------
        signals: list[dict] = []
        first_flag_time: dict[str, pd.Timestamp] = {}
        for metric in metrics:
            g = group[group["event_type"] == metric].sort_values("timestamp")
            latest = g.iloc[-1]
            z = float(latest["z_score"]) if pd.notna(latest["z_score"]) else 0.0

            metric_flags = flags[(flags["zone"] == zone) & (flags["event_type"] == metric)].sort_values("timestamp")
            first_flag_time[metric] = metric_flags[metric_flags["is_anomaly"] == True][  # noqa: E712
                "timestamp"
            ].min()
            # Persistence: consecutive abnormal steps ending at the latest.
            consecutive = 0
            for flag in metric_flags["is_anomaly"].iloc[::-1]:
                if flag:
                    consecutive += 1
                else:
                    break

            signals.append(
                {
                    "metric": metric,
                    "title": titles.get(metric, metric),
                    "z_score": z,
                    "value": float(latest["value"]),
                    "baseline": None if pd.isna(latest["baseline_mean"]) else float(latest["baseline_mean"]),
                    "last_time": latest["timestamp"],
                    "consecutive_steps": consecutive,
                }
            )

        # --- Temporal proximity --------------------------------------------
        times = [s["last_time"] for s in signals]
        spread_minutes = int((max(times) - min(times)).total_seconds() / 60.0)
        mean_z = float(np.mean([abs(s["z_score"]) for s in signals])) if signals else 0.0
        max_persistence = max(s["consecutive_steps"] for s in signals)

        # --- CityPulse Event Confidence (prototype score, capped < 100%) ---
        confidence = conf_c["base"]
        confidence += conf_c["per_extra_signal"] * max(0, len(signals) - 2)
        confidence += min(conf_c["max_strength_bonus"], (mean_z / 6.0) * conf_c["max_strength_bonus"])
        confidence += min(conf_c["persistence_cap"], max(0, (max_persistence - 1)) * conf_c["per_persistent_step"])
        if spread_minutes <= 15:
            confidence += conf_c["tight_window_bonus"]
        elif spread_minutes <= EVENT_WINDOW_MINUTES:
            confidence += conf_c["spread_window_bonus"]
        confidence = float(np.clip(confidence, 0, conf_c["cap"]))

        latest_signal_time = max(times)
        status = (
            "Developing"
            if latest_signal_time >= current_time - pd.Timedelta(minutes=15)
            else "Ongoing"
        )

        ordered = sorted(first_flag_time, key=lambda m: first_flag_time[m])
        sequence = " → ".join(titles.get(m, m) for m in ordered)

        events[zone] = {
            "zone": zone,
            "signals": metrics,
            "signal_titles_str": " + ".join(titles.get(m, m) for m in metrics),
            "confidence": round(confidence),
            "window_minutes": EVENT_WINDOW_MINUTES,
            "spread_minutes": spread_minutes,
            "mean_z": round(mean_z, 2),
            "max_persistence": max_persistence,
            "started": min(first_flag_time.values()),
            "last_signal_time": latest_signal_time,
            "status": status,
            "sequence": sequence,
            "signal_details": signals,
        }

    return events


def explain_zone_risk(
    zone: str,
    info: dict,
    zone_anomalies: dict[str, dict],
    zone_lagged: list[dict],
    civic_event: Optional[dict],
    current_time: pd.Timestamp,
) -> list[str]:
    """
    Upgrade 5 — "Why is this zone at risk?": numbered, fully dynamic reasons
    derived from the zone's own current data. Works for Zone A, B, C and any
    future zone — nothing is hard-coded. Correlation wording is
    direction-aware and never implies causation.
    """
    titles = {"rainfall": "Rainfall", "traffic": "Traffic congestion", "complaints": "Complaint volume"}
    units = {"rainfall": " mm", "traffic": "%", "complaints": ""}
    reasons: list[str] = []

    for metric, a in zone_anomalies.items():
        title = titles.get(metric, metric)
        baseline = a["baseline_mean"]
        current = a["value"]
        if baseline is None:
            reasons.append(f"{title} is unusual for this time of day ({current:.1f}{units.get(metric, '')}) — not enough history for a baseline comparison yet.")
            continue
        pct = safe_pct_difference(current, baseline)
        if pct is None:
            reasons.append(
                f"{title} is {format_signed(current - baseline, units.get(metric, ''), 1)} above its recent baseline "
                f"({current:.1f} vs {baseline:.1f}) — baseline too small for a % comparison."
            )
        else:
            reasons.append(
                f"{title} is {pct_text(pct)} above its recent baseline ({current:.1f} vs {baseline:.1f}{units.get(metric, '')})."
            )

    if civic_event:
        reasons.append(
            f"Multiple abnormal signals ({civic_event['signal_titles_str']}) overlap within the same "
            f"~{civic_event['window_minutes']}-minute event window — signals increased in sequence "
            f"(CityPulse Event Confidence {civic_event['confidence']:.0f}%)."
        )

    strong = [r for r in zone_lagged if abs(r["r"]) >= STRONG_CORR]
    if strong:
        top = strong[0]
        a_title = titles.get(top["a"], top["a"])
        b_title = titles.get(top["b"], top["b"])
        if top["lag_minutes"] > 0 and top["r"] > 0.20:
            reasons.append(
                f"{a_title} changes preceded {b_title} changes by approximately {top['lag_minutes']} minutes "
                f"(r = {top['r']}, possible temporal association — not a confirmed cause)."
            )
        else:
            reasons.append(
                f"{a_title} and {b_title} show a {top['classification'].lower()} relationship "
                f"in the current window (r = {top['r']}, temporal association only)."
            )

    if not reasons:
        reasons.append("No metric is currently beyond its normal baseline — conditions look stable for this zone.")

    reasons.append(
        f"Current Civic Health Score: {info['health_score']:.0f}/100 ({info['status']}) — a CityPulse prototype indicator, not an official metric."
    )
    return reasons


def calculate_city_status(
    health_scores: dict[str, dict], alerts: list[dict], anomalies_now: dict[str, dict[str, dict]]
) -> dict:
    """
    Upgrade 6 — high-level CITY STATUS banner data, updated every replay step.
    "ATTENTION REQUIRED" is a CityPulse prototype label, not an official
    government classification (the UI displays the disclaimer).
    """
    stable_zones = [z for z, i in health_scores.items() if i["status"] in ("Healthy", "Moderate")]
    at_risk_zones = [z for z, i in health_scores.items() if i["status"] in ("Warning", "Critical")]

    counts = {
        "weather_events": sum(1 for z in anomalies_now if "rainfall" in anomalies_now[z]),
        "traffic_anomalies": sum(1 for z in anomalies_now if "traffic" in anomalies_now[z]),
        "complaint_spikes": sum(1 for z in anomalies_now if "complaints" in anomalies_now[z]),
    }
    has_problem = bool(at_risk_zones) or bool(alerts) or any(counts.values())
    return {
        "level": "ATTENTION REQUIRED" if has_problem else "STABLE",
        "emoji": "🟡" if has_problem else "🟢",
        "stable_zones": stable_zones,
        "at_risk_zones": at_risk_zones,
        "active_alerts": len(alerts),
        **counts,
    }


def compute_health_history(prepared: dict[str, pd.DataFrame], current_time: pd.Timestamp) -> pd.DataFrame:
    """
    Upgrade 13 data layer: per-zone Civic Health Score at EVERY replay step
    up to current_time (each step uses only its own past — consistent with
    the replay contract). Feeds the city-wide health trend chart.
    """
    weather, traffic, complaints = prepared["weather"], prepared["traffic"], prepared["complaints"]
    if weather.empty or traffic.empty or complaints.empty:
        return pd.DataFrame(columns=["timestamp", "zone", "health_score", "status"])

    stamps = sorted(
        set(weather["timestamp"].unique()) & set(traffic["timestamp"].unique()) & set(complaints["timestamp"].unique())
    )
    rows: list[dict] = []
    for ts in stamps:
        if ts > current_time:
            break
        scores = calculate_health_scores(
            weather[weather["timestamp"] <= ts],
            traffic[traffic["timestamp"] <= ts],
            complaints[complaints["timestamp"] <= ts],
            ts,
        )
        for zone, info in scores.items():
            rows.append({"timestamp": ts, "zone": zone, "health_score": info["health_score"], "status": info["status"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 12. ONE-CALL REPLAY-AWARE STATE
# ---------------------------------------------------------------------------

def get_current_state(prepared: dict[str, pd.DataFrame], replay_timestamp: Optional[pd.Timestamp] = None) -> dict:
    """
    The single function the UI calls every replay tick. Everything inside
    uses ONLY data with timestamp <= replay_timestamp (or the latest
    timestamp when replay_timestamp is None), so the dashboard behaves like
    a system receiving data in real time.

    Returns a dict with: replay_time, visible data slices, latest
    observations per zone, health scores, anomalies (latest flags),
    correlations, event correlations, alerts, summary, predictions, timeline
    segments, and the list of complaint categories present in the data.
    """
    weather = prepared["weather"]
    traffic = prepared["traffic"]
    complaints = prepared["complaints"]
    normalized = prepared["normalized"]
    anomalies = prepared["anomalies"]

    if replay_timestamp is None:
        replay_timestamp = get_latest_timestamp(prepared)

    visible_weather = weather[weather["timestamp"] <= replay_timestamp] if not weather.empty else weather
    visible_traffic = traffic[traffic["timestamp"] <= replay_timestamp] if not traffic.empty else traffic
    visible_complaints = complaints[complaints["timestamp"] <= replay_timestamp] if not complaints.empty else complaints

    health_scores = calculate_health_scores(visible_weather, visible_traffic, visible_complaints, replay_timestamp)
    correlations = calculate_correlations(normalized, replay_timestamp)
    lagged = calculate_lagged_relationships(normalized, replay_timestamp)
    event_correlations = detect_event_correlations(anomalies, replay_timestamp)
    civic_events = detect_civic_events(normalized, replay_timestamp)
    predictions = generate_predictions(normalized, replay_timestamp)
    alerts = generate_alerts(
        anomalies, correlations, health_scores, event_correlations, predictions, replay_timestamp,
        civic_events=civic_events,
    )
    summary = generate_summary(alerts, health_scores)
    timeline = build_timeline(anomalies, replay_timestamp)

    # Latest raw anomaly rows (for the UI's "how unusual" tooltips).
    latest_anomalies: dict[tuple[str, str], dict] = {}
    if not anomalies.empty:
        vis = anomalies[anomalies["timestamp"] <= replay_timestamp]
        for (zone, event_type), group in vis.groupby(["zone", "event_type"]):
            latest = group.sort_values("timestamp").iloc[-1]
            latest_anomalies[(zone, event_type)] = {
                "value": float(latest["value"]),
                "baseline_mean": None if pd.isna(latest["baseline_mean"]) else float(latest["baseline_mean"]),
                "baseline_std": None if pd.isna(latest["baseline_std"]) else float(latest["baseline_std"]),
                "z_score": None if pd.isna(latest["z_score"]) else float(latest["z_score"]),
                "is_anomaly": bool(latest["is_anomaly"]),
                "timestamp": latest["timestamp"],
            }

    # --- v2.0 additions (all replay-aware, all data-derived) ----------------
    anomalies_now = collect_anomalies_now(latest_anomalies, replay_timestamp)
    health_history = compute_health_history(prepared, replay_timestamp)
    narrative = build_narrative_timeline(anomalies, health_history, civic_events, replay_timestamp)

    zone_risk_reasons = {
        zone: explain_zone_risk(
            zone,
            info,
            anomalies_now.get(zone, {}),
            lagged.get(zone, []),
            civic_events.get(zone),
            replay_timestamp,
        )
        for zone, info in health_scores.items()
    }

    city_status = calculate_city_status(health_scores, alerts, anomalies_now)

    categories = (
        sorted(complaints["category"].dropna().unique().tolist()) if not complaints.empty and "category" in complaints.columns else []
    )

    return {
        "replay_time": replay_timestamp,
        "visible_weather": visible_weather,
        "visible_traffic": visible_traffic,
        "visible_complaints": visible_complaints,
        "health_scores": health_scores,
        "latest_anomalies": latest_anomalies,
        "correlations": correlations,
        "lagged_relationships": lagged,
        "event_correlations": event_correlations,
        "civic_events": civic_events,
        "anomalies_now": anomalies_now,
        "zone_risk_reasons": zone_risk_reasons,
        "city_status": city_status,
        "health_history": health_history,
        "predictions": predictions,
        "alerts": alerts,
        "summary": summary,
        "timeline": timeline,
        "narrative": narrative,
        "categories": categories,
    }

"""
simulation.py
-------------
Synthetic city data generation for CityPulse (moved here from
generate_data.py in v2.0 so the simulation is importable — demo tooling and
tests can generate data without the CLI).

The generator is UNCHANGED from v1.0: same seed, same constants, same
distributions, same rain -> traffic (15-min lag) -> complaints story, so
every previously generated CSV and every replay result reproduces exactly.
"""

import os

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# GLOBAL CONFIG
# ---------------------------------------------------------------------------

# Fixed seed -> identical "random" data every time the script runs.
np.random.seed(42)

ZONES = ["Zone A", "Zone B", "Zone C"]

# 6 hours of data at 15-minute resolution = 24 timestamps.
START_TIME = pd.Timestamp("2026-09-24 10:00")
NUM_STEPS = 24
FREQ_MINUTES = 15

# The deliberate rainfall event happens around "hour 3" of the window.
# Hour 3 = 12 steps in (since each step is 15 minutes -> 4 steps/hour).
# We ramp the event up over a few steps, hold near-peak, then taper off,
# so it reads naturally on the replay slider instead of appearing/vanishing
# instantly.
EVENT_ZONE = "Zone A"
EVENT_START_STEP = 10   # 12:30 - rain starts building
EVENT_PEAK_STEPS = range(12, 15)   # 13:00 - 13:30 - heaviest rain
EVENT_END_STEP = 17     # 14:15 - back to near-normal

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def generate_timestamps() -> pd.DatetimeIndex:
    """Build the shared 15-minute timestamp index used by all three datasets."""
    return pd.date_range(start=START_TIME, periods=NUM_STEPS, freq=f"{FREQ_MINUTES}min")


def _rainfall_condition(rainfall_mm: float) -> str:
    """Map a rainfall amount to a human-readable weather condition label."""
    if rainfall_mm < 0.5:
        return "Clear"
    elif rainfall_mm < 2:
        return "Cloudy"
    elif rainfall_mm < 10:
        return "Light Rain"
    else:
        return "Heavy Rain"


def generate_weather(timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Generate weather.csv contents.

    Normal conditions: small random fluctuation in temperature and a light,
    mostly-dry rainfall baseline (0-3mm, mimicking occasional light drizzle
    noise a real sensor feed would show).

    Deliberate event: Zone A gets a rainfall spike that ramps up from ~2mm
    to a 20-35mm peak, then tapers back down. Zone B and Zone C are left
    at their normal baseline the entire time, which is what lets the
    dashboard later show "Zone A is the anomaly, not the whole city."
    """
    rows = []
    for step, ts in enumerate(timestamps):
        for zone in ZONES:
            # Normal baseline: each zone has a slightly different "climate"
            # so the demo doesn't look like every zone is a clone of another.
            base_temp = {"Zone A": 30.0, "Zone B": 29.0, "Zone C": 31.5}[zone]
            temperature = round(base_temp + np.random.normal(0, 0.6), 1)

            # Baseline rainfall noise: mostly near zero with small variation.
            rainfall = max(0.0, np.random.normal(0.5, 0.6))

            if zone == EVENT_ZONE:
                if step in EVENT_PEAK_STEPS:
                    # Heaviest part of the storm.
                    rainfall = np.random.uniform(20, 35)
                elif EVENT_START_STEP <= step < min(EVENT_PEAK_STEPS):
                    # Ramp-up: rain building steadily toward the peak.
                    progress = (step - EVENT_START_STEP + 1) / (
                        min(EVENT_PEAK_STEPS) - EVENT_START_STEP + 1
                    )
                    rainfall = np.random.uniform(3, 20) * progress + np.random.uniform(1, 3)
                elif max(EVENT_PEAK_STEPS) < step <= EVENT_END_STEP:
                    # Taper-off: rain easing back toward baseline.
                    progress = (EVENT_END_STEP - step + 1) / (
                        EVENT_END_STEP - max(EVENT_PEAK_STEPS) + 1
                    )
                    rainfall = np.random.uniform(5, 18) * progress + np.random.uniform(0.5, 2)
                # Rain slightly cools the air during the event.
                if rainfall > 5:
                    temperature = round(temperature - np.random.uniform(1.5, 3.5), 1)

            rainfall = round(rainfall, 1)
            condition = _rainfall_condition(rainfall)

            rows.append(
                {
                    "timestamp": ts,
                    "zone": zone,
                    "temperature": temperature,
                    "rainfall_mm": rainfall,
                    "condition": condition,
                }
            )

    return pd.DataFrame(rows)


def generate_traffic(weather_df: pd.DataFrame, timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Generate traffic.csv contents, driven partly by the weather data.

    Design choice: congestion in Zone A responds to rainfall with a short
    lag (drivers slow down / accidents cluster a little AFTER rain starts,
    not the exact same instant), which is more realistic and also gives the
    replay slider a nice "cause seems to ripple forward in time" feel
    without the code ever claiming causation.
    """
    # Index weather by (timestamp, zone) for quick lookup while building traffic rows.
    weather_lookup = weather_df.set_index(["timestamp", "zone"])["rainfall_mm"]

    rows = []
    # Track each zone's rainfall history so we can apply a 1-step lag effect.
    rainfall_history = {zone: [] for zone in ZONES}

    for step, ts in enumerate(timestamps):
        for zone in ZONES:
            base_congestion = {"Zone A": 32.0, "Zone B": 28.0, "Zone C": 25.0}[zone]
            congestion = base_congestion + np.random.normal(0, 4)
            incidents = np.random.poisson(0.3)

            rainfall_history[zone].append(weather_lookup[(ts, zone)])

            if zone == EVENT_ZONE and len(rainfall_history[zone]) > 1:
                # Use the PREVIOUS step's rainfall (a 1-step / 15-minute lag)
                # so traffic visibly responds to rain rather than moving in
                # perfect lockstep with it.
                lagged_rainfall = rainfall_history[zone][-2]
                if lagged_rainfall > 5:
                    # Heavier recent rain -> noticeably worse congestion.
                    congestion += lagged_rainfall * 1.6 + np.random.uniform(5, 15)
                    incidents += np.random.poisson(1.2)

            congestion = float(np.clip(congestion, 0, 100))
            rows.append(
                {
                    "timestamp": ts,
                    "zone": zone,
                    "congestion_pct": round(congestion, 1),
                    "incidents": int(incidents),
                }
            )

    return pd.DataFrame(rows)


def generate_complaints(
    weather_df: pd.DataFrame, traffic_df: pd.DataFrame, timestamps: pd.DatetimeIndex
) -> pd.DataFrame:
    """
    Generate complaints.csv contents.

    Each (timestamp, zone) gets a row per category. Counts are drawn from
    a Poisson distribution (a standard way to model "number of discrete
    events in a fixed time window", which is exactly what a complaint
    count is).

    During the Zone A rain event:
      - waterlogging complaints spike heavily (the most directly
        weather-linked category)
      - roads and noise complaints rise modestly (plausible knock-on
        effects of worse traffic)
      - garbage and streetlight complaints stay at baseline (unrelated
        categories, included so the correlation engine has to actually
        distinguish signal from noise instead of "everything goes up")
    """
    categories = ["waterlogging", "garbage", "roads", "streetlight", "noise"]

    weather_lookup = weather_df.set_index(["timestamp", "zone"])["rainfall_mm"]
    traffic_lookup = traffic_df.set_index(["timestamp", "zone"])["congestion_pct"]

    baseline_means = {
        "waterlogging": 0.4,
        "garbage": 1.2,
        "roads": 0.8,
        "streetlight": 0.5,
        "noise": 0.9,
    }

    rows = []
    for ts in timestamps:
        for zone in ZONES:
            rainfall = weather_lookup[(ts, zone)]
            congestion = traffic_lookup[(ts, zone)]

            for category in categories:
                mean = baseline_means[category]

                if zone == EVENT_ZONE:
                    if category == "waterlogging" and rainfall > 5:
                        # Strong, direct response to rainfall severity.
                        mean = baseline_means[category] + rainfall * 0.35
                    elif category in ("roads", "noise") and congestion > 45:
                        # Smaller, indirect bump tied to worse traffic.
                        mean = baseline_means[category] + (congestion - 45) * 0.05

                count = int(np.random.poisson(max(mean, 0.05)))
                rows.append(
                    {
                        "timestamp": ts,
                        "zone": zone,
                        "category": category,
                        "count": count,
                    }
                )

    return pd.DataFrame(rows)


def simulate() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Generate the full synthetic city snapshot (weather, traffic, complaints)
    in memory. Reproducible: fixed seed, deterministic ordering.
    """
    np.random.seed(42)
    timestamps = generate_timestamps()
    weather = generate_weather(timestamps)
    traffic = generate_traffic(weather, timestamps)
    complaints = generate_complaints(weather, traffic, timestamps)
    return weather, traffic, complaints


def write_data(data_dir: str = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate the synthetic city and write the three CSVs to data_dir."""
    os.makedirs(data_dir, exist_ok=True)
    weather, traffic, complaints = simulate()
    weather.to_csv(os.path.join(data_dir, "weather.csv"), index=False)
    traffic.to_csv(os.path.join(data_dir, "traffic.csv"), index=False)
    complaints.to_csv(os.path.join(data_dir, "complaints.csv"), index=False)
    return weather, traffic, complaints

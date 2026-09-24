"""
config.py
---------
Single source of truth for every tunable constant in CityPulse.

All numbers that shape the system's behavior live here with a comment
explaining WHY each value was chosen — so judges (and future you) can see
exactly how the system is calibrated without hunting through logic code.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

# Minimum number of PRIOR observations required before we trust a baseline
# enough to call something an anomaly. Too few points -> mean/std are noisy
# and we would flag false positives constantly.
MIN_HISTORY_FOR_BASELINE = 4

# How many standard deviations above the mean counts as "anomalous".
# 2 std devs is a common, easy-to-explain statistical convention: under a
# roughly normal distribution, about 95% of values fall within 2 standard
# deviations of the mean, so anything beyond that is genuinely unusual
# rather than ordinary noise.
ANOMALY_STD_MULTIPLIER = 2.0

# PRACTICAL-SIGNIFICANCE FLOORS (one value per metric).
#
# A reading is only flagged as an anomaly if it clears BOTH tests:
#   1. Statistical significance: value > baseline_mean + 2 * baseline_std
#   2. Practical significance:   value >= the floor below
#
# Why both? Early in a replay the baseline is short and nearly flat, so its
# standard deviation is tiny — a completely ordinary blip (1.6 mm of drizzle,
# or congestion moving 40% -> 43%) can produce a huge z-score. Requiring a
# minimum absolute magnitude as well is standard monitoring practice: a
# deviation must be BOTH statistically unusual AND large enough to matter
# for citizens before we call it an anomaly. It also keeps the alert list
# focused on real events instead of noise.
MIN_ANOMALY_VALUE = {
    "rainfall": 3.0,     # below ~3 mm per 15 min is drizzle noise
    "traffic": 45.0,     # below ~45% congestion is normal city flow
    "complaints": 10.0,  # fewer than ~10 reports per 15 min is routine volume
}

# ---------------------------------------------------------------------------
# Correlation engine
# ---------------------------------------------------------------------------

# Rolling window (number of 15-minute steps) for correlation math.
CORRELATION_WINDOW = 6

# Correlation strength bands for the human-readable labels.
STRONG_CORR = 0.7    # |r| >= 0.7 -> "Strong"
MODERATE_CORR = 0.4  # |r| >= 0.4 -> "Moderate", below that -> "Weak"

# ---------------------------------------------------------------------------
# Lagged temporal relationships (Upgrade 2)
# ---------------------------------------------------------------------------

# Lags (in minutes) evaluated for A(t) -> B(t + lag). 15 minutes = one
# replay step in this dataset.
LAG_MINUTES = [0, 15, 30]

# ---------------------------------------------------------------------------
# Civic event detection (Upgrade 1) — CityPulse Event Confidence
# ---------------------------------------------------------------------------

# Signals within the same zone and inside this window (minutes) can combine
# into one civic event.
EVENT_WINDOW_MINUTES = 30

# Minimum distinct signal types required to call something a civic event
# (1 anomalous signal = weak evidence, not an event).
EVENT_MIN_SIGNALS = 2

# CityPulse Event Confidence is an INTERNAL PROTOTYPE score built from four
# explainable components (NOT a probability of any real-world event):
#   base        -> two signals already overlapping is meaningful evidence
#   diversity   -> each extra distinct signal type adds confidence
#   strength    -> how far values deviate from their baselines (mean z-score)
#   persistence -> repeatedly abnormal steps beat one isolated spike
#   proximity   -> signals clustered tightly in time raise confidence
EVENT_CONFIDENCE = {
    "base": 40.0,
    "per_extra_signal": 12.0,     # added for each signal beyond the 2nd
    "max_strength_bonus": 25.0,   # scaled from mean |z| (capped at z=6)
    "per_persistent_step": 5.0,   # added per consecutive abnormal step, capped
    "persistence_cap": 15.0,
    "tight_window_bonus": 10.0,   # all signals within 15 minutes of each other
    "spread_window_bonus": 5.0,   # signals within 30 minutes
    "cap": 95.0,                  # never 100% — it is a prototype indicator
}

# ---------------------------------------------------------------------------
# Correlation classification (Upgrade 7) — exact display ranges
# ---------------------------------------------------------------------------

CLASSIFICATION_BANDS = [
    (0.70, "Strong positive"),
    (0.40, "Moderate positive"),
    (0.20, "Weak positive"),
    (-0.20, "Very weak / little linear relationship"),
    (-0.40, "Weak inverse"),
    (-0.70, "Moderate inverse"),
    (-1.01, "Strong inverse"),
]

# ---------------------------------------------------------------------------
# Demo mode (Upgrade 8)
# ---------------------------------------------------------------------------

# Seconds between replay steps at each speed. 24 steps x 3s = 72 seconds for
# the full story at 1x — inside the 60-90 second judge-demo target.
DEMO_STEP_SECONDS = {1: 3.0, 2: 1.5, 4: 0.75}
DEMO_SPEEDS = [1, 2, 4]   # displayed as 1x / 2x / 4x

# ---------------------------------------------------------------------------
# Civic Health Score
# ---------------------------------------------------------------------------

# Weights for the Civic Health Score. Documented explicitly so judges can see
# exactly how the number is built. These are CityPulse prototype weights,
# NOT an official standard.
HEALTH_WEIGHTS = {"traffic": 0.40, "weather": 0.30, "complaints": 0.30}

# Scaling caps used to normalize each health component to 0-100 severity.
TRAFFIC_CAP = 100.0        # congestion_pct is already 0-100
RAINFALL_CAP_MM = 40.0     # 40 mm of rain per 15 min = maximum severity
COMPLAINTS_CAP = 20.0      # 20 complaints per 15 min in one zone = maximum severity

# Civic Health Score interpretation bands (score -> status).
HEALTH_BANDS = [
    (80, "Healthy", "🟢"),
    (60, "Moderate", "🟡"),
    (40, "Warning", "🟠"),
    (0, "Critical", "🔴"),
]

# ---------------------------------------------------------------------------
# UI constants (shared between app.py panels)
# ---------------------------------------------------------------------------

# Fictional city layout for the map. These are ILLUSTRATIVE positions for a
# fictional city — they do not represent real civic locations.
CITY_CENTER = (17.700, 78.480)
ZONE_COORDS = {
    "Zone A": (17.710, 78.465),   # west
    "Zone B": (17.700, 78.480),   # center
    "Zone C": (17.690, 78.495),   # east
}

# Status color coding used across cards, map, and charts.
STATUS_COLORS = {
    "Healthy": "#2ecc71",
    "Moderate": "#f1c40f",
    "Warning": "#e67e22",
    "Critical": "#e74c3c",
}

SEVERITY_EMOJI = {"Low": "🟢", "Moderate": "🟡", "High": "🟠", "Critical": "🔴"}
TREND_ARROW = {"up": "📈", "down": "📉", "flat": "➡️"}

# Autoplay cadence: pause between replay steps while playing (seconds).
AUTOPLAY_DELAY_SECONDS = 0.8

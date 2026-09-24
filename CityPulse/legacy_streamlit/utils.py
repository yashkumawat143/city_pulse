"""
utils.py
--------
Small shared helpers used by both the pipeline (backend) and the app (UI).
Kept separate so logic and presentation never have to import each other.

Language rules baked in here (do not remove):
    Correlation is NOT causation. Inverse relationships must NEVER be
    described as "moving together". All wording helpers below produce
    cautious, direction-aware phrasing.
"""

from typing import Optional

import pandas as pd

from config import MODERATE_CORR, STRONG_CORR


def strength_label(r: Optional[float]) -> str:
    """Map a Pearson correlation coefficient to a human-readable strength."""
    if r is None or (isinstance(r, float) and pd.isna(r)):
        return "Not enough data"
    r_abs = abs(r)
    if r_abs >= STRONG_CORR:
        return "Strong"
    if r_abs >= MODERATE_CORR:
        return "Moderate"
    return "Weak"


def is_strong(r: Optional[float]) -> bool:
    """True when a correlation value is present and reaches the Strong band."""
    return r is not None and abs(r) >= STRONG_CORR


# ---------------------------------------------------------------------------
# Upgrade 7: exact classification ranges
# ---------------------------------------------------------------------------

def classify_correlation(r: Optional[float]) -> str:
    """
    Classify a Pearson r using the exact v2.0 display ranges:

        r >= 0.70       Strong positive
        0.40-0.69       Moderate positive
        0.20-0.39       Weak positive
        -0.19-0.19      Very weak / little linear relationship
        -0.39--0.20     Weak inverse
        -0.69--0.40     Moderate inverse
        <= -0.70        Strong inverse
    """
    if r is None or (isinstance(r, float) and pd.isna(r)):
        return "Not enough data"
    # Explicit boundaries (matches the spec table exactly, including the
    # <= -0.70 / >= 0.70 strong-inclusive edges).
    if r >= 0.70:
        return "Strong positive"
    if r >= 0.40:
        return "Moderate positive"
    if r >= 0.20:
        return "Weak positive"
    if r > -0.20:
        return "Very weak / little linear relationship"
    if r > -0.40:
        return "Weak inverse"
    if r > -0.70:
        return "Moderate inverse"
    return "Strong inverse"


def relationship_sentence(metric_a: str, metric_b: str, r: Optional[float], zone: str) -> str:
    """
    One direction-aware, causally-safe sentence describing a relationship.

    Positive r  -> "moving together" style wording is allowed.
    Inverse r   -> NEVER "moving together"; explicitly described as inverse.
    Always ends with the actual coefficient.
    """
    if r is None or (isinstance(r, float) and pd.isna(r)):
        return (
            f"Not enough historical observations to calculate a reliable "
            f"{metric_a} / {metric_b} relationship in {zone} yet."
        )
    classification = classify_correlation(r)
    if r >= 0.20:
        core = (
            f"{metric_a.title()} and {metric_b} show a {classification.lower()} "
            f"relationship in {zone} — they have been increasing together."
        )
    elif r <= -0.20:
        core = (
            f"{metric_a.title()} and {metric_b} show a {classification.lower()} "
            f"relationship in {zone} — one tends to be higher while the other is lower. "
            f"These signals show an inverse relationship."
        )
    else:
        core = (
            f"{metric_a.title()} and {metric_b} show little linear relationship "
            f"in {zone} (no meaningful pattern in the current window)."
        )
    return f"{core} (r = {r}) — a temporal association, not a confirmed cause."


def sequence_sentence(signal_names: list[str], zone: str, lag_desc: str) -> str:
    """Causally-safe wording for signals that rose one after another."""
    joined = " → ".join(signal_names)
    return (
        f"Possible temporal sequence in {zone}: {joined}. "
        f"Signals increased in sequence, with changes spaced roughly {lag_desc}."
    )


# ---------------------------------------------------------------------------
# Safe formatting helpers (never divide by zero, never print NaN)
# ---------------------------------------------------------------------------

def safe_pct_difference(current: float, baseline: float) -> Optional[float]:
    """
    Percentage difference vs baseline, or None when the comparison is
    meaningless (baseline ~ 0 -> percentages explode and mislead).
    """
    if baseline is None or abs(baseline) < 1e-9:
        return None
    return round((current - baseline) / abs(baseline) * 100.0, 0)


def format_signed(value: float, suffix: str = "", digits: int = 1) -> str:
    """Format a number with an explicit +/- sign (e.g. '+14.2 mm')."""
    sign = "+" if value >= 0 else "−"  # proper minus sign, not a hyphen
    return f"{sign}{abs(value):.{digits}f}{suffix}"


def pct_text(pct: Optional[float]) -> str:
    """Human text for a percentage difference, safe when None."""
    if pct is None:
        return "n/a (baseline too small for a % comparison)"
    return f"{format_signed(pct, '%', 0)}"

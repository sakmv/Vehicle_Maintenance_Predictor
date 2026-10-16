"""
Trend forecasting for logged sensor readings.

For every sensor we:
1. Fit a robust trend line (Theil-Sen: median of pairwise slopes, so one bad
   reading can't skew it) and test whether the trend is real (Mann-Kendall /
   Kendall tau p-value).
2. If the sensor is drifting toward its unhealthy limit, project when it will
   cross it, with a best/worst-case range from the slope's 90% confidence band.
3. Do the same for the classifier's failure probability, which shows when the
   overall risk is expected to reach "High".

Time axis: a timestamp column if present (days), else mileage_km (km), else the
reading index.
"""
import logging
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger("forecast")

MIN_POINTS = 5
SIGNIFICANCE = 0.10      # p-value below which a trend counts as real
HORIZON_SPANS = 3.0      # don't call a drift "imminent" if the ETA is > 3x the observed time span
TIME_KEYS = ("timestamp", "date", "time", "datetime", "recorded_at")

# feature: (label, unit, healthy_lo, healthy_hi, bad_direction)
SENSORS = {
    "engine_temp_c": ("Engine temperature", "°C", 70, 100, "high"),
    "rpm": ("RPM", "rpm", 700, 3500, "high"),
    "vibration_level": ("Vibration", "g", 0.0, 0.15, "high"),
    "oil_quality_pct": ("Oil quality", "%", 40, 100, "low"),
    "brake_pad_mm": ("Brake pad thickness", "mm", 3, 12, "low"),
    "battery_voltage": ("Battery voltage", "V", 12.0, 14.5, "low"),
    "coolant_level_pct": ("Coolant level", "%", 50, 100, "low"),
}
RISK = ("Failure risk (model)", "%", 0.0, 0.6, "high")  # shown x100

RANK = {"out_of_range": 0, "drifting": 1, "slow_drift": 2, "improving": 3, "stable": 4, "insufficient": 5}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _fmt(v, d=2):
    return f"{v:.{d}f}".rstrip("0").rstrip(".") or "0"


def _with_unit(v, unit):
    return f"{_fmt(v)}{unit}" if unit in ("%", "°C") else f"{_fmt(v)} {unit}"


# ------------------------------------------------------------------ axis ----
def _prepare(rows):
    """Sort rows in time order. Returns (rows, x, x_unit, last_datetime_or_None)."""
    n = len(rows)
    for key in TIME_KEYS:
        raw = [r.get(key) for r in rows]
        if sum(v not in (None, "") for v in raw) < 0.8 * n:
            continue
        ts = pd.to_datetime(pd.Series([None if v in (None, "") else str(v) for v in raw]),
                            errors="coerce", utc=True)
        if ts.notna().sum() < 0.8 * n:
            continue
        keep = [i for i in ts.sort_values().index if pd.notna(ts[i])]
        rows = [rows[i] for i in keep]
        ts = ts.loc[keep].reset_index(drop=True)
        x = ((ts - ts.iloc[0]).dt.total_seconds() / 86400).to_numpy(dtype=float)
        return rows, x, "days", ts.iloc[-1].to_pydatetime()

    m = [_num(r.get("mileage_km")) for r in rows]
    if all(v is not None for v in m) and np.ptp(m) > 0:
        order = np.argsort(m, kind="stable")
        rows = [rows[i] for i in order]
        mm = np.asarray(m, dtype=float)[order]
        return rows, mm - mm[0], "km", None

    return rows, np.arange(n, dtype=float), "readings", None


# -------------------------------------------------------------- analysis ----
def _span_phrase(eta, x_unit):
    if x_unit == "days":
        if eta < 1:
            return "within a day"
        if eta < 60:
            return f"in about {round(eta)} days"
        return f"in about {round(eta / 30)} months"
    if x_unit == "km":
        return f"in about {int(round(eta / 10) * 10):,} km"
    return f"in about {round(eta)} more readings"


def _analyze(feature, meta, xs, ys, x_now, x_unit, last_dt, scale=1.0):
    label, unit, lo, hi, bad = meta
    limit = hi if bad == "high" else lo
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    n = len(ys)

    out = {
        "feature": feature, "label": label, "unit": unit, "scale": scale,
        "limit": limit, "bad_direction": bad, "latest": round(float(ys[-1]), 4),
        "points": [[round(float(a), 3), round(float(b), 4)] for a, b in zip(xs, ys)],
        "status": "insufficient", "slope": None, "p_value": None, "eta": None,
        "eta_range": None, "eta_date": None, "fit": None, "projection": None, "message": "",
    }
    if n < MIN_POINTS or np.ptp(xs) == 0:
        out["message"] = f"Need at least {MIN_POINTS} readings of {label.lower()} (have {n})."
        return out

    latest = float(ys[-1])
    span = float(np.ptp(xs))
    if np.ptp(ys) == 0:
        slope, icpt, lo_s, hi_s, p = 0.0, float(ys[0]), 0.0, 0.0, 1.0
    else:
        slope, icpt, lo_s, hi_s = stats.theilslopes(ys, xs, alpha=0.90)
        _, p = stats.kendalltau(xs, ys)
        p = 1.0 if p is None or not np.isfinite(p) else float(p)

    fit_now = icpt + slope * x_now
    out["slope"] = float(slope)
    out["p_value"] = round(p, 4)
    out["fit"] = [[round(float(xs[0]), 3), round(float(icpt + slope * xs[0]), 4)],
                  [round(float(xs[-1]), 3), round(float(icpt + slope * xs[-1]), 4)]]

    mult = 1000.0 if x_unit == "km" else 1.0
    rate_label = {"days": "/day", "km": " per 1,000 km", "readings": " per reading"}[x_unit]
    rate_txt = f"{_fmt(abs(slope) * mult * scale, 2)} {unit}{rate_label}"
    word_dir = "rising" if slope > 0 else "falling"
    above_below = "above" if bad == "high" else "below"
    limit_txt = _with_unit(limit * scale, unit)
    limit_name = "the High-risk threshold" if feature == "failure_risk" else "its healthy limit"

    beyond = latest > limit if bad == "high" else latest < limit
    toward = slope > 0 if bad == "high" else slope < 0
    significant = p < SIGNIFICANCE and slope != 0

    if beyond:
        out["status"] = "out_of_range"
        out["message"] = f"{label} is already {above_below} {limit_name} ({limit_txt})."
    elif significant and toward:
        gap = max(0.0, (limit - fit_now) if bad == "high" else (fit_now - limit))
        eta = gap / abs(slope)
        fast = max(abs(lo_s), abs(hi_s))
        slow = min(abs(lo_s), abs(hi_s)) if lo_s * hi_s > 0 else None   # None = could be much later
        out["eta"] = round(float(eta), 2)
        out["eta_range"] = [round(float(gap / fast), 2) if fast > 0 else None,
                            round(float(gap / slow), 2) if slow else None]
        if eta > HORIZON_SPANS * span:
            out["status"] = "slow_drift"
            out["eta"] = None
            out["eta_range"] = None
            x_end = x_now + span
            out["projection"] = [[round(x_now, 3), round(fit_now, 4)],
                                 [round(x_end, 3), round(fit_now + slope * span, 4)]]
            out["message"] = (f"{label} is slowly {word_dir} (~{rate_txt}) but is not projected "
                              f"to reach its limit any time soon.")
        else:
            out["status"] = "drifting"
            x_end = x_now + eta
            out["projection"] = [[round(x_now, 3), round(fit_now, 4)], [round(x_end, 3), round(limit, 4)]]
            when = _span_phrase(eta, x_unit)
            if x_unit == "days" and last_dt is not None:
                date = (last_dt + timedelta(days=float(eta))).date().isoformat()
                out["eta_date"] = date
                when += f" (around {date})"
            out["message"] = (f"{label} is {word_dir} ~{rate_txt} and is projected to go "
                              f"{above_below} {limit_txt} {when}.")
    elif significant:
        out["status"] = "improving"
        out["message"] = f"{label} is moving back toward healthy (~{rate_txt})."
    else:
        out["status"] = "stable"
        out["message"] = f"{label} is stable; no significant trend."
    return out


# ------------------------------------------------------------------- run ----
def run(rows, risk_fn=None):
    rows = [r for r in rows if isinstance(r, dict)]
    n = len(rows)
    if n < MIN_POINTS:
        return {"n": n, "x_unit": None, "series": [], "summary": [],
                "message": f"Need at least {MIN_POINTS} readings to forecast (have {n})."}

    rows, x, x_unit, last_dt = _prepare(rows)
    x_now = float(x[-1])
    series = []

    for feat, meta in SENSORS.items():
        pts = [(xi, _num(r.get(feat))) for xi, r in zip(x, rows)]
        pts = [(a, b) for a, b in pts if b is not None]
        if pts:
            series.append(_analyze(feat, meta, [p[0] for p in pts], [p[1] for p in pts],
                                   x_now, x_unit, last_dt))

    if risk_fn is not None:
        try:
            probs = risk_fn(rows)
            series.append(_analyze("failure_risk", RISK, x, probs, x_now, x_unit, last_dt, scale=100.0))
        except Exception as e:  # never let the risk model break sensor trends
            log.warning("risk series failed: %s", e)

    series.sort(key=lambda s: (RANK[s["status"]], s["eta"] if s["eta"] is not None else 1e18))

    summary = [s["message"] for s in series if s["status"] in ("out_of_range", "drifting")]
    if not summary:
        summary = ["No sensor is drifting toward its healthy limit."]

    return {"n": n, "x_unit": x_unit, "series": series, "summary": summary[:4], "message": ""}
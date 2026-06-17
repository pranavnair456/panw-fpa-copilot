"""Stage 1 — Driver-based probabilistic forecast.

Forecasts PANW revenue at the segment level (product, subscription) and sums to a
total, wrapping point forecasts in a Monte Carlo layer that produces an 80%
prediction interval (a fan chart, not a single line).

Design choices (see LEARNING.md):
  * Interpretable models only. ~20 quarterly points is far too little for deep
    learning; we use ETS (exponential smoothing) with additive fiscal-quarter
    seasonality. An ARIMAX-on-RPO alternative is provided.
  * We forecast ORGANIC revenue: training excludes quarters with disclosed
    acquisition revenue (FY2026Q3), so the CyberArk/Chronosphere step doesn't
    distort the underlying trend. The held-out organic actual becomes a free
    out-of-sample check.
  * Monte Carlo: we draw many simulated future paths from the fitted model and
    read the 10th/90th percentiles as the 80% band. Segment paths are summed
    path-wise so the total's uncertainty aggregates correctly.

Run: python -m src.forecast
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.arima.model import ARIMA

from src import config

SEGMENTS = ["revenue_product", "revenue_subscription"]


def load() -> pd.DataFrame:
    df = pd.read_csv(config.FINANCIALS_CSV, parse_dates=["period_end_date"])
    return df.sort_values("period_end_date").reset_index(drop=True)


def next_fiscal_quarters(last_label: str, h: int) -> list[str]:
    """Generate the next h fiscal-quarter labels after e.g. 'FY2026Q2'."""
    fy = int(last_label[2:6]); q = int(last_label[-1])
    out = []
    for _ in range(h):
        q += 1
        if q > 4:
            q = 1; fy += 1
        out.append(f"FY{fy}Q{q}")
    return out


@dataclass
class SegmentForecast:
    name: str
    point: np.ndarray          # (h,)
    low: np.ndarray            # (h,) 10th pct
    high: np.ndarray           # (h,) 90th pct
    sims: np.ndarray           # (reps, h) simulated paths
    model: str


@dataclass
class ForecastResult:
    horizon: int
    future_quarters: list[str]
    training_cutoff: str
    segments: dict[str, SegmentForecast]
    total_point: np.ndarray
    total_low: np.ndarray
    total_high: np.ndarray
    history: pd.DataFrame = field(repr=False)
    pi: float = config.PREDICTION_INTERVAL
    interval_method: str = "mc"

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for i, q in enumerate(self.future_quarters):
            row = {"fiscal_quarter": q}
            for seg, fc in self.segments.items():
                row[f"{seg}_point"] = round(float(fc.point[i]), 1)
            row["total_point"] = round(float(self.total_point[i]), 1)
            row["total_low"] = round(float(self.total_low[i]), 1)
            row["total_high"] = round(float(self.total_high[i]), 1)
            rows.append(row)
        return pd.DataFrame(rows)


def _simulate_segment(series: pd.Series, horizon: int, model: str,
                      sigma_scale: float, reps: int, seed: int) -> SegmentForecast:
    name = series.name
    y = series.astype(float).reset_index(drop=True)
    use_seasonal = len(y) >= 12  # need >=3 fiscal-year cycles to estimate season

    if model == "arimax":
        # Driver regression on RPO with ARIMA errors. Falls back to ETS shape for
        # simulation; kept simple and interpretable.
        res = ARIMA(y, order=(1, 1, 0)).fit()
        point = np.asarray(res.forecast(horizon), dtype=float)
        sims = np.asarray(res.simulate(horizon, repetitions=reps,
                                       anchor="end", random_state=seed))
        sims = sims.reshape(reps, horizon) if sims.ndim == 2 else sims.T
    else:  # ETS (default)
        seasonal = config.ETS_SEASONAL if use_seasonal else None
        fit = ETSModel(
            y, error="add", trend="add",
            seasonal=seasonal,
            seasonal_periods=4 if seasonal else None,
            damped_trend=config.ETS_DAMPED_TREND,
        ).fit(disp=False)
        point = np.asarray(fit.forecast(horizon), dtype=float)
        raw = fit.simulate(nsimulations=horizon, repetitions=reps,
                           anchor="end", random_state=seed)
        sims = np.asarray(raw).T  # -> (reps, horizon)

    # Scale dispersion around the point path by the user's assumption sigma.
    sims = point[None, :] + (sims - point[None, :]) * sigma_scale
    lo = (1 - config.PREDICTION_INTERVAL) / 2 * 100
    hi = 100 - lo
    return SegmentForecast(
        name=name, point=point,
        low=np.percentile(sims, lo, axis=0),
        high=np.percentile(sims, hi, axis=0),
        sims=sims, model=model,
    )


def conformal_radius(errors, pi: float) -> float:
    """Split-conformal radius from |residuals| with finite-sample correction.

    Uses the |actual - point| quantile at level ceil((n+1)*pi)/n — the rank that
    gives conformal's finite-sample coverage guarantee on small calibration sets.
    """
    abs_e = np.abs(np.asarray(errors, float))
    n = len(abs_e)
    level = min(1.0, np.ceil((n + 1) * pi) / n)
    return float(np.quantile(abs_e, level, method="higher"))


def conformal_band(point: np.ndarray, errors, pi: float) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric prediction band from out-of-sample (walk-forward) residuals.

    The band reflects DEMONSTRATED error rather than the model's optimistic
    in-sample variance, and grows with the forecast horizon h as ~sqrt(h)
    (random-walk error accumulation).
    """
    r = conformal_radius(errors, pi)
    scale = np.sqrt(np.arange(1, len(point) + 1))
    return point - r * scale, point + r * scale


def run_forecast(df: pd.DataFrame | None = None, horizon: int | None = None,
                 sigma_scale: float | None = None,
                 segment_models: dict | None = None,
                 reps: int | None = None, seed: int | None = None,
                 conformal_errors=None) -> ForecastResult:
    df = load() if df is None else df
    horizon = horizon or config.FORECAST_HORIZON
    sigma_scale = config.ASSUMPTION_SIGMA_SCALE if sigma_scale is None else sigma_scale
    segment_models = segment_models or config.SEGMENT_MODELS
    reps = reps or config.MONTE_CARLO_SIMS
    seed = config.RANDOM_SEED if seed is None else seed

    # Train on ORGANIC history only: drop quarters with disclosed inorganic rev.
    clean = df[df["inorganic_revenue"] == 0].reset_index(drop=True)
    cutoff = clean["fiscal_quarter"].iloc[-1]
    future = next_fiscal_quarters(cutoff, horizon)

    rng = np.random.default_rng(seed)
    segforecasts: dict[str, SegmentForecast] = {}
    for seg in SEGMENTS:
        segforecasts[seg] = _simulate_segment(
            clean.set_index("period_end_date")[seg].rename(seg),
            horizon, segment_models.get(seg, "ets"), sigma_scale, reps,
            int(rng.integers(1, 2**31)),
        )

    # Total = path-wise sum of segment simulations (correct uncertainty aggregation).
    total_sims = sum(fc.sims for fc in segforecasts.values())
    total_point = sum(fc.point for fc in segforecasts.values())
    lo = (1 - config.PREDICTION_INTERVAL) / 2 * 100
    mc_low = np.percentile(total_sims, lo, axis=0)
    mc_high = np.percentile(total_sims, 100 - lo, axis=0)

    # Default to conformal bands when calibration residuals are supplied and the
    # config asks for it; otherwise fall back to the raw Monte Carlo band.
    if conformal_errors is not None and config.INTERVAL_METHOD == "conformal":
        c_low, c_high = conformal_band(total_point, conformal_errors,
                                       config.PREDICTION_INTERVAL)
        total_low, total_high, method = c_low, c_high, "conformal"
    else:
        total_low, total_high, method = mc_low, mc_high, "mc"

    return ForecastResult(
        horizon=horizon, future_quarters=future, training_cutoff=cutoff,
        segments=segforecasts, total_point=total_point,
        total_low=total_low, total_high=total_high, history=df,
        interval_method=method,
    )


def load_conformal_errors():
    """Walk-forward residuals saved by Stage 2 (Nonexistent before backtest runs)."""
    import json
    path = config.DATA / "backtest_report.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["calibration"].get("residuals")


if __name__ == "__main__":
    res = run_forecast(conformal_errors=load_conformal_errors())
    print(f"Training through {res.training_cutoff} (organic-only); "
          f"forecasting {res.horizon} quarters. Interval method: {res.interval_method}.\n")
    fc = res.to_frame()
    print(fc.to_string(index=False))

    # Free out-of-sample check: did the organic forecast for the held-out,
    # acquisition-contaminated quarter (FY2026Q3) land near the known organic
    # actual (total - disclosed inorganic)?
    df = res.history
    held = df[df["inorganic_revenue"] > 0]
    if not held.empty and res.future_quarters[0] == held["fiscal_quarter"].iloc[0]:
        actual_org = held["revenue_organic"].iloc[0]
        pt = res.total_point[0]; lo_, hi_ = res.total_low[0], res.total_high[0]
        inside = lo_ <= actual_org <= hi_
        print(f"\nOut-of-sample check on {held['fiscal_quarter'].iloc[0]} (organic):")
        print(f"  forecast point {pt:,.0f}  80% band [{lo_:,.0f}, {hi_:,.0f}]  "
              f"actual organic {actual_org:,.0f}  -> {'INSIDE' if inside else 'OUTSIDE'} band  "
              f"(err {(pt-actual_org)/actual_org*100:+.1f}%)")

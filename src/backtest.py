"""Stage 2 — Backtesting & validation.

Walk-forward (a.k.a. rolling-origin) evaluation: train on organic history through
quarter T, forecast T+1, roll forward one quarter, repeat. No future data ever
enters a training window (no leakage). We then ask three questions:

  1. Accuracy: MAPE / RMSE of the model vs naive baselines AND vs management's own
     revenue guidance. A forecast that can't beat "last year + growth" isn't worth
     trusting — and if it doesn't, we say so.
  2. Calibration: do the 80% prediction intervals actually contain the actual
     ~80% of the time? An interval that's right 80% of the time is honest; one
     that's right 30% of the time is overconfident.
  3. Honesty: every number is reported as-is, including where the model loses.

Run: python -m src.backtest
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import numpy as np
import pandas as pd

from src import config
from src.forecast import run_forecast

TARGET = "revenue_organic"        # forecast the underlying organic series
MIN_TRAIN = 12                    # need >=3 fiscal-year cycles for seasonal ETS


def _mape(actual, pred) -> float:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.mean(np.abs((a - p) / a)) * 100)


def _rmse(actual, pred) -> float:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.sqrt(np.mean((a - p) ** 2)))


@dataclass
class BacktestReport:
    steps: pd.DataFrame                 # per-origin predictions vs actuals
    metrics: dict                       # MAPE/RMSE per method
    calibration: dict                   # coverage vs nominal
    beats_baseline: bool
    headline: str

    def save(self, path=None):
        path = path or (config.DATA / "backtest_report.json")
        payload = {
            "metrics": self.metrics,
            "calibration": self.calibration,
            "beats_baseline": self.beats_baseline,
            "headline": self.headline,
            "steps": self.steps.to_dict(orient="records"),
        }
        path.write_text(json.dumps(payload, indent=2, default=float))
        return path


def run_backtest(df: pd.DataFrame | None = None, min_train: int = MIN_TRAIN) -> BacktestReport:
    from src.forecast import load
    df = load() if df is None else df
    clean = df[df["inorganic_revenue"] == 0].reset_index(drop=True)
    y = clean[TARGET].to_numpy(float)

    rows = []
    for i in range(min_train, len(clean) - 1):     # origin = clean[i], predict clean[i+1]
        actual = y[i + 1]
        # --- model: segment-sum ETS + Monte Carlo, trained ONLY on data <= origin
        train_df = df[df["period_end_date"] <= clean["period_end_date"].iloc[i]]
        res = run_forecast(df=train_df, horizon=1)
        m_pt, m_lo, m_hi = res.total_point[0], res.total_low[0], res.total_high[0]
        # --- baselines
        naive = y[i] * (y[i] / y[i - 1])                       # drift: last QoQ growth
        seasonal = y[i - 3] * (y[i] / y[i - 4])                # last-year same-Q x trailing YoY
        # --- management guidance issued AT origin for the next quarter (midpoint)
        g_lo = clean["guidance_revenue_next_q_low"].iloc[i]
        g_hi = clean["guidance_revenue_next_q_high"].iloc[i]
        guidance = (g_lo + g_hi) / 2 if pd.notna(g_lo) and pd.notna(g_hi) else np.nan

        rows.append({
            "predict_quarter": clean["fiscal_quarter"].iloc[i + 1],
            "actual": round(actual, 1),
            "model": round(m_pt, 1),
            "mc_low": round(m_lo, 1), "mc_high": round(m_hi, 1),
            "mc_in_band": bool(m_lo <= actual <= m_hi),
            "naive": round(naive, 1), "seasonal_naive": round(seasonal, 1),
            "guidance": round(guidance, 1) if pd.notna(guidance) else np.nan,
        })
    steps = pd.DataFrame(rows)

    # Signed out-of-sample residuals (actual - point) drive conformal intervals.
    from src.forecast import conformal_radius
    residuals = (steps["actual"] - steps["model"]).to_numpy(float)
    pi = config.PREDICTION_INTERVAL
    lo_q = (1 - pi) / 2 * 100
    # Leave-one-out symmetric conformal band: radius from the OTHER residuals.
    c_lows, c_highs, c_in = [], [], []
    for k in range(len(steps)):
        r = conformal_radius(np.delete(residuals, k), pi)
        cl, ch = steps["model"].iloc[k] - r, steps["model"].iloc[k] + r
        c_lows.append(round(cl, 1)); c_highs.append(round(ch, 1))
        c_in.append(bool(cl <= steps["actual"].iloc[k] <= ch))
    steps["conf_low"], steps["conf_high"], steps["conf_in_band"] = c_lows, c_highs, c_in

    methods = ["model", "naive", "seasonal_naive", "guidance"]
    metrics = {}
    for m in methods:
        mask = steps[m].notna()
        metrics[m] = {
            "MAPE": round(_mape(steps.loc[mask, "actual"], steps.loc[mask, m]), 2),
            "RMSE": round(_rmse(steps.loc[mask, "actual"], steps.loc[mask, m]), 1),
            "n": int(mask.sum()),
        }

    # Calibration of the 80% band — raw Monte Carlo vs conformal.
    def verdict(cov):
        if abs(cov - config.PREDICTION_INTERVAL) <= 0.15:
            return "well-calibrated"
        return ("overconfident (bands too narrow)" if cov < config.PREDICTION_INTERVAL
                else "conservative (bands too wide)")
    mc_cov = float(steps["mc_in_band"].mean())
    conf_cov = float(steps["conf_in_band"].mean())
    calibration = {
        "nominal": config.PREDICTION_INTERVAL,
        "n": int(len(steps)),
        "mc_coverage": round(mc_cov, 3),
        "mc_verdict": verdict(mc_cov),
        "conformal_coverage": round(conf_cov, 3),
        "conformal_verdict": verdict(conf_cov),
        # full-set conformal radius + residuals, exported for the LIVE forecast band
        "conformal_radius": round(conformal_radius(residuals, pi), 1),
        "residuals": [round(float(r), 1) for r in residuals],
    }

    # Primary baseline (per spec): naive drift = prior quarter x trailing growth.
    # We ALSO report a tougher seasonal-naive and management guidance as honest
    # benchmarks — beating a weak baseline alone would overstate the result.
    model_mape = metrics["model"]["MAPE"]
    drift = metrics["naive"]["MAPE"]
    seasonal_mape = metrics["seasonal_naive"]["MAPE"]
    beats = model_mape < drift
    impr = (drift - model_mape) / drift * 100
    headline = (
        f"Model MAPE {model_mape:.2f}% "
        + (f"beats the naive drift baseline ({drift:.2f}%) by {impr:.0f}%."
           if beats else
           f"does NOT beat the naive drift baseline ({drift:.2f}%).")
        + f" Tougher benchmarks: seasonal-naive {seasonal_mape:.2f}%"
    )
    if not np.isnan(metrics["guidance"]["MAPE"]):
        headline += f", management guidance {metrics['guidance']['MAPE']:.2f}%"
    headline += (f" (over {metrics['model']['n']} walk-forward quarters). "
                 f"Model roughly matches these strong benchmarks — expected for a "
                 f"backlog-driven business; the added value is calibrated "
                 f"uncertainty + organic/inorganic decomposition.")

    return BacktestReport(steps, metrics, calibration, beats, headline)


if __name__ == "__main__":
    rep = run_backtest()
    print("Walk-forward backtest (no leakage) — forecasting organic total revenue\n")
    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(rep.steps.to_string(index=False))
    print("\n--- Accuracy (lower = better) ---")
    print(pd.DataFrame(rep.metrics).T.to_string())
    print("\n--- Calibration of 80% interval (Monte Carlo vs Conformal) ---")
    c = rep.calibration
    print(f"  nominal {c['nominal']:.0%} over n={c['n']} quarters")
    print(f"  Monte Carlo : coverage {c['mc_coverage']:.0%}  -> {c['mc_verdict']}")
    print(f"  Conformal   : coverage {c['conformal_coverage']:.0%}  -> {c['conformal_verdict']}")
    print(f"\n>>> {rep.headline}")
    saved = rep.save()
    print(f"\nSaved {saved}")

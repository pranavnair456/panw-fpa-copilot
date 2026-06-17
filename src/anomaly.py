"""Stage 3.5 — Discrepancy & Anomaly Detection.

The CFO-org AI team builds three things for FP&A: forecasting, variance analysis,
and DISCREPANCY / ANOMALY detection. This stage is the third. It scans the data
and the forecast outputs for points that look *off* and explains WHY each was
flagged — then does the thing a good analyst does next: it cross-checks each flag
against what we already know (disclosed acquisitions, guidance, the calibrated
forecast band) and labels it **"expected (explained)"** vs **"unexplained
(investigate)"**. A statistical outlier the company already told us about (the
$388M CyberArk + Chronosphere revenue) is *expected*; an unexplained one is what a
human should look at.

It stays deliberately INTERPRETABLE — robust statistics (median / MAD), explicit
accounting identities, and the existing conformal band — never a black box. Every
flag carries the numbers behind it so a CFO can audit it, and every generated
figure is gated by the same no-hallucination verifier (src/verify.py).

Three detector families:
  1. reconciliation — accounting identities (segments sum to total; organic +
     inorganic = total) + the independent SEC XBRL cross-check. Data-integrity.
  2. trend_band     — a metric breaking its trend/seasonality band, measured by a
     robust z-score on its year-over-year growth (seasonality-neutral).
  3. forecast_band  — an actual landing outside the *calibrated* conformal band,
     reusing the leakage-free walk-forward forecast. The "abnormally large
     variance vs forecast" case.

Output is DATA, not prose (mirrors variance.py); the narrative is templated and
verifier-safe. Run: python -m src.anomaly [FY2026Q3]
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
import sys
import numpy as np
import pandas as pd

from src import config

_SEV_RANK = {"info": 1, "warning": 2, "critical": 3}


# ----------------------------------------------------------- robust statistics
def _robust_z(values: np.ndarray) -> np.ndarray:
    """(value - median) / (1.4826 * MAD), the robust analog of a z-score.

    MAD (median absolute deviation) is used instead of the standard deviation
    because on a ~20-point series one outlier would inflate the std and hide
    itself; the median/MAD pair is barely moved by a single extreme point.
    """
    x = np.asarray(values, float)
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale == 0:        # degenerate (e.g. constant)
        sd = np.nanstd(x)
        scale = sd if sd > 0 else np.nan
    return (x - med) / scale


def _yoy_growth(df: pd.DataFrame, col: str) -> np.ndarray:
    """Year-over-year (same fiscal quarter) % growth — neutralizes seasonality."""
    v = df[col].to_numpy(float)
    out = np.full(len(v), np.nan)
    for i in range(4, len(v)):
        if np.isfinite(v[i]) and np.isfinite(v[i - 4]) and v[i - 4]:
            out[i] = (v[i] - v[i - 4]) / v[i - 4] * 100
    return out


def _qoq_change_pp(df: pd.DataFrame, col: str) -> np.ndarray:
    """Quarter-over-quarter change in percentage points (for margin-style lines)."""
    v = df[col].to_numpy(float)
    out = np.full(len(v), np.nan)
    out[1:] = v[1:] - v[:-1]
    return out


def _sev_from_z(z: float) -> str:
    az = abs(z)
    if az >= config.ANOMALY_Z_CRITICAL:
        return "critical"
    if az >= config.ANOMALY_Z_WARNING:
        return "warning"
    return "info"


def _sev_from_ratio(ratio: float) -> str | None:
    """Severity from band-exceedance ratio = |actual - point| / conformal radius.

    <=1.0 means inside the calibrated band → not an anomaly (None)."""
    if ratio > 2.0:
        return "critical"
    if ratio > 1.3:
        return "warning"
    if ratio > 1.0:
        return "info"            # just outside the band — a boundary miss
    return None


# ----------------------------------------------------------------- data model
@dataclass
class Anomaly:
    metric: str                  # e.g. "revenue_total", "rpo", "segment_reconciliation"
    quarter: str                 # fiscal quarter the flag applies to
    detector: str                # "reconciliation" | "trend_band" | "forecast_band"
    observed: float
    expected: float
    deviation_pct: float         # observed vs expected, in % (signed)
    unit: str                    # "$M" | "%"
    severity: str                # "info" | "warning" | "critical"
    status: str                  # "explained" | "unexplained"
    why: str                     # deterministic, verifier-safe plain-English reason
    explanation: str | None = None   # if explained: the disclosure that accounts for it

    @property
    def sort_key(self):
        # unexplained first, then by descending severity, then magnitude
        return (self.status == "explained", -_SEV_RANK[self.severity],
                -abs(self.deviation_pct))


@dataclass
class AnomalyReport:
    quarter: str                 # focus quarter (drives the forecast-relative check)
    quarters_scanned: list
    anomalies: list              # severity-ranked list[Anomaly]
    notes: list = field(default_factory=list)

    def to_records(self) -> list:
        return [asdict(a) for a in self.anomalies]

    def to_frame(self) -> pd.DataFrame:
        cols = ["severity", "status", "quarter", "metric", "detector",
                "observed", "expected", "deviation_pct", "unit", "why"]
        if not self.anomalies:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(self.to_records())[cols]

    def save(self, path=None):
        path = path or config.ANOMALY_REPORT
        payload = {
            "quarter": self.quarter,
            "quarters_scanned": self.quarters_scanned,
            "notes": self.notes,
            "anomalies": self.to_records(),
        }
        path.write_text(json.dumps(payload, indent=2, default=float))
        return path


# -------------------------------------------------------------- the detectors
def _detect_reconciliation(df: pd.DataFrame, notes: list) -> list:
    """Accounting-identity discrepancies + the independent SEC XBRL cross-check.

    On clean data nothing fires (the dataset already reconciles); this detector
    exists to CATCH a future mis-transcribed or mis-keyed figure — the everyday
    'tie-out' an FP&A analyst does before trusting any number.
    """
    from src.ingest import reconcile
    out = []
    recon = reconcile(df).set_index("fiscal_quarter")
    for _, r in df.iterrows():
        q = r["fiscal_quarter"]
        total = float(r["revenue_total"])
        # (a) segment identity: product + subscription == total
        seg_sum = round(float(r["revenue_product"]) + float(r["revenue_subscription"]), 1)
        gap = round(seg_sum - total, 1)
        if abs(gap) > 0.2:
            out.append(Anomaly(
                metric="segment_reconciliation", quarter=q, detector="reconciliation",
                observed=seg_sum, expected=total,
                deviation_pct=round(gap / total * 100, 2) if total else 0.0, unit="$M",
                severity="critical", status="unexplained",
                why=(f"Product + Subscription sum to ${seg_sum:,.1f}M but total revenue "
                     f"is reported ${total:,.1f}M — a ${abs(gap):,.1f}M discrepancy that "
                     f"must be reconciled before the number is trusted."),
            ))
        # (b) organic + inorganic == total
        org = float(r["revenue_organic"]); inorg = float(r["inorganic_revenue"])
        ogap = round(org + inorg - total, 1)
        if abs(ogap) > 0.2:
            out.append(Anomaly(
                metric="organic_reconciliation", quarter=q, detector="reconciliation",
                observed=round(org + inorg, 1), expected=total,
                deviation_pct=round(ogap / total * 100, 2) if total else 0.0, unit="$M",
                severity="critical", status="unexplained",
                why=(f"Organic ${org:,.1f}M + inorganic ${inorg:,.1f}M = ${org + inorg:,.1f}M, "
                     f"which does not tie to the ${total:,.1f}M total reported."),
            ))
        # (c) independent SEC XBRL cross-check (where a quarterly fact exists)
        if q in recon.index and not bool(recon.loc[q, "xbrl_matches"]):
            xv = float(recon.loc[q, "xbrl_revenue"])
            out.append(Anomaly(
                metric="xbrl_cross_check", quarter=q, detector="reconciliation",
                observed=total, expected=xv,
                deviation_pct=round((total - xv) / xv * 100, 2) if xv else 0.0, unit="$M",
                severity="critical", status="unexplained",
                why=(f"Press-release total ${total:,.1f}M disagrees with the independent "
                     f"SEC XBRL figure ${xv:,.1f}M for the same period."),
            ))
    return out


def _detect_trend_band(df: pd.DataFrame, notes: list) -> list:
    """A metric breaking its trend/seasonality band, via a robust z on YoY growth."""
    # (metric, label, transform, unit-of-the-change)
    specs = [
        ("revenue_total", "Total revenue", _yoy_growth),
        ("revenue_organic", "Organic revenue", _yoy_growth),
        ("rpo", "RPO (backlog)", _yoy_growth),
        ("ngs_arr", "NGS ARR", _yoy_growth),
        ("non_gaap_op_margin", "Non-GAAP operating margin", _qoq_change_pp),
    ]
    out = []
    for col, label, transform in specs:
        if col not in df:
            continue
        change = transform(df, col)
        n_valid = int(np.isfinite(change).sum())
        if n_valid < config.ANOMALY_MIN_POINTS:
            notes.append(f"Trend-band scan skipped for {label}: only {n_valid} "
                         f"comparable points (need ≥{config.ANOMALY_MIN_POINTS}).")
            continue
        z = _robust_z(change)
        typical = float(np.nanmedian(change))
        for i in range(len(df)):
            if not np.isfinite(z[i]) or abs(z[i]) < config.ANOMALY_Z_WARNING:
                continue
            growth = round(float(change[i]), 1)
            kind = "year-over-year" if transform is _yoy_growth else "quarter-over-quarter (pp)"
            out.append(Anomaly(
                metric=col, quarter=df["fiscal_quarter"].iloc[i], detector="trend_band",
                observed=growth, expected=round(typical, 1),
                deviation_pct=round(growth - typical, 1), unit="%",
                severity=_sev_from_z(z[i]), status="unexplained",
                why=(f"{label} moved {growth:+.1f}% {kind}, versus a typical "
                     f"{round(typical, 1):+.1f}%; robust z = {z[i]:.1f} — outside the "
                     f"metric's normal band."),
            ))
    return out


def _detect_forecast_band(df: pd.DataFrame, quarter: str, backtest, notes: list) -> list:
    """Actuals landing outside the calibrated conformal band (leakage-free).

    Two sources, both reusing the existing forecast machinery:
      * historical walk-forward steps (organic quarters the model was surprised by);
      * the focus quarter, forecast from prior data only — where the
        acquisition-contaminated total is a large, *explained* band break.
    """
    out = []
    pi = config.ANOMALY_BAND_LEVEL

    # --- historical walk-forward surprises (clean organic quarters) ---
    if backtest is not None:
        steps = backtest.steps
        for _, s in steps[~steps["conf_in_band"].astype(bool)].iterrows():
            actual, point = float(s["actual"]), float(s["model"])
            radius = max((float(s["conf_high"]) - float(s["conf_low"])) / 2, 1e-9)
            ratio = abs(actual - point) / radius
            sev = _sev_from_ratio(ratio)
            if sev is None:
                continue
            out.append(Anomaly(
                metric="revenue_organic", quarter=str(s["predict_quarter"]),
                detector="forecast_band", observed=round(actual, 1), expected=round(point, 1),
                deviation_pct=round((actual - point) / point * 100, 1), unit="$M",
                severity=sev, status="unexplained",
                why=(f"Organic revenue actual ${actual:,.1f}M vs the model's "
                     f"${point:,.1f}M ({round((actual - point) / point * 100, 1):+.1f}%) — "
                     f"outside the calibrated {pi:.0%} band (≈{ratio:.1f}× the error radius)."),
            ))

    # --- focus quarter: forecast from prior data only (no leakage) ---
    try:
        from src.variance import forecast_for
        res = forecast_for(df, quarter)
    except Exception as e:                      # quarter too early to forecast, etc.
        notes.append(f"Forecast-relative scan skipped for {quarter}: {e}")
        return out

    row = df[df["fiscal_quarter"] == quarter].iloc[0]
    f_org = float(res.total_point[0])
    lo, hi = float(res.total_low[0]), float(res.total_high[0])
    radius = max((hi - lo) / 2, 1e-9)
    actual_total = float(row["revenue_total"])
    actual_org = float(row["revenue_organic"])
    inorg = float(row["inorganic_revenue"])

    # (1) Total reported vs the organic forecast — the headline check.
    gap = actual_total - f_org
    ratio_t = abs(gap) / radius
    sev_t = _sev_from_ratio(ratio_t)
    if sev_t is not None:
        # Explained when a disclosed acquisition accounts for most of the gap.
        explained = inorg > 0 and gap != 0 and (inorg / gap) >= 0.5
        if explained:
            status, expl = "explained", (
                f"${inorg:,.0f}M of the gap is the disclosed CyberArk + Chronosphere "
                f"acquisition revenue — structural, not a forecasting error.")
            why = (f"Reported total revenue ${actual_total:,.0f}M came in ${gap:,.0f}M above "
                   f"the ${f_org:,.0f}M organic forecast; ${inorg:,.0f}M of that is the "
                   f"disclosed CyberArk + Chronosphere acquisition.")
        else:
            status, expl = "unexplained", None
            why = (f"Reported total revenue ${actual_total:,.0f}M is ${gap:,.0f}M from the "
                   f"${f_org:,.0f}M forecast — outside the calibrated {pi:.0%} band "
                   f"(≈{ratio_t:.1f}× the error radius).")
        out.append(Anomaly(
            metric="revenue_total", quarter=quarter, detector="forecast_band",
            observed=round(actual_total, 1), expected=round(f_org, 1),
            deviation_pct=round(gap / f_org * 100, 1), unit="$M",
            severity=sev_t, status=status, why=why, explanation=expl))

    # (2) Organic actual vs the band — the honest "did the core business surprise us?"
    ratio_o = abs(actual_org - f_org) / radius
    sev_o = _sev_from_ratio(ratio_o)
    if sev_o is not None:
        dev = round((actual_org - f_org) / f_org * 100, 1)
        out.append(Anomaly(
            metric="revenue_organic", quarter=quarter, detector="forecast_band",
            observed=round(actual_org, 1), expected=round(f_org, 1),
            deviation_pct=dev, unit="$M", severity=sev_o, status="unexplained",
            why=(f"Organic revenue ${actual_org:,.0f}M landed {dev:+.1f}% versus the "
                 f"${f_org:,.0f}M forecast — just outside the {pi:.0%} band "
                 f"(≈{ratio_o:.1f}× the calibrated error radius).")))
    return out


# ------------------------------------------------------------------ assembly
def build_report(quarter: str = "FY2026Q3", df: pd.DataFrame | None = None,
                 backtest=None, run_bt: bool = True) -> AnomalyReport:
    """Scan the dataset + forecast outputs for discrepancies and anomalies.

    `backtest` (a BacktestReport) can be injected to reuse a cached run; otherwise
    one is computed when `run_bt` is True. Reconciliation + trend-band scans cover
    every quarter; the forecast-relative scan focuses on `quarter`.
    """
    from src.forecast import load
    df = load() if df is None else df
    df = df.sort_values("period_end_date").reset_index(drop=True)
    notes: list = []

    if backtest is None and run_bt:
        from src.backtest import run_backtest
        backtest = run_backtest(df=df)

    anomalies = []
    anomalies += _detect_reconciliation(df, notes)
    anomalies += _detect_trend_band(df, notes)
    anomalies += _detect_forecast_band(df, quarter, backtest, notes)
    anomalies.sort(key=lambda a: a.sort_key)

    n_unexpl = sum(a.status == "unexplained" for a in anomalies)
    notes.insert(0, (f"{len(anomalies)} item(s) flagged across "
                     f"{len(df)} quarters: {n_unexpl} unexplained (investigate), "
                     f"{len(anomalies) - n_unexpl} expected (explained by disclosure)."))
    return AnomalyReport(quarter=quarter,
                         quarters_scanned=df["fiscal_quarter"].tolist(),
                         anomalies=anomalies, notes=notes)


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "FY2026Q3"
    rep = build_report(q)
    print(f"=== Discrepancy & anomaly scan — focus {rep.quarter} "
          f"({len(rep.quarters_scanned)} quarters) ===\n")
    for n in rep.notes:
        print(" •", n)
    print()
    if rep.anomalies:
        with pd.option_context("display.width", 200, "display.max_columns", None,
                               "display.max_colwidth", 80):
            print(rep.to_frame().to_string(index=False))
        print("\n--- Why each was flagged ---")
        for a in rep.anomalies:
            tag = (f"EXPLAINED — {a.explanation}" if a.status == "explained"
                   else "UNEXPLAINED — investigate")
            print(f"\n[{a.severity.upper()}] {a.quarter} · {a.metric} ({a.detector}) "
                  f"[{tag}]\n    {a.why}")
    else:
        print("No anomalies flagged — every metric within its normal band and every "
              "actual inside the calibrated forecast band.")
    print(f"\nSaved {rep.save()}")

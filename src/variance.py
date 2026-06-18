"""Stage 3 — Automated variance analysis & attribution.

When an actual lands (or on a held-out quarter), explain the variance
automatically: vs our forecast AND vs management guidance, in $ and %, with
Favorable/Unfavorable flags, then DECOMPOSE it into components that reconcile to
the total — the key one being organic vs inorganic (isolating the CyberArk +
Chronosphere acquisition impact). Output is structured DATA, not prose; the
narrative comes later (Stage 5).

The centerpiece is a variance bridge that reconciles exactly:

    Forecast (organic)  →  + organic outperformance  →  + inorganic (M&A)  →  Actual

Run: python -m src.variance [FY2026Q3]
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import json
import sys
import numpy as np
import pandas as pd

from src import config
from src.forecast import run_forecast, load_conformal_errors
from src.fmt import fmt_money, fmt_pct


def _pct1(x: float) -> float:
    """One-decimal percent, rounded half-up (finance convention): 11.25 -> 11.3."""
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def favorability(actual: float, plan: float, higher_is_better: bool = True,
                 tol: float = 0.0) -> str:
    """F/U flag. Favorability FLIPS for cost lines (higher_is_better=False)."""
    diff = actual - plan
    if abs(diff) <= tol:
        return "On plan"
    good = diff > 0 if higher_is_better else diff < 0
    return "Favorable" if good else "Unfavorable"


def _row(label, actual, plan, higher_is_better=True, unit="$M"):
    var = actual - plan
    pct = var / plan * 100 if plan else np.nan
    return {
        "line": label, "actual": round(actual, 1), "plan": round(plan, 1),
        "variance": round(var, 1), "variance_pct": round(pct, 2),
        "flag": favorability(actual, plan, higher_is_better), "unit": unit,
    }


@dataclass
class VarianceReport:
    quarter: str
    summary: dict
    vs_guidance: pd.DataFrame
    vs_forecast: pd.DataFrame
    bridge: pd.DataFrame
    segment_attribution: pd.DataFrame
    driver_attribution: pd.DataFrame
    notes: list = field(default_factory=list)

    def save(self, path=None):
        path = path or (config.DATA / "variance_report.json")
        payload = {
            "quarter": self.quarter, "summary": self.summary, "notes": self.notes,
            "vs_guidance": self.vs_guidance.to_dict("records"),
            "vs_forecast": self.vs_forecast.to_dict("records"),
            "bridge": self.bridge.to_dict("records"),
            "segment_attribution": self.segment_attribution.to_dict("records"),
            "driver_attribution": self.driver_attribution.to_dict("records"),
        }
        path.write_text(json.dumps(payload, indent=2, default=float))
        return path


def forecast_for(df: pd.DataFrame, quarter: str):
    """Organic forecast for `quarter`, trained only on data strictly before it."""
    idx = df.index[df["fiscal_quarter"] == quarter][0]
    train = df.iloc[: idx]  # everything before the quarter
    res = run_forecast(df=train, horizon=1, conformal_errors=load_conformal_errors())
    assert res.future_quarters[0] == quarter, (res.future_quarters[0], quarter)
    return res


def build_report(quarter: str = "FY2026Q3", df: pd.DataFrame | None = None) -> VarianceReport:
    from src.forecast import load
    df = load() if df is None else df
    row = df[df["fiscal_quarter"] == quarter].iloc[0]
    i = df.index[df["fiscal_quarter"] == quarter][0]
    prior = df.iloc[i - 1]

    actual_total = float(row["revenue_total"])
    inorganic = float(row["inorganic_revenue"])
    actual_organic = float(row["revenue_organic"])

    # Management guidance for this quarter was issued in the PRIOR quarter's release.
    g_lo = float(prior["guidance_revenue_next_q_low"])
    g_hi = float(prior["guidance_revenue_next_q_high"])
    g_mid = (g_lo + g_hi) / 2

    # Our model's organic forecast for this quarter (trained only on the past).
    res = forecast_for(df, quarter)
    f_organic = float(res.total_point[0])
    f_product = float(res.segments["revenue_product"].point[0])
    f_subscription = float(res.segments["revenue_subscription"].point[0])

    # ---- Variance vs management guidance (total reported revenue) ----
    vs_guidance = pd.DataFrame([
        _row("Total revenue vs guidance midpoint", actual_total, g_mid),
        _row("Total revenue vs guidance low", actual_total, g_lo),
        _row("Total revenue vs guidance high", actual_total, g_hi),
    ])

    # ---- Variance vs our forecast, split organic vs inorganic ----
    vs_forecast = pd.DataFrame([
        _row("Organic revenue vs forecast", actual_organic, f_organic),
        _row("Total revenue vs forecast (organic basis)", actual_total, f_organic),
    ])

    # ---- The bridge: forecast (organic) -> actual (total), reconciles exactly ----
    organic_beat = actual_organic - f_organic
    bridge = pd.DataFrame([
        {"step": "Forecast (organic)", "amount": round(f_organic, 1), "kind": "start"},
        {"step": "Organic outperformance", "amount": round(organic_beat, 1),
         "kind": "favorable" if organic_beat >= 0 else "unfavorable"},
        {"step": "Inorganic (CyberArk + Chronosphere)", "amount": round(inorganic, 1),
         "kind": "inorganic"},
        {"step": "Actual (total reported)", "amount": round(actual_total, 1), "kind": "end"},
    ])

    # ---- Segment attribution (raw beat by segment; inorganic unallocated) ----
    seg = pd.DataFrame([
        _row("Product revenue vs forecast", float(row["revenue_product"]), f_product),
        _row("Subscription & support vs forecast", float(row["revenue_subscription"]), f_subscription),
    ])

    # ---- Driver attribution: which leading indicator moved, organic vs inorganic ----
    def driver(name, col, inorg_col):
        cur, prev = float(row[col]), float(prior[col])
        chg = cur - prev
        inorg = float(row.get(inorg_col, 0) or 0)
        org = chg - inorg
        return {
            "driver": name, "prior": round(prev, 1), "current": round(cur, 1),
            "change": round(chg, 1), "change_pct": round(chg / prev * 100, 1),
            "inorganic_part": round(inorg, 1), "inorganic_pct": _pct1(inorg / prev * 100),
            "organic_part": round(org, 1), "organic_pct": _pct1(org / prev * 100),
            "unit": "$M",
        }
    driver_attr = pd.DataFrame([
        driver("RPO (backlog)", "rpo", "inorganic_rpo"),
        driver("NGS ARR", "ngs_arr", "inorganic_ngs_arr"),
    ])

    # ---- Timing vs permanent (inferred) ----
    notes = [
        f"Bridge reconciles: {f_organic:.1f} + {organic_beat:.1f} (organic beat) + "
        f"{inorganic:.1f} (inorganic) = {actual_total:.1f}.",
        "Inorganic revenue is PERMANENT/structural (ongoing acquired businesses: "
        "CyberArk identity security + Chronosphere observability).",
        "Organic outperformance tagged likely-permanent (run-rate), but timing vs "
        "permanent can't be fully separated without internal bookings data.",
        f"Guidance was issued {prior['fiscal_quarter']} — AFTER CyberArk closed "
        "(Feb 11, 2026) — so it already embedded the acquisitions; the vs-guidance "
        "beat is mostly execution, not the acquisition itself.",
        "Segment beats are raw: the $%.0f M inorganic revenue is not split by segment "
        "in disclosure, so it inflates both Product and Subscription variances." % inorganic,
    ]

    summary = {
        "actual_total": actual_total, "actual_organic": actual_organic,
        "inorganic": inorganic,
        "forecast_organic": round(f_organic, 1),
        "guidance_midpoint": round(g_mid, 1),
        "vs_guidance_$": round(actual_total - g_mid, 1),
        "vs_guidance_%": round((actual_total - g_mid) / g_mid * 100, 2),
        "vs_guidance_flag": favorability(actual_total, g_mid),
        "organic_beat_$": round(organic_beat, 1),
        "inorganic_share_of_beat_%": round(
            inorganic / (actual_total - f_organic) * 100, 1) if actual_total != f_organic else None,
    }

    return VarianceReport(quarter, summary, vs_guidance, vs_forecast, bridge,
                          seg, driver_attr, notes)


def plain_bottom_line(rep: "VarianceReport") -> str:
    """A one-line, non-technical summary built ONLY from computed values (so it
    passes the no-hallucination verifier). Used at the top of the Variance tab."""
    s = rep.summary
    beat = s["actual_total"] - s["forecast_organic"]          # total vs our forecast
    verb = "beat" if beat >= 0 else "missed"
    ob_str = fmt_money(s["organic_beat_$"])                 # e.g. $50M (verifier-parseable)
    out = f"Revenue {verb} our forecast by {fmt_money(abs(beat))}"
    share = s.get("inorganic_share_of_beat_%")
    if s["inorganic"] and share is not None and beat:
        out += (f", but {fmt_pct(share)} of that was the CyberArk acquisition — organically "
                f"we were on target ({ob_str} vs forecast)")
    else:
        out += f" — all organic ({ob_str} vs forecast)"
    g = s["vs_guidance_$"]
    out += (f". Versus guidance, {fmt_money(abs(g))} {'ahead' if g >= 0 else 'behind'} "
            f"({fmt_pct(s['vs_guidance_%'], signed=True)}).")
    return out


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "FY2026Q3"
    rep = build_report(q)
    print(plain_bottom_line(rep), "\n")
    print(f"=== Variance report — {rep.quarter} ===\n")
    s = rep.summary
    print(f"Actual total {s['actual_total']:,.0f}  (organic {s['actual_organic']:,.0f} "
          f"+ inorganic {s['inorganic']:,.0f})")
    print(f"vs guidance midpoint {s['guidance_midpoint']:,.0f}: "
          f"{s['vs_guidance_$']:+,.0f} ({s['vs_guidance_%']:+.1f}%)  {s['vs_guidance_flag']}")
    print(f"vs forecast (organic) {s['forecast_organic']:,.0f}: organic beat "
          f"{s['organic_beat_$']:+,.0f}; inorganic = {s['inorganic_share_of_beat_%']:.0f}% "
          f"of the total beat vs forecast\n")
    print("--- Variance bridge (reconciles to actual) ---")
    print(rep.bridge.to_string(index=False))
    print("\n--- Segment attribution ---")
    print(rep.segment_attribution.to_string(index=False))
    print("\n--- Driver attribution (leading indicators) ---")
    print(rep.driver_attribution.to_string(index=False))
    print("\n--- Notes ---")
    for n in rep.notes:
        print(" •", n)
    print(f"\nSaved {rep.save()}")

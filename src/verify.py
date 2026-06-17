"""Number-verification harness — operationalizes the HARD no-hallucination rule.

The LLM (Stage 5 brief, chat answers) is only ever allowed to *narrate* computed
figures. This module is the guard that proves it did: it parses every dollar
amount and percentage out of generated text and cross-checks each against a
"source of truth" set assembled from the computed pipeline (financials,
forecast, variance). Any figure that doesn't match a real computed value within
tolerance is a VIOLATION — the brief is rejected and regenerated.

This turns the spec's guardrail into a tested, demonstrable feature (see the
negative test: a deliberately corrupted number is caught).
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import numpy as np
import pandas as pd

from src import config

# $3,002 million | $3.0 billion | $388M | $2,564 | 27.1% | +2.0% | -1.9%
_MONEY = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s?(billion|bn|million|mm|m|b)?\b", re.IGNORECASE)
_PCT = re.compile(r"([-+]?\d+(?:\.\d+)?)\s?%")


def _to_millions(num: float, unit: str | None) -> float:
    u = (unit or "").lower()
    if u in ("billion", "bn", "b"):
        return num * 1000
    return num  # million / m / mm / bare $ already in $M context


def parse_money(text: str) -> list[tuple[str, float]]:
    out = []
    for m in _MONEY.finditer(text):
        val = float(m.group(1).replace(",", ""))
        out.append((m.group(0), _to_millions(val, m.group(2))))
    return out


def parse_pct(text: str) -> list[tuple[str, float]]:
    return [(m.group(0), float(m.group(1))) for m in _PCT.finditer(text)]


def _add(s: set, *vals):
    for v in vals:
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            s.add(round(float(v), 1))


def _add_variance_facts(money: set, pct: set, quarter: str, df) -> None:
    """Fold the variance decomposition figures for `quarter` into the source of
    truth so the chat agent (which works off the dataset-wide set) can narrate the
    variance read — guidance midpoint, the beat, the inorganic share — verifiably."""
    from src.variance import build_report
    s = build_report(quarter, df=df).summary
    _add(money, s["actual_total"], s["actual_organic"], s["inorganic"],
         s["forecast_organic"], s["guidance_midpoint"], s["vs_guidance_$"],
         s["organic_beat_$"])
    _add(pct, s["vs_guidance_%"])
    if s.get("inorganic_share_of_beat_%") is not None:
        _add(pct, s["inorganic_share_of_beat_%"])


def _add_anomaly_facts(money: set, pct: set, quarter: str, df) -> None:
    """Fold the discrepancy/anomaly figures into the source of truth so the chat
    agent and brief can NARRATE flagged anomalies and still pass verification.
    Skips the backtest (run_bt=False) — narrated anomalies are about the focus
    quarter, whose forecast-relative check needs no walk-forward run."""
    from src.anomaly import build_report as anomaly_report
    rep = anomaly_report(quarter, df=df, run_bt=False)
    for a in rep.anomalies:
        if a.unit == "$M":
            _add(money, a.observed, a.expected, a.observed - a.expected)
        else:
            _add(pct, a.observed, a.expected)
        _add(pct, a.deviation_pct)


def build_source_of_truth(quarter: str = "FY2026Q3") -> dict:
    """Assemble the allowed money ($M) and percentage values for `quarter`."""
    from src.forecast import load
    from src.variance import build_report
    df = load()
    row = df[df["fiscal_quarter"] == quarter].iloc[0]
    i = df.index[df["fiscal_quarter"] == quarter][0]
    prior = df.iloc[i - 1]
    yago = df.iloc[i - 4] if i >= 4 else None
    rep = build_report(quarter, df=df)

    money: set[float] = set()
    pct: set[float] = set()

    # Reported actuals + prior quarter
    for r in (row, prior):
        _add(money, r["revenue_total"], r["revenue_product"], r["revenue_subscription"],
             r["revenue_organic"], r["inorganic_revenue"], r["rpo"], r["ngs_arr"],
             r["guidance_revenue_next_q_low"], r["guidance_revenue_next_q_high"],
             r.get("inorganic_rpo", 0), r.get("inorganic_ngs_arr", 0))
        _add(pct, r["non_gaap_op_margin"])
    # Variance report numbers (forecast, bridge, segment & driver attribution)
    s = rep.summary
    _add(money, s["actual_total"], s["actual_organic"], s["inorganic"],
         s["forecast_organic"], s["guidance_midpoint"], s["vs_guidance_$"], s["organic_beat_$"])
    _add(pct, s["vs_guidance_%"])
    if s.get("inorganic_share_of_beat_%") is not None:
        _add(pct, s["inorganic_share_of_beat_%"])
    for b in rep.bridge.to_dict("records"):
        _add(money, b["amount"])
    for seg in rep.segment_attribution.to_dict("records"):
        _add(money, seg["variance"]); _add(pct, seg["variance_pct"])
    for d in rep.driver_attribution.to_dict("records"):
        _add(money, d["prior"], d["current"], d["change"], d["inorganic_part"], d["organic_part"])
        _add(pct, d["change_pct"])
    # YoY growth %s (commonly cited in narrative)
    if yago is not None:
        for col in ("revenue_total", "rpo", "ngs_arr"):
            if pd.notna(row[col]) and pd.notna(yago[col]) and yago[col]:
                _add(pct, round((row[col] - yago[col]) / yago[col] * 100, 1))
    # Forecast band for the next quarters
    from src.forecast import run_forecast, load_conformal_errors
    fc = run_forecast(df=df[df["period_end_date"] <= row["period_end_date"]],
                      conformal_errors=load_conformal_errors())
    _add(money, *fc.total_point.tolist(), *fc.total_low.tolist(), *fc.total_high.tolist())
    _add(pct, config.PREDICTION_INTERVAL * 100)  # the 80% band
    # Stage 3.5 anomaly figures (so a narrated anomaly stays verifiable)
    _add_anomaly_facts(money, pct, quarter, df)

    return {"money": money, "pct": pct, "quarter": quarter}


def build_dataset_facts() -> dict:
    """Union of allowed money/pct across the WHOLE dataset — used by the chat
    agent, which can ask about any quarter. Built directly from financials +
    forecast (cheap; no per-quarter variance recompute)."""
    from src.forecast import load, run_forecast, load_conformal_errors
    df = load()
    money: set[float] = set()
    pct: set[float] = set()
    for _, r in df.iterrows():
        _add(money, r["revenue_total"], r["revenue_product"], r["revenue_subscription"],
             r["revenue_organic"], r["inorganic_revenue"], r["rpo"], r["ngs_arr"],
             r["billings"], r["guidance_revenue_next_q_low"], r["guidance_revenue_next_q_high"],
             r.get("inorganic_rpo", 0), r.get("inorganic_ngs_arr", 0))
        _add(pct, r["non_gaap_op_margin"])
    # YoY revenue growth for every quarter
    rev = df.set_index("fiscal_quarter")["revenue_total"]
    for i in range(4, len(df)):
        a, b = df["revenue_total"].iloc[i], df["revenue_total"].iloc[i - 4]
        if b:
            _add(pct, round((a - b) / b * 100, 1))
    fc = run_forecast(df=df, conformal_errors=load_conformal_errors())
    _add(money, *fc.total_point.tolist(), *fc.total_low.tolist(), *fc.total_high.tolist())
    _add(pct, config.PREDICTION_INTERVAL * 100)
    # Variance + anomaly figures for the focus quarter, so the chat agent can
    # narrate "what drove the beat?" and "is anything anomalous?" verifiably.
    focus = (df[df["inorganic_revenue"] > 0]["fiscal_quarter"].iloc[-1]
             if (df["inorganic_revenue"] > 0).any() else df["fiscal_quarter"].iloc[-1])
    _add_variance_facts(money, pct, focus, df)
    _add_anomaly_facts(money, pct, focus, df)
    return {"money": money, "pct": pct, "quarter": "ALL"}


def _matches(claim: float, allowed: set[float], rel: float, absol: float) -> bool:
    return any(abs(claim - v) <= max(absol, rel * max(abs(claim), abs(v))) for v in allowed)


@dataclass
class Violation:
    raw: str
    value: float
    kind: str  # 'money' | 'pct'


def verify_text(text: str, facts: dict,
                money_rel: float = 0.015, pct_abs: float = 0.6) -> list[Violation]:
    """Return numeric claims in `text` that don't match any computed value.

    money: matched within max($1M, 1.5% relative) to absorb legitimate rounding
    (e.g. "$3.0 billion" for 3,002). pct: matched within 0.6 absolute points.
    """
    violations = []
    for raw, val in parse_money(text):
        if not _matches(val, facts["money"], money_rel, 1.0):
            violations.append(Violation(raw, val, "money"))
    for raw, val in parse_pct(text):
        if not _matches(val, facts["pct"], 0.0, pct_abs):
            violations.append(Violation(raw, val, "pct"))
    return violations


def verify_brief(text: str, quarter: str = "FY2026Q3") -> tuple[bool, list[Violation]]:
    facts = build_source_of_truth(quarter)
    v = verify_text(text, facts)
    return (len(v) == 0, v)


if __name__ == "__main__":
    facts = build_source_of_truth("FY2026Q3")
    print(f"Source-of-truth for FY2026Q3: {len(facts['money'])} money values, "
          f"{len(facts['pct'])} percentages.")
    good = ("Total revenue was $3,002 million (organic $2,614M plus $388M from "
            "CyberArk and Chronosphere), beating guidance of $2,943M by 2.0%.")
    bad = "Total revenue was $3,500 million, up 99% — a blowout quarter."
    print("\nClean brief violations:", verify_text(good, facts))
    print("Corrupted brief violations:", [v.raw for v in verify_text(bad, facts)])

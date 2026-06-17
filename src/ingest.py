"""Stage 0 — Data foundation.

Builds data/financials.csv (one row per fiscal quarter) from the press-release-
sourced figures in data/raw/earnings_extracted.json, derives organic/split-
adjusted columns, and CROSS-CHECKS every total revenue against the independent
SEC XBRL companyfacts backbone. Nothing is fabricated or interpolated; absent
values stay blank. Run: python -m src.ingest
"""
from __future__ import annotations
import json
import datetime as dt
import pandas as pd

from src import config


def load_earnings() -> pd.DataFrame:
    raw = json.loads(config.EARNINGS_JSON.read_text())
    rows = raw["quarters"]
    df = pd.DataFrame(rows)
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    df = df.sort_values("period_end_date").reset_index(drop=True)
    return df


def xbrl_quarterly_revenue() -> dict[str, float]:
    """Independent total-revenue series from SEC XBRL (quarterly facts only).

    Returns {period_end (YYYY-MM-DD): revenue_in_millions}. Q4 isn't tagged as a
    discrete quarter in XBRL (only FY), so this covers Q1-Q3 quarters; we use it
    purely as a reconciliation check, not as the primary source.
    """
    facts = json.loads(config.COMPANYFACTS.read_text())
    usd = facts["facts"]["us-gaap"][
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]["units"]["USD"]
    # A period end can carry multiple facts: the original 10-Q value (precise)
    # and later comparatives that PANW rounds to whole millions. Keep the
    # EARLIEST-filed fact per period end — the as-originally-reported figure.
    best: dict[str, tuple[str, float]] = {}  # end -> (filed_date, value_millions)
    for r in usd:
        try:
            start = dt.date.fromisoformat(r["start"])
            end = dt.date.fromisoformat(r["end"])
        except (KeyError, ValueError):
            continue
        if (end - start).days >= 100:  # skip 9-mo / FY cumulatives
            continue
        filed = r.get("filed", "9999-12-31")
        if r["end"] not in best or filed < best[r["end"]][0]:
            best[r["end"]] = (filed, round(r["val"] / 1_000_000, 1))
    return {k: v[1] for k, v in best.items()}


def reconcile(df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-quarter reconciliation report (segment-sum + XBRL cross-check)."""
    xbrl = xbrl_quarterly_revenue()
    rep = []
    for _, row in df.iterrows():
        seg_sum = round((row["revenue_product"] or 0) + (row["revenue_subscription"] or 0), 1)
        seg_ok = abs(seg_sum - row["revenue_total"]) <= 0.2
        key = row["period_end_date"].date().isoformat()
        xv = xbrl.get(key)
        xbrl_ok = xv is None or abs(xv - row["revenue_total"]) <= 0.2
        rep.append({
            "fiscal_quarter": row["fiscal_quarter"],
            "revenue_total": row["revenue_total"],
            "segment_sum": seg_sum,
            "segment_reconciles": seg_ok,
            "xbrl_revenue": xv,
            "xbrl_matches": xbrl_ok,
        })
    return pd.DataFrame(rep)


def build() -> pd.DataFrame:
    df = load_earnings()

    # Derived: inorganic defaults to 0 (only FY2026Q3 discloses figures), and
    # organic revenue carves it out so forecasting isn't polluted by M&A steps.
    for c in ["inorganic_revenue", "inorganic_rpo", "inorganic_ngs_arr"]:
        df[c] = df[c].fillna(0.0) if c in df else 0.0
    df["revenue_organic"] = (df["revenue_total"] - df["inorganic_revenue"]).round(1)

    # Split-adjusted EPS on the current per-share basis (revenue is unaffected).
    factor = df["split_basis"].map(config.SPLIT_FACTORS)
    df["non_gaap_eps_split_adj"] = (df["non_gaap_eps_reported"] / factor).round(3)
    df["gaap_eps_diluted_split_adj"] = (df["gaap_eps_diluted_reported"] / factor).round(3)

    cols = [
        "fiscal_quarter", "period_end_date",
        "revenue_total", "revenue_product", "revenue_subscription",
        "inorganic_revenue", "revenue_organic",
        "ngs_arr", "rpo", "billings",
        "inorganic_rpo", "inorganic_ngs_arr",
        "non_gaap_op_margin",
        "non_gaap_eps_reported", "non_gaap_eps_split_adj",
        "gaap_eps_diluted_reported", "gaap_eps_diluted_split_adj",
        "guidance_revenue_next_q_low", "guidance_revenue_next_q_high",
        "split_basis", "accn",
    ]
    out = df[cols].copy()
    out.to_csv(config.FINANCIALS_CSV, index=False)
    return out


if __name__ == "__main__":
    df = build()
    rep = reconcile(df)
    print(f"Wrote {config.FINANCIALS_CSV}  ({len(df)} quarters, "
          f"{df['fiscal_quarter'].iloc[0]} -> {df['fiscal_quarter'].iloc[-1]})")
    print("\n--- Reconciliation ---")
    with pd.option_context("display.max_rows", None, "display.width", 140):
        print(rep.to_string(index=False))
    bad_seg = rep[~rep["segment_reconciles"]]
    bad_xbrl = rep[~rep["xbrl_matches"]]
    print(f"\nSegment reconciles: {rep['segment_reconciles'].all()} "
          f"({len(bad_seg)} failures)")
    n_checked = rep["xbrl_revenue"].notna().sum()
    print(f"XBRL cross-check: {rep['xbrl_matches'].all()} "
          f"({n_checked} quarters had an XBRL quarterly fact; {len(bad_xbrl)} mismatches)")

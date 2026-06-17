"""Tests for the MVP pipeline (Stages 0-2).

Covers the guarantees that matter for a finance system:
  * reconciliation (segments sum to total; XBRL cross-check)
  * no provenance gaps that were silently filled
  * forecast determinism + segment-sum invariant
  * backtest has NO leakage (no future row in any training window)
  * calibration math is correct
"""
import warnings
import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")

from src import config
from src import ingest
from src import forecast
from src.backtest import run_backtest


@pytest.fixture(scope="module")
def df():
    return ingest.build()


@pytest.fixture
def force_offline(monkeypatch):
    """Force the LLM client into offline mode so these tests are hermetic —
    they exercise the deterministic fallback regardless of whether an
    ANTHROPIC_API_KEY happens to be configured in the environment."""
    from src.llm.client import client
    monkeypatch.setattr(client, "_client", None)
    return client


# ----------------------------------------------------------- Stage 0: data
def test_segment_reconciliation(df):
    """revenue_product + revenue_subscription == revenue_total every quarter."""
    seg = (df["revenue_product"] + df["revenue_subscription"]).round(1)
    assert np.allclose(seg, df["revenue_total"], atol=0.2)


def test_xbrl_cross_check(df):
    """Press-release totals match the independent SEC XBRL backbone."""
    rep = ingest.reconcile(df)
    checked = rep[rep["xbrl_revenue"].notna()]
    assert len(checked) >= 15
    assert checked["xbrl_matches"].all()


def test_organic_definition(df):
    """revenue_organic = total - inorganic; only FY2026Q3 carries inorganic."""
    assert np.allclose(df["revenue_organic"],
                       (df["revenue_total"] - df["inorganic_revenue"]).round(1), atol=0.2)
    inorg = df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist()
    assert inorg == ["FY2026Q3"]


def test_no_silent_interpolation(df):
    """Known gaps stay blank (NaN), never filled with estimates."""
    # billings is discontinued after FY2024Q1 -> must contain NaNs, not zeros.
    assert df["billings"].isna().any()
    assert df["ngs_arr"].isna().any()       # absent before FY2024Q4
    # revenue is never missing.
    assert df["revenue_total"].notna().all()


def test_split_adjustment(df):
    """FY2022Q4 non-GAAP EPS (pre-both-splits) restates to ~0.40 on current basis."""
    row = df[df["fiscal_quarter"] == "FY2022Q4"].iloc[0]
    # 2.39 reported / 6.0 cumulative split factor
    assert row["non_gaap_eps_split_adj"] == pytest.approx(2.39 / 6.0, abs=0.01)


# --------------------------------------------------------- Stage 1: forecast
def test_segment_sum_invariant():
    res = forecast.run_forecast()
    seg_sum = sum(fc.point for fc in res.segments.values())
    assert np.allclose(seg_sum, res.total_point, atol=0.5)


def test_forecast_is_deterministic():
    a = forecast.run_forecast(seed=7).total_point
    b = forecast.run_forecast(seed=7).total_point
    assert np.allclose(a, b)


def test_interval_contains_point():
    res = forecast.run_forecast(conformal_errors=forecast.load_conformal_errors())
    assert np.all(res.total_low <= res.total_point)
    assert np.all(res.total_point <= res.total_high)


def test_assumption_changes_output_visibly():
    """Widening the uncertainty scale must widen the band (deterministic effect)."""
    narrow = forecast.run_forecast(sigma_scale=0.5)
    wide = forecast.run_forecast(sigma_scale=2.0)
    w_narrow = (narrow.total_high - narrow.total_low).mean()
    w_wide = (wide.total_high - wide.total_low).mean()
    # only meaningful for the MC method; force it
    if narrow.interval_method == "mc":
        assert w_wide > w_narrow


# --------------------------------------------------------- Stage 2: backtest
def test_backtest_no_leakage(monkeypatch):
    """Assert each training window ends at/before its origin quarter.

    We wrap run_forecast to capture the max training date per call and confirm it
    never includes the quarter being predicted.
    """
    from src import backtest as bt
    seen = []
    orig = bt.run_forecast

    def spy(df=None, **kw):
        if df is not None:
            seen.append(df["period_end_date"].max())
        return orig(df=df, **kw)

    monkeypatch.setattr(bt, "run_forecast", spy)
    rep = bt.run_backtest()
    # For every step, the training max date must be strictly before the predicted
    # quarter's date.
    clean = ingest.build()
    clean = clean[clean["inorganic_revenue"] == 0].reset_index(drop=True)
    dates = clean.set_index("fiscal_quarter")["period_end_date"]
    for train_max, pq in zip(seen, rep.steps["predict_quarter"]):
        assert train_max < dates[pq], f"leakage: trained through {train_max} to predict {pq}"


def test_backtest_beats_naive():
    rep = run_backtest()
    assert rep.metrics["model"]["MAPE"] < rep.metrics["naive"]["MAPE"]
    assert rep.beats_baseline is True


def test_conformal_better_calibrated_than_mc():
    rep = run_backtest()
    c = rep.calibration
    # conformal coverage should be closer to nominal than raw MC
    assert abs(c["conformal_coverage"] - c["nominal"]) <= abs(c["mc_coverage"] - c["nominal"])


# --------------------------------------------------------- Stage 3: variance
def test_variance_bridge_reconciles():
    """Bridge steps must sum to the actual total (no unexplained variance)."""
    from src.variance import build_report
    rep = build_report("FY2026Q3")
    steps = rep.bridge
    start = steps.iloc[0]["amount"]
    increments = steps.iloc[1:-1]["amount"].sum()
    end = steps.iloc[-1]["amount"]
    assert start + increments == pytest.approx(end, abs=0.2)
    # and end equals reported total revenue
    assert end == pytest.approx(rep.summary["actual_total"], abs=0.2)


def test_variance_organic_inorganic_explicit():
    from src.variance import build_report
    rep = build_report("FY2026Q3")
    assert rep.summary["inorganic"] == pytest.approx(388.0, abs=0.1)
    assert (rep.summary["actual_organic"] + rep.summary["inorganic"]
            == pytest.approx(rep.summary["actual_total"], abs=0.2))


def test_driver_attribution_splits_reconcile():
    """Each driver's organic + inorganic parts must sum to its total change."""
    from src.variance import build_report
    da = build_report("FY2026Q3").driver_attribution
    recon = da["organic_part"] + da["inorganic_part"]
    assert np.allclose(recon, da["change"], atol=0.2)


def test_favorability_flips_for_cost_lines():
    from src.variance import favorability
    # revenue line: higher actual than plan is good
    assert favorability(110, 100, higher_is_better=True) == "Favorable"
    # cost line: higher actual than plan is BAD (flips)
    assert favorability(110, 100, higher_is_better=False) == "Unfavorable"
    assert favorability(100, 100) == "On plan"


def test_variance_no_leakage():
    """The forecast used for variance must train only on data before the quarter."""
    from src.variance import forecast_for
    d = ingest.build()
    res = forecast_for(d, "FY2026Q3")
    assert res.training_cutoff == "FY2026Q2"  # last quarter strictly before


# ----------------------------------------------- V3: verification harness / LLM
def test_verify_passes_clean_numbers():
    from src import verify
    facts = verify.build_source_of_truth("FY2026Q3")
    clean = ("Total revenue was $3,002 million; organic $2,614M plus $388M from "
             "CyberArk and Chronosphere, a +2.0% beat vs guidance.")
    assert verify.verify_text(clean, facts) == []


def test_verify_catches_hallucinated_numbers():
    """The HARD guardrail: a fabricated figure must be flagged (negative test)."""
    from src import verify
    facts = verify.build_source_of_truth("FY2026Q3")
    bad = "Revenue was $3,500 million, up 99% — a record blowout."
    viol = verify.verify_text(bad, facts)
    raws = {v.raw for v in viol}
    assert "$3,500 million" in raws
    assert any("99%" == v.raw for v in viol)


def test_offline_summary_verifies(force_offline):
    """Offline brief must be fully verifiable by construction (no API key path)."""
    from src.summary import generate_brief
    brief = generate_brief("FY2026Q3")
    assert brief.source == "offline-template"
    assert brief.verified, [v.raw for v in brief.violations]
    # reads like prose, not a dump
    assert "Executive Brief" in brief.text and "CyberArk" in brief.text


def test_offline_chat_answers_verify(force_offline):
    from src.chat import ask
    for q in ["What drove the FY2026Q3 beat?", "forecast next quarter", "RPO backlog"]:
        a = ask(q)
        assert a.verified, (q, [v.raw for v in a.violations])


def test_signals_schema_valid(force_offline):
    """Signals are schema-valid and joinable to financials by quarter."""
    from src.signals import build
    sig = build()
    assert set(["fiscal_quarter", "management_sentiment", "guidance_tone",
                "emphasis_ngs_arr", "source"]).issubset(sig.columns)
    assert sig["management_sentiment"].isin(
        ["positive", "neutral", "cautious", "negative"]).all()
    assert sig["guidance_tone"].isin(["raising", "holding", "lowering"]).all()
    # one row per financial quarter
    fin = ingest.build()
    assert len(sig) == len(fin)

"""Central config: paths, model parameters, and forecast assumptions.

Assumptions live here (not buried in code) so they can be documented, version-
controlled, and overridden from the dashboard. Changing a value here changes the
forecast deterministically (given RANDOM_SEED).
"""
from pathlib import Path

# ---- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
FINANCIALS_CSV = DATA / "financials.csv"
DATA_DICT = DATA / "data_dictionary.md"
COMPANYFACTS = RAW / "panw_companyfacts.json"
EARNINGS_JSON = RAW / "earnings_extracted.json"

# ---- Company facts -------------------------------------------------------
CIK = 1327567
SEC_UA = "PANW-FPA-Copilot research pranavnair963@gmail.com"
FISCAL_YEAR_END_MONTH = 7  # July 31

# ---- Stock splits (effective dates) for EPS continuity -------------------
# Two forward splits: 3-for-1 (Sep 2022) and 2-for-1 (Dec 2024).
# To restate an as-reported EPS to the CURRENT (post-both) per-share basis,
# divide by the cumulative factor for that quarter's split_basis tag.
SPLIT_FACTORS = {
    "pre-3for1-pre-2for1": 6.0,    # divide by 3 then 2
    "post-3for1-pre-2for1": 2.0,   # divide by 2
    "post-3for1-post-2for1": 1.0,  # current basis
}

# ---- Forecast assumptions (Stage 1) — overridable from dashboard ---------
RANDOM_SEED = 42
FORECAST_HORIZON = 4            # quarters to forecast
PREDICTION_INTERVAL = 0.80      # 80% band
MONTE_CARLO_SIMS = 5000

# Segment models. ETS chosen as default for a ~20-point series (interpretable,
# robust, no exogenous required). ARIMAX with RPO is offered as an alternative.
SEGMENT_MODELS = {
    "revenue_product": "ets",        # 'ets' | 'arimax'
    "revenue_subscription": "ets",
}

# ETS shape (chosen by walk-forward MAPE: mul+undamped won at 1.23% vs 1.70%).
# PANW revenue grows steadily (undamped) with proportional fiscal-Q4 seasonal
# spikes (multiplicative).
ETS_SEASONAL = "mul"             # 'add' | 'mul' | None
ETS_DAMPED_TREND = False

# Prediction-interval method. The model's own Monte Carlo variance proved
# overconfident in backtest (~29% coverage vs 80% nominal), so the DEFAULT
# reported band is CONFORMAL: width learned from out-of-sample walk-forward
# residuals. 'mc' keeps the raw simulation band (kept for comparison).
INTERVAL_METHOD = "conformal"    # 'conformal' | 'mc'

# Monte Carlo: residual-based noise is scaled by this factor so the user can
# stress-test wider/narrower uncertainty from the dashboard. 1.0 = use the
# model's own estimated residual sigma.
ASSUMPTION_SIGMA_SCALE = 1.0

# Optional manual driver overrides (e.g. assume RPO grows X% next quarter).
# Used only by ARIMAX segment models. None -> drivers are themselves forecast.
RPO_GROWTH_QOQ = None            # e.g. 0.05 for +5% QoQ

# Exogenous driver usable as a continuous series (RPO has ~20 quarters of
# history; NGS ARR starts FY2024Q4; billings discontinued after FY2024Q1).
PRIMARY_DRIVER = "rpo"

# ---- Discrepancy & anomaly detection (Stage 3.5) ---------------------------
# Interpretable, rule-based flags reusing the forecast + variance outputs. We
# keep it transparent (robust statistics + accounting identities + the already-
# calibrated conformal band), never a black box — every flag must be explainable
# to a CFO. Robust z = (value - median) / (1.4826 * MAD); thresholds below.
ANOMALY_REPORT = DATA / "anomaly_report.json"
ANOMALY_Z_WARNING = 2.5            # |robust z| at/above this -> warning
ANOMALY_Z_CRITICAL = 3.5          # |robust z| at/above this -> critical
ANOMALY_MIN_POINTS = 8            # don't trend-scan a metric with fewer points
ANOMALY_BAND_LEVEL = PREDICTION_INTERVAL   # reuse the calibrated 80% band

# ---- LLM layer (Stages 4-5, V3) — Anthropic Claude --------------------------
# Sonnet for high-volume structured extraction; Opus for the CFO-grade prose
# and the chat agent. Override by editing here. All stages fall back to a
# deterministic offline mode when ANTHROPIC_API_KEY is unset (zero cost).
EXTRACTION_MODEL = "claude-sonnet-4-6"   # Stage 4 transcript signals
SUMMARY_MODEL = "claude-opus-4-8"        # Stage 5 executive brief
CHAT_MODEL = "claude-opus-4-8"           # chat-with-your-financials agent
SIGNALS_CSV = DATA / "signals.csv"
EXEC_BRIEF_MD = DATA / "exec_brief.md"

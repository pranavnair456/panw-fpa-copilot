# PANW AI FP&A Copilot

An end-to-end, AI-augmented **Financial Planning & Analysis** system built on Palo Alto Networks (PANW) public financial data. It runs the FP&A loop — **forecast → validate → variance → signal → executive summary** — pairing interpretable machine learning with an LLM layer, surfaced in an interactive Streamlit dashboard. Every input number traces to an SEC filing, and the LLM is only ever allowed to *narrate* computed figures, never invent them. This repo is a portfolio project for an "AI Financial Analyst" role; it's built to demonstrate real FP&A understanding, predictive modeling, modern AI tooling, and the maturity to deploy AI responsibly around financial numbers.

> **Status:** Complete — all 6 stages shipped. **Stage 0 (data) · 1 (forecast) · 2 (backtest) · 3 (variance) · 4 (transcript signals) · 5 (LLM exec summary) + dashboard**, plus three differentiators: a **number-verification harness**, a **chat-with-your-financials agent**, and **one-click brief export**. The LLM layer (Stages 4–5 + chat) uses Anthropic Claude when `ANTHROPIC_API_KEY` is set, and a deterministic offline mode otherwise — so the whole project runs and is tested at zero cost.

## What each stage does

| Stage | Module | Does |
|---|---|---|
| 0 · Data | `src/ingest.py` | Builds a 21-quarter, fully-sourced dataset from SEC 8-K earnings releases, cross-checked against the SEC XBRL API. |
| 1 · Forecast | `src/forecast.py` | Driver-based, segment-level revenue forecast (ETS) wrapped in a Monte Carlo layer → an 80% prediction interval (fan chart). |
| 2 · Backtest | `src/backtest.py` | Walk-forward validation: accuracy vs naive baselines & management guidance, plus interval calibration (conformal). |
| 3 · Variance | `src/variance.py` | Automated variance vs forecast & guidance; reconciling bridge (forecast → organic beat → inorganic → actual), segment & driver attribution. |
| 4 · Signals | `src/signals.py` | Schema-validated LLM extraction of management signals (sentiment, guidance tone, emphasis) → `signals.csv`. |
| 5 · Summary | `src/summary.py` | LLM-drafted CFO executive brief — numbers passed in, never invented; **gated by `src/verify.py`**. |
| ★ Guard | `src/verify.py` | Number-verification harness: cross-checks every figure in LLM output vs the computed source of truth. |
| ★ Chat | `src/chat.py` | Chat-with-your-financials agent — answers only from computed data, routed through the verifier. |
| 6 · Dashboard | `app/dashboard.py` | Streamlit UI — 6 tabs (Forecast, Backtest, Variance, Signals, Exec Summary, Chat). |

## Headline results (MVP)

- **Data integrity:** 21 quarters (FY2021Q3–FY2026Q3); two independent sources (press release + SEC XBRL) agree to the dollar; segment revenue reconciles to total every quarter.
- **Forecast accuracy:** model **MAPE 1.23%**, beating a naive baseline (8.92%) by **86%**; on par with a strong seasonal-naive (1.00%) and management guidance (0.94%) — reported honestly.
- **Calibration:** the model's own Monte Carlo bands were overconfident (43% coverage vs 80% target); **conformal intervals restore calibration to 86%**.
- **Timely real-world hook:** PANW's ~$25B **CyberArk** acquisition closed Feb 2026, adding ~$388M inorganic revenue to FY2026Q3 — the dataset isolates it, and the model's *organic* forecast for that held-out quarter lands within ~2% of actual.
- **Variance insight (Stage 3):** the FY2026Q3 beat decomposes to **89% acquisition (M&A) vs our forecast**, but a modest **+2% organic execution beat vs guidance** (which already embedded the deal) — a reconciling bridge and driver attribution (RPO +$1.8B / NGS ARR +$1.6B acquired) make it explicit.
- **Responsible AI (V3):** the LLM exec brief and chat agent narrate *only* computed figures; the **number-verification harness mechanically rejects any hallucinated number** (proven by a negative test — `$3,500M`/`99%` are caught). The guardrail is a tested feature, not a promise.

## Honest design tradeoffs

- **Small sample → simple models.** ~20 quarterly points means interpretable ETS, not deep learning (which would overfit). Documented in `LEARNING.md`.
- **No hallucinated numbers.** The LLM layer (V3) narrates only pre-computed figures; a verification harness will cross-check every number in generated text against the source-of-truth.
- **Provenance everywhere.** `data/data_dictionary.md` ties every field to a filing URL; gaps are left blank, never interpolated.
- **Honesty about limits.** The model doesn't beat management guidance, and one held-out quarter is a boundary miss — both reported, not hidden.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m src.ingest      # Stage 0: build + reconcile data/financials.csv
python -m src.forecast    # Stage 1: probabilistic forecast
python -m src.backtest    # Stage 2: walk-forward validation report
python -m src.variance    # Stage 3: variance bridge + attribution (default FY2026Q3)
python -m src.signals     # Stage 4: transcript signals -> signals.csv
python -m src.summary     # Stage 5: verified CFO exec brief
python -m src.verify      # number-verification harness demo (clean vs corrupted)
python -m src.chat "What drove the FY2026Q3 beat?"   # chat agent
pytest -q                 # 22 tests incl. the no-hallucination negative test

# Optional — live Claude for Stages 4-5 + chat (otherwise deterministic offline mode):
export ANTHROPIC_API_KEY=sk-ant-...

streamlit run app/dashboard.py   # interactive 6-tab dashboard
```

## Repo layout

```
data/            financials.csv, data_dictionary.md, signals.csv, exec_brief.md, raw/ (SEC filings + extracted JSON)
src/             ingest, forecast, backtest, variance, signals, summary, verify, chat, config, llm/
app/dashboard.py Streamlit UI (6 tabs)
tests/           pytest suite (22 tests)
LEARNING.md      teaching log — explains every stage at 3 levels (fundamental/technical/financial)
```

## What I'd build next with production data

With an internal data warehouse instead of public quarterly filings, I'd move to **monthly** actuals with bookings/pipeline drivers (turning the RPO regression into a genuine leading-indicator model), feed the signal layer **full earnings-call transcripts** (incl. analyst Q&A) rather than press-release commentary, extend the number-verification harness to qualitative claims, add per-user auth, and deploy with a scheduled refresh that re-runs the whole pipeline on each earnings release.

---

*Built with Python, statsmodels, scikit-learn, Plotly, Streamlit, and the Anthropic Claude API. See `LEARNING.md` to understand every part from first principles.*

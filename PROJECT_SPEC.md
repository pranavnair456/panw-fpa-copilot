# PROJECT_SPEC.md — PANW AI FP&A Copilot

**Purpose:** An end-to-end, AI-augmented FP&A system built on Palo Alto Networks (PANW) public financial data. It runs the full FP&A loop — forecast → validate → variance → signal → executive summary — with machine learning and an LLM layer, surfaced in an interactive dashboard.

**Why it exists:** Portfolio project for an "AI Financial Analyst" role. It must demonstrate four things at once: (1) real FP&A understanding, (2) predictive modeling, (3) creative use of modern AI/LLM tooling, and (4) the maturity to deploy AI responsibly around financial numbers.

> **Note to the builder (Claude Code):** Build in the phase order in Section 9. Ship a working MVP (Phases 0–2 + dashboard) before adding later stages. Treat the guardrails in Section 8 as hard requirements, not suggestions.
>
> **Teaching requirement (do not skip):** The user is learning, not just shipping. Maintain a `LEARNING.md` (Section 13) and **update it at the end of every stage**. Explain what you built and why, at three levels — fundamental, technical, and financial — in plain language, assuming the reader is smart but new to the finance and ML concepts. Define jargon the first time it appears. This file is as important as the code.

---

## 1. Tech stack

- **Language:** Python 3.11+
- **Data:** `pandas`, `sqlite3` (or flat CSV), `numpy`
- **Modeling:** `statsmodels` (ARIMA/ARIMAX, ETS) and/or `prophet`, plus a custom Monte Carlo loop; `scikit-learn` for regression/metrics
- **LLM layer:** any chat-completions API (used in Stages 4–5 only)
- **Dashboard:** `streamlit`
- **Viz:** `plotly` or `matplotlib`
- **Testing:** `pytest`

## 2. Repository structure

```
panw-fpa-copilot/
├── data/
│   ├── raw/                # source files: transcripts, downloaded tables
│   ├── financials.csv      # the tidy quarterly dataset (Stage 0)
│   └── data_dictionary.md  # field definitions + source per column
├── src/
│   ├── ingest.py           # Stage 0: build the dataset
│   ├── forecast.py         # Stage 1: driver-based + Monte Carlo forecast
│   ├── backtest.py         # Stage 2: walk-forward validation
│   ├── variance.py         # Stage 3: variance + attribution
│   ├── signals.py          # Stage 4: transcript NLP signal extraction
│   ├── summary.py          # Stage 5: LLM executive summary (numbers passed in, never invented)
│   └── config.py           # paths, model params, assumptions
├── app/
│   └── dashboard.py        # Stage 6: Streamlit wrapper
├── tests/
├── requirements.txt
├── LEARNING.md             # teaching log: explains every stage at 3 levels (updated each phase)
└── README.md
```

## 3. Stage 0 — Data foundation

**Objective:** A clean, sourced quarterly dataset and a transcript corpus.

**Source:** PANW quarterly earnings releases (SEC Form 8-K, Exhibit 99.1) and the investor-relations transcript pages. Fiscal year ends **July 31** (Q1≈Oct, Q2≈Jan, Q3≈Apr, Q4≈Jul). Aim for the most recent ~16–20 quarters.

**Schema (`financials.csv`, one row per fiscal quarter):**
`fiscal_quarter, period_end_date, revenue_total, revenue_product, revenue_subscription, ngs_arr, rpo, billings, non_gaap_op_margin, non_gaap_eps, guidance_revenue_next_q` (add columns only if reliably sourced).

**Acceptance criteria:**
- Every numeric field traces to a specific 8-K in `data_dictionary.md`.
- No fabricated or interpolated values; gaps are left blank and noted.
- `revenue_product + revenue_subscription` reconciles to `revenue_total` each quarter.

**Guardrail:** ~16–20 data points is intentionally small. This constrains Stage 1 model choice — do not paper over it.

## 4. Stage 1 — Driver-based predictive forecast

**Objective:** Forecast the next 1–4 quarters of revenue at the segment level (product, subscription), using leading indicators as inputs, with an uncertainty range.

**Approach:**
- Forecast each segment separately, then sum to total.
- Use **interpretable** models (ETS / ARIMA / ARIMAX with `ngs_arr`, `rpo`, `billings` as exogenous inputs, or a simple driver regression). No deep learning — the sample is too small.
- Wrap point forecasts in a **Monte Carlo** layer (sample assumption distributions) to produce an 80% prediction interval.

**Outputs:** a forecast table (point + low/high per quarter) and a fan chart. Assumptions live in `config.py` and are overridable from the dashboard.

**Acceptance criteria:**
- Segment forecasts sum to the total forecast.
- Output includes a calibrated interval, not just a point.
- Changing an assumption changes the output deterministically and visibly.

## 5. Stage 2 — Backtesting & validation

**Objective:** Prove the forecast is trustworthy before anyone relies on it.

**Approach:**
- **Walk-forward:** train through quarter T, predict T+1, roll forward across all available quarters.
- Compare error (MAPE, RMSE) against a **naive baseline** (e.g., prior quarter × trailing growth) and, where available, against management guidance.
- **Calibration check:** do the 80% intervals contain the actual ~80% of the time?

**Outputs:** a validation report (printed + a dashboard tab): error table, a "beats naive baseline by X%" headline, and a calibration summary.

**Acceptance criteria:**
- Backtest runs without leakage (no future data in any training window).
- Report explicitly states whether the model beats the naive baseline and by how much.
- If it does **not** beat baseline, that is reported honestly, not hidden.

## 6. Stage 3 — Automated variance analysis & attribution

**Objective:** When an actual lands (or on a held-out quarter), compute and explain the variance automatically.

**Approach:**
- Variance vs. forecast **and** vs. management plan/guidance, in $ and %, with Favorable/Unfavorable flags (favorability flips for cost lines).
- **Decompose:** segment-level price/volume style split; driver attribution (which leading indicator moved); and **organic vs. inorganic** (isolate acquisition impact, e.g., CyberArk).
- Tag each driver **timing vs. permanent** where inferable.

**Outputs:** a variance bridge/waterfall (plan → drivers → actual) and a structured variance table.

**Acceptance criteria:**
- Decomposed components reconcile to the total variance.
- Organic vs. inorganic split is explicit.
- Output is data, not prose (prose comes in Stage 5).

## 7. Stage 4 — Transcript NLP signal layer

**Objective:** Turn earnings-call transcripts into structured forward-looking signals.

**Approach:**
- For each transcript, use the LLM to extract a structured record: management sentiment, guidance tone (raising/holding/lowering), confidence vs. hedging, and emphasis on key topics (NGS ARR, platformization, CyberArk, margin).
- Build a per-quarter signal scorecard. Optional analysis: plot a sentiment/tone signal against the **subsequent** revenue surprise to test predictive value.

**Outputs:** `signals.csv` (one structured row per quarter) and a signal-vs-surprise chart.

**Acceptance criteria:**
- Extraction returns consistent, schema-valid structured output per transcript.
- Signals are stored as data and can be joined to `financials.csv` by quarter.

## 8. Stage 5 — LLM executive summary

**Objective:** Auto-draft the CFO-ready narrative from the computed outputs — "data ingestion to executive summary."

**Approach:**
- The LLM receives the **already-computed** forecast, variance decomposition, and transcript signals, and writes a one-page brief.
- The prompt forbids inventing or altering any number; the model only narrates figures passed to it.

**Outputs:** a generated markdown brief: forecast + range, the variance story, the organic/inorganic read, the transcript signal, and what to watch.

**Acceptance criteria (HARD):**
- **No hallucinated numbers** — every figure in the summary matches a computed value. Add a verification step that cross-checks numbers in the output against the source dict.
- Reads like analyst prose, not a data dump.

## 9. Phased milestones

| Phase | Scope | Definition of done |
|---|---|---|
| **MVP** | Stages 0, 1, 2 + dashboard tab | A backtested, probabilistic forecast you can demo and tweak |
| **V2** | + Stage 3 | Automated variance + organic/inorganic decomposition |
| **V3** | + Stages 4, 5 | Transcript signals + auto-generated executive summary |

Ship each phase as a working slice before starting the next. An excellent MVP beats an unfinished full system.

## 10. Stage 6 — Dashboard (wrapper, built incrementally with each phase)

A Streamlit app with tabs added as phases complete: **Forecast** (fan chart + assumption sliders), **Backtest** (metrics + calibration), **Variance** (waterfall + table), **Signals** (scorecard + chart), **Summary** (the generated brief). Changing an assumption recalculates the forecast and bands live.

## 11. Cross-cutting principles (non-negotiable)

1. **No hallucinated numbers.** The LLM narrates computed figures; it never produces them.
2. **Interpretability over complexity.** Thin data → simple, explainable models. Document the choice.
3. **Validate before trust.** Nothing is "forecast" until it's backtested against a baseline.
4. **Provenance.** Every input number is sourced to a filing.
5. **Human in the loop.** The system drafts and flags; a human owns the judgment and the final narrative.
6. **Honesty about limits.** Report when the model underperforms; don't tune the story to look good.

## 12. README must include (for the demo)

A 4–5 sentence overview, a "what each stage does" map, the honest design tradeoffs (small sample → interpretable models; no-hallucinated-numbers guardrail), one screenshot per tab, and a one-paragraph "what I'd build next with production data" note.

## 13. LEARNING.md — the teaching log (first-class deliverable)

**Objective:** By the time the project is done, the user can explain *every* part of it from first principles — the finance, the math, and the code. This file is how that happens. It is written FOR the user, as a tutor would, and **updated at the end of each stage**.

**For each stage, LEARNING.md must explain it at three levels:**

1. **Fundamental (the intuition):** What problem does this stage solve and why does it matter, in plain English with an analogy if helpful. No jargon, or jargon immediately defined. Example target: "A backtest is like checking whether last year's weather forecast was actually right before you trust tomorrow's."
2. **Technical (the how):** The methods, models, and code. What algorithm/library was used and *why it was chosen over alternatives* (e.g., "ETS instead of an LSTM because we have 16 data points and an LSTM would overfit"). Walk through the key function. Define every ML term (MAPE, exogenous variable, calibration, walk-forward, Monte Carlo) the first time it appears.
3. **Financial (the meaning):** The finance concept behind the numbers. Define the FP&A and accounting terms (driver-based forecast, variance, organic vs. inorganic, ARR, RPO, P&L, operating margin) and explain what the output means to a CFO and why they'd care.

**Also include:**
- A running **glossary** at the bottom (term → one-line definition), appended to as new terms appear.
- For each stage, **3–5 "interview questions you should now be able to answer"** with brief model answers (e.g., "Why did you use a probability range instead of a point forecast?").
- Honest **"what this does NOT do / limitations"** notes per stage, so the user can speak to tradeoffs.

**Acceptance criteria:**
- Every stage shipped has a corresponding LEARNING.md section before that stage is considered done.
- No unexplained jargon: any finance or ML term used in code or summary appears in the glossary.
- A motivated reader with no finance/ML background could read LEARNING.md alone and understand what the system does and why.

**Style:** teach, don't document. Short paragraphs, concrete examples, analogies over formality. Assume an intelligent reader who is new to these specific domains.

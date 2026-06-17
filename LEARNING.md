# LEARNING.md — the teaching log

This file exists so that by the end of the project you can explain **every** part of it from first principles — the finance, the math, and the code. It's written *for you*, like a tutor would, and updated at the end of each stage. Each stage is explained at three levels: **Fundamental** (the intuition), **Technical** (the how), and **Financial** (what it means to a CFO). Jargon is defined the first time it appears and collected in the glossary at the bottom.

> Status: **MVP shipped** — Stage 0 (data), Stage 1 (forecast), Stage 2 (backtest) + dashboard. V2/V3 sections will be appended as they land.

---

## Stage 0 — Data foundation

### Fundamental (the intuition)
Before you can forecast anything, you need clean, trustworthy numbers. This stage builds a spreadsheet of Palo Alto Networks' (PANW) quarterly results — 21 quarters of revenue, backlog, profitability — where **every single number can be traced back to an official government filing**. Think of it like a chef sourcing ingredients: a great dish starts with knowing exactly where each ingredient came from. If a number can't be sourced, we leave the cell blank rather than guess. That discipline is the whole foundation of trusting everything built on top.

### Technical (the how)
- **Two independent sources, cross-checked.** Primary figures come from PANW's quarterly **earnings press releases** (SEC Form **8-K**, Exhibit 99.1). We *separately* pull total revenue from the **SEC XBRL API** (a machine-readable database of everything companies file) and assert the two agree. All 16 quarters that exist in both sources match to the dollar. Two sources agreeing is far stronger evidence than one.
- **Extraction with provenance.** `src/ingest.py` reads `data/raw/earnings_extracted.json` — figures pulled verbatim from each press release, each with a short quote proving the value (the "evidence" field). `data/data_dictionary.md` maps every column to its source filing URL.
- **Reconciliation as a test.** `revenue_product + revenue_subscription == revenue_total` is checked for all 21 quarters (`test_segment_reconciliation`). If a number were mis-transcribed, this test would catch it.
- **Derived columns, honestly labeled.** `revenue_organic = revenue_total − inorganic_revenue`. **inorganic** revenue (from acquisitions) is recorded *only* where the company explicitly disclosed it — exactly one quarter, FY2026Q3, where PANW said "$388 million from CyberArk and Chronosphere."
- **Stock splits.** PANW split its stock twice (3-for-1 in 2022, 2-for-1 in 2024). A split changes per-share numbers (EPS) but not the business. We keep the as-reported EPS *and* a `split_adjusted` version on today's share basis, so the EPS series is comparable over time. Revenue is unaffected by splits.

### Financial (the meaning)
- **Revenue segments:** PANW splits revenue into **Product** (firewalls/hardware, lumpy, seasonal) and **Subscription and support** (recurring software — the part investors prize). Recurring revenue is more valuable because it's predictable.
- **RPO (Remaining Performance Obligations):** contracted revenue not yet recognized — essentially *backlog*. It's a GAAP-defined leading indicator of future revenue.
- **NGS ARR (Next-Gen Security Annual Recurring Revenue):** PANW's headline growth metric — annualized recurring revenue from its modern security products. A non-GAAP operational metric.
- **Why provenance matters in FP&A:** a CFO will not act on a number they can't trace to a filing. "Where did this come from?" is the first question in any finance review; this dataset answers it for every cell.

### What this stage does NOT do (limits)
- Only captures metrics PANW disclosed. `billings` stops after FY2024Q1 (the company de-emphasized it) and `ngs_arr` starts FY2024Q4 — these gaps are real and left blank, never filled.
- We don't reconstruct the product/subscription split of the $388M acquisition revenue (PANW didn't disclose it), so we treat the contaminated quarter carefully in Stage 1 rather than inventing a split.

### Interview questions you should now be able to answer
1. *How do you know your data is right?* Two independent sources (press release + SEC XBRL) cross-checked to the dollar, plus a segment-sum reconciliation test on every quarter.
2. *Why leave cells blank instead of interpolating?* Interpolation invents data; in finance an invented number that looks real is worse than an honest gap.
3. *What's the difference between RPO and revenue?* RPO is contracted-but-not-yet-recognized backlog (future); revenue is what's recognized this period.
4. *Why separate organic from inorganic revenue?* Acquisitions create one-time step-changes that would distort a growth model; isolating them keeps the underlying trend honest.

---

## Stage 1 — Driver-based probabilistic forecast

### Fundamental (the intuition)
We predict the next 1–4 quarters of revenue — but instead of a single guessed number, we produce a **range** with a stated confidence ("80% chance revenue lands between X and Y"). A single-number forecast pretends to a precision nobody has; a range tells the truth about uncertainty. We forecast the two revenue segments separately (they behave differently) and add them up.

### Technical (the how)
- **Why a simple model?** We have ~20 data points. A neural network (LSTM, etc.) has thousands of parameters and would **overfit** — memorize noise and fail on new data. With little data you use *interpretable* models with few parameters. We use **ETS (Exponential Smoothing)**: it tracks three things — the current **level**, the **trend** (steady growth), and the **seasonality** (PANW's Q4 is always the biggest quarter). We picked the multiplicative-seasonal, undamped-trend variant because it won the walk-forward test (1.23% error vs 1.70% for alternatives).
- **Forecasting organic revenue.** Training excludes the acquisition-contaminated quarter (FY2026Q3), so the CyberArk/Chronosphere jump doesn't bend the trend. A nice side effect: the model's prediction for that held-out quarter becomes a *free out-of-sample test*.
- **Monte Carlo for the range.** A **Monte Carlo** simulation runs the future many times (5,000 paths) with random noise drawn from the model's error, then reads the 10th and 90th percentiles as the 80% band. Segment paths are summed path-by-path so the total's uncertainty combines correctly. A dashboard slider scales this uncertainty so you can stress-test.
- **Determinism.** Given a fixed random seed, the forecast is identical every run (`test_forecast_is_deterministic`) — essential for a tool people audit.

### Financial (the meaning)
- A **driver-based forecast** ties revenue to its operational *drivers* (here, segment dynamics and backlog/RPO) rather than just extrapolating a line — it's how real FP&A teams build budgets.
- The **prediction interval** is the part a CFO actually cares about for planning: the downside case drives how much cash cushion or hiring restraint you need. A point forecast hides exactly that.

### What this stage does NOT do (limits)
- It forecasts *organic* revenue. To predict total *reported* revenue going forward you'd add an explicit acquisition-contribution layer (a Stage 3 / production extension).
- ETS uses revenue's own history; it doesn't yet *regress on* RPO as a driver (we tested an RPO regression — it didn't beat ETS on this small sample, so we kept the simpler model and documented it).
- 20 points is genuinely little; the model is honest but not magic.

### Interview questions you should now be able to answer
1. *Why not deep learning?* 20 data points; an LSTM would overfit. Model complexity must match data size.
2. *Why a range instead of a point?* Honesty about uncertainty, and the downside case is what planning actually needs.
3. *What is Monte Carlo doing here?* Simulating many noisy futures to empirically derive an 80% band instead of trusting a formula.
4. *How did you handle the CyberArk acquisition?* Forecast organic revenue (exclude the contaminated quarter from training); add acquisition impact separately.

---

## Stage 2 — Backtesting & validation

### Fundamental (the intuition)
Never trust a forecast you haven't tested on the past. **Backtesting** is checking whether last year's forecast was actually right before you rely on tomorrow's. We replay history: stand at each past quarter, forecast the next one using *only* data available then, and compare to what really happened. Two questions: is it *accurate* (close to actual)? and is its *confidence honest* (do the 80% bands really contain the truth 80% of the time)?

### Technical (the how)
- **Walk-forward (rolling origin), no leakage.** Train through quarter T, predict T+1, roll forward. The cardinal sin is **leakage** — letting the model see the future. A test (`test_backtest_no_leakage`) spies on every training window and asserts its latest date is strictly before the quarter being predicted.
- **Beat a baseline.** A forecast is only useful if it beats a dumb rule. Our model's **MAPE** (Mean Absolute Percentage Error) is **1.23%**, vs **8.92%** for a naive "last quarter × recent growth" baseline — an **86% improvement**. We *also* report two tougher benchmarks honestly: a seasonal-naive rule (1.00%) and **management's own guidance** (0.94%). The model roughly matches these — expected for a backlog-heavy business where management has great visibility — so we don't oversell it.
- **Calibration + conformal fix.** The model's own Monte Carlo bands were **overconfident**: they contained the actual only **43%** of the time, not 80%. The fix is **conformal prediction** — set the band width from the model's *actual out-of-sample errors* rather than its optimistic internal variance. That lifts coverage to **86%** — well-calibrated. This is the single most important methodological idea in the MVP: *trust demonstrated error, not the model's self-assessment.*

### Financial (the meaning)
- **MAPE / RMSE** are the standard scorecards for forecast accuracy. Lower is better; MAPE is in percent (easy to communicate), RMSE in dollars (penalizes big misses).
- **Beating guidance is hard** for PANW because RPO (backlog) gives management strong forward visibility — a genuinely instructive finding: for some businesses the *uncertainty quantification* and *decomposition* are the value-add, not beating the point forecast.
- A **calibrated interval** is what lets a CFO size a risk: an "80% band" that's actually right 43% of the time would badly understate downside.

### What this stage does NOT do (limits)
- Only ~7 walk-forward quarters — calibration estimated on a small sample is itself uncertain. The conformal finite-sample correction helps, but more history would tighten it.
- The held-out FY2026Q3 organic check came in at **−1.9%, just outside** the 80% band (boundary miss) — reported honestly, not tuned away. The model was chosen on walk-forward MAPE, *not* by peeking at that quarter.

### Interview questions you should now be able to answer
1. *What is walk-forward backtesting and why not a random train/test split?* Time series have order; you must only ever train on the past, or you leak the future.
2. *What does "the model beats the baseline by 86%" mean — and what's the catch?* 1.23% vs 8.92% MAPE on the naive baseline; the catch is that seasonal-naive and guidance are far tougher and the model only matches them.
3. *What is calibration and how did you fix it?* Whether an 80% band is right 80% of the time; fixed via conformal intervals set from out-of-sample residuals (43% → 86% coverage).
4. *Where does the model lose, and why is that OK to show?* It doesn't beat guidance, and one held-out quarter is a boundary miss — honesty about limits is the whole point (you can't trust a tool that only reports its wins).

---

## Stage 3 — Automated variance analysis & attribution (V2)

### Fundamental (the intuition)
A forecast tells you what you *expected*; **variance analysis** explains why reality differed. When the actual number lands, a CFO's first question is "why?" — and "we beat by $59M" is useless without the breakdown. This stage answers automatically: how much of the beat was the *core business* doing better (organic), how much was *acquisitions* (inorganic), and which *leading indicators* moved. Think of it like a doctor explaining not just that your weight changed, but how much was muscle vs water vs fat — the decomposition is the insight.

### Technical (the how)
- **Two comparisons.** We compute variance vs **our forecast** and vs **management guidance**, in dollars and percent, each flagged **Favorable/Unfavorable**. Favorability *flips* for cost lines (more revenue = good; more cost = bad) — handled by a `higher_is_better` switch (`test_favorability_flips_for_cost_lines`).
- **A bridge that reconciles.** The centerpiece is a waterfall:
  `Forecast (organic) 2,564 → +50 organic outperformance → +388 inorganic (CyberArk + Chronosphere) → Actual 3,002`.
  The steps sum *exactly* to the actual (`test_variance_bridge_reconciles`) — a variance analysis with an unexplained residual is a broken one.
- **Driver attribution.** For each leading indicator we split the quarter-over-quarter change into organic vs inorganic using PANW's own disclosures: RPO rose $2.4B (of which **$1.8B was CyberArk/Chronosphere**), NGS ARR rose $1.8B (**$1.6B acquired**). So the indicator surge was mostly M&A — consistent with the revenue beat being ~89% inorganic. The split reconciles to the total change (`test_driver_attribution_splits_reconcile`).
- **No leakage here either.** The forecast used as the "plan" is trained only on quarters strictly before the actual (`test_variance_no_leakage`).
- **Output is data, not prose.** Tables + a structured JSON (`data/variance_report.json`); the English narrative is deferred to Stage 5, where an LLM will narrate these *computed* numbers.

### Financial (the meaning)
- **Variance vs plan** is the heartbeat of FP&A — every monthly/quarterly close is a variance review. Splitting **price/volume/mix** is the classic technique; for a software business without unit data, the honest analog is **segment mix** (how much each segment drove the variance), which is what we report.
- **Organic vs inorganic** is exactly how analysts judge "real" growth: a beat that's 89% acquisition tells a very different story than an organic one. The subtle, sophisticated read here: vs our forecast the beat was mostly M&A, but vs *guidance* (issued after CyberArk closed, so already including it) the +2% beat was **organic execution** — two correct answers to "did they beat?" depending on the baseline.
- **Timing vs permanent:** acquired revenue is permanent/structural; a one-off pull-forward would be timing. Knowing which determines whether you raise the run-rate.

### What this stage does NOT do (limits)
- No true price/volume split (no unit/ASP data for software) — we do segment-mix attribution and say so.
- The $388M inorganic revenue isn't split by segment in disclosure, so segment-level beats are raw (inflated by M&A); flagged in the notes.
- Timing vs permanent is partly inferred — internal bookings/pipeline data would make it definitive.

### Interview questions you should now be able to answer
1. *PANW beat — was it good?* Depends on the baseline: ~89% of the beat vs our forecast was the CyberArk/Chronosphere acquisition; vs guidance (which already embedded the deal) it was a ~$59M / +2% organic execution beat.
2. *What is a variance bridge and why must it reconcile?* A waterfall from plan to actual; if the pieces don't sum to the total, you've mis-attributed something.
3. *How did you separate organic from inorganic?* Used PANW's explicit disclosures ($388M revenue, $1.8B RPO, $1.6B NGS ARR from the acquisitions) and carried them as sourced columns.
4. *What does Favorable/Unfavorable mean and when does it flip?* Actual better than plan = Favorable; for cost lines the sign of "better" flips (lower is favorable).

---

## Stages 4 & 5 — Transcript signals + LLM executive summary (V3)

### Fundamental (the intuition)
The numbers tell you *what* happened; management's words hint at *what's coming*. **Stage 4** turns each quarter's earnings commentary into structured signals — is management upbeat or cautious? raising or lowering guidance? what are they emphasizing? **Stage 5** then has an AI write the one-page CFO brief from everything we computed. The crucial rule: the AI is a *writer, not a calculator* — it narrates numbers we already computed and is never allowed to make one up. A guard checks every figure before the brief is trusted.

### Technical (the how)
- **Structured extraction (Stage 4).** We ask Claude to read the commentary and return a *schema-valid* record (sentiment, guidance tone, confidence, topic-emphasis scores) using the SDK's `messages.parse` with a Pydantic schema — so the output is always valid, typed data, never free text we have to parse. Results land in `signals.csv`, joinable to the financials by quarter. We also test whether tone *predicts* the next quarter's revenue surprise (it's weak here — honestly reported).
- **The no-hallucination guard (`verify.py`) — the most important piece.** It parses every dollar amount and percentage out of generated text and checks each against a "source of truth" set built from the computed pipeline. Anything that doesn't match a real computed value (within a small rounding tolerance) is a **violation**. A negative test proves it works: feed it a brief containing `$3,500M` and `99%`, and both are caught.
- **Verified generation (Stage 5).** The LLM gets a FACTS block (the only numbers it may use) and writes the brief; `verify.py` checks it; if any figure is unverifiable, the violations are fed back and it regenerates. **Offline mode:** with no API key, a deterministic *template* brief is produced from the same numbers — it passes verification by construction, so everything runs and is tested at zero cost; the live Claude path activates when a key is set.
- **Chat agent (differentiator).** Natural-language Q&A answered *only* from the computed data, every answer routed through the same verifier — agentic AI under the same discipline.

### Financial (the meaning)
- **Sentiment / guidance tone** are the qualitative overlay analysts add to the quant: two companies can post the same number while one signals confidence and the other hedges.
- **"Data ingestion to executive summary"** is the FP&A dream — the analyst's manual write-up, automated, but with a hard integrity gate so a CFO can trust it. The verifier is what makes AI *deployable* around financial numbers: it converts "the model promised not to lie" into "we mechanically checked, and here's the proof."

### What this stage does NOT do (limits)
- Signal source is the **press-release management commentary**, not the full earnings-call transcript (which adds analyst Q&A) — chosen for clean provenance and reproducibility; full transcripts are the production upgrade.
- Offline heuristic signals are mechanical (e.g. guidance tone from a seasonal QoQ rule); the LLM path is richer. Each row tags its `source` so you always know which produced it.
- The verifier checks dollar amounts and percentages (where hallucination risk lives); it doesn't police every qualitative claim.

### Interview questions you should now be able to answer
1. *How do you stop an LLM from inventing financial numbers?* It only narrates a FACTS block of pre-computed values, and a verification harness mechanically cross-checks every figure against the computed source of truth, rejecting any mismatch.
2. *Why structured output for signal extraction?* Schema-validated output (`messages.parse` + Pydantic) guarantees typed, joinable data instead of free text you have to parse and might mis-read.
3. *What's the difference between Stage 4 and Stage 5?* Stage 4 extracts structured signals *from* text; Stage 5 generates *narrative* text from computed data — opposite directions, both bounded by the no-hallucination rule.
4. *How would you productionize this responsibly?* Human-in-the-loop (the system drafts and flags; a person owns the final narrative), provenance on every input, and the verifier as a hard gate before anything ships.

---

## Glossary

| Term | One-line definition |
|---|---|
| **8-K / Exhibit 99.1** | An SEC filing companies use to announce material events; the earnings press release is attached as Exhibit 99.1. |
| **XBRL** | A machine-readable tagging standard for financial filings; the SEC exposes it as a free API. |
| **GAAP / non-GAAP** | GAAP = official accounting rules; non-GAAP = company-adjusted figures (e.g. excluding stock comp) — useful but management-defined. |
| **Segment** | A slice of revenue reported separately; PANW uses Product vs Subscription & support. |
| **RPO** | Remaining Performance Obligations — contracted revenue not yet recognized (backlog); a leading indicator. |
| **NGS ARR** | Next-Gen Security Annual Recurring Revenue — PANW's headline annualized recurring-revenue metric. |
| **Billings** | Revenue + change in deferred revenue; an older cash-timing metric PANW de-emphasized. |
| **Organic vs inorganic** | Growth from the existing business vs growth bought via acquisition. |
| **ETS** | Exponential Smoothing — a forecasting model tracking level, trend, and seasonality. |
| **Seasonality** | A repeating within-year pattern (PANW's fiscal-Q4 revenue spike). |
| **Exogenous variable / driver** | An outside input fed into a model (e.g. RPO) to help predict the target. |
| **Monte Carlo** | Estimating an outcome's distribution by simulating it many times with random inputs. |
| **Prediction interval** | A range expected to contain the actual value with a stated probability (here 80%). |
| **Walk-forward / rolling origin** | Backtesting by repeatedly training on the past and predicting the next step. |
| **Leakage** | Accidentally letting a model see future/test data during training — inflates apparent accuracy. |
| **MAPE / RMSE** | Mean Absolute Percentage Error / Root Mean Squared Error — forecast accuracy scores. |
| **Naive baseline** | A trivial forecast (e.g. repeat last quarter) used as the bar a real model must clear. |
| **Calibration** | Whether stated confidence matches reality (does an 80% band contain the truth 80% of the time?). |
| **Conformal prediction** | Building prediction intervals from a model's actual out-of-sample errors, giving honest coverage. |
| **Stock split** | Dividing each share into more shares; changes per-share metrics (EPS) but not the business. |
| **Variance** | The difference between an actual result and a plan/forecast, in $ and %. |
| **Favorable / Unfavorable** | Whether a variance helps (F) or hurts (U); the sign of "good" flips for cost lines. |
| **Variance bridge / waterfall** | A chart decomposing plan→actual into additive components that must sum to the total. |
| **Price/volume/mix** | Classic split of a revenue variance into how much came from price, quantity, and product mix. |
| **Driver attribution** | Tying a variance to the underlying operational metric (driver) that moved. |
| **Timing vs permanent** | Whether a variance is a one-off shift in timing or a lasting change to the run-rate. |
| **Sentiment analysis** | Inferring tone/attitude (positive, cautious, …) from text. |
| **Guidance tone** | Whether management is raising, holding, or lowering its forward outlook. |
| **Structured output** | Forcing an LLM to return data matching a fixed schema (typed fields) rather than free text. |
| **Pydantic** | A Python library for defining and validating typed data schemas. |
| **Hallucination** | An LLM stating something false or invented as if it were fact. |
| **Verification harness** | Code that mechanically checks generated text against a source of truth (here, every figure vs computed values). |
| **Source of truth** | The authoritative set of correct values everything else is checked against. |
| **Human in the loop** | A workflow where AI drafts/flags but a person owns the final judgment. |

# LEARNING.md — the teaching log

> This file teaches you the whole system from zero — the finance, the code, and the math — so you can explain every part from first principles. **Read it top to bottom the first time.** **Parts 1–3** are a guided tour of *what the system is and how it flows*, assuming no finance or programming background. **Part 4** is the detail on each stop, at three levels — **Fundamental** (the intuition) / **Technical** (the how) / **Financial** (what it means to a CFO). **Part 5** is the glossary. Every new word is defined the first time it appears.
>
> Status: **complete** — all stages shipped (data → forecast → backtest → variance → anomaly → signals → summary), plus a no-hallucination verifier, a chat agent, and a 7-tab dashboard.

---

## Part 1 — Start here: what is this?

Picture a junior financial analyst whose whole job is one company's quarterly numbers. Every three months the company publishes results, and the analyst must: (1) **predict** next quarter, (2) **explain** why the latest quarter came in above or below plan, (3) **flag** anything that looks wrong or surprising, and (4) **write the one-page summary** the CFO takes to the board. This project is software that does all four — for **Palo Alto Networks (PANW)**, a large cybersecurity company — using only its **public financial filings**, under one ironclad rule: **it never makes up a number.** When it writes English, it may only repeat figures it actually computed, and a separate piece of code mechanically checks that.

### What you need to know first (the absolute basics)
- **Revenue** — the money a company earns from selling its products and services in a period. The headline number everyone watches.
- **A quarter** — a three-month chunk of a company's financial ("fiscal") year. PANW's fiscal year ends July 31, so quarters are labeled like `FY2026Q3` (third quarter of fiscal 2026).
- **A forecast** — a prediction of a future number; here, next quarter's revenue.
- **A model** — a small math formula whose settings are *learned* from past data so it can predict the future. "**Training**" a model = fitting those settings to history.
- **A CSV / table** — a spreadsheet-like file of rows and columns. Here, one row per quarter.
- **A Python module** — one code file (e.g. `forecast.py`) that does one job. The system is ~10 of them in the `src/` folder.
- **The dashboard** — the web page (built with a tool called *Streamlit*) that shows the results in tabs. It's what you actually look at.
- **An LLM (large language model)** — an AI like Claude that writes text. Here it only *narrates* (turns computed numbers into prose); it never calculates.

## Part 2 — The flow, end to end

### The map

Data flows left-to-right through the modules. Each module reads the previous output and writes the next. There is exactly **one loop** (the backtest measures the forecast's real errors and feeds them back to set its range width) and **one gate** (the verifier, which every AI-written sentence must pass).

```
  SEC filings  (8-K earnings press releases  +  XBRL machine-readable data)
        │   numbers hand-extracted, each with a quote proving it
        ▼
  ingest.py  (Stage 0) ── build + reconcile ──►  financials.csv   ← the one clean, sourced table
        │
        ├───►  forecast.py (Stage 1) ─────►  a revenue RANGE for next quarter
        │            ▲     │
        │  residuals │     │ (re-forecasts the past, over and over)
        │  set the   │     ▼
        │  band  ────┴──  backtest.py (Stage 2) ─►  "is the forecast trustworthy?"  + error history
        │
        ├───►  variance.py  (Stage 3)   ─►  WHY actual ≠ plan   (organic vs acquisition bridge)
        ├───►  anomaly.py   (Stage 3.5) ─►  WHAT looks off       (expected vs unexplained)
        └───►  signals.py   (Stage 4)   ─►  management TONE      (LLM reads the commentary)
                     │
   all computed ─────┴────►  summary.py (Stage 5) ─►  CFO brief (LLM writes the prose)
   numbers                                │
                                          ▼
                                     verify.py  ──  GATE: every $ and % in the AI's text
                                          │          must match a computed value, or it's rejected
                                          ▼
                              dashboard.py  /  chat.py   ──►  what you see and ask
```

### Follow one quarter's number through the system

The most concrete way to understand the flow is to follow a single real number — **FY2026Q3 revenue** — from filing to dashboard. (FY2026Q3 is special: it's the quarter PANW closed its ~$25B **CyberArk** acquisition, plus a smaller one, Chronosphere.)

1. **It starts as a filing.** PANW publishes an earnings press release (an SEC document called an **8-K**). It reports total revenue of **$3,002M** ($M = millions of dollars). A human copies that figure into `data/raw/earnings_extracted.json` *with a short quote proving it* — so every number is traceable to its source. (**Provenance** = being able to point to where a number came from.)

2. **`ingest.py` builds the clean table.** It reads that JSON and writes `data/financials.csv` — one tidy row per quarter. It also does two integrity checks: that the revenue **segments** (PANW splits revenue into "Product" and "Subscription") add up to the total, and that the total matches an independent government source (the SEC's **XBRL** database). Crucially, it computes **organic** revenue. PANW disclosed that **$388M** of the $3,002M came from the acquisitions (that's **inorganic** revenue — bought, not grown); the rest, **$2,614M**, is **organic** (the existing business). Separating them keeps an acquisition from masquerading as real growth.

3. **`forecast.py` predicts it — as a range.** The forecaster trains a simple, interpretable model called **ETS** (Exponential Smoothing — it tracks the current level, the trend, and the repeating yearly **seasonality**, e.g. PANW's big Q4) on the *organic* history only. It then runs a **Monte Carlo** simulation — playing the future out thousands of times with random noise — to produce not one number but an **80% prediction interval** (a range we're ~80% confident the answer falls in). Trained only on quarters *before* FY2026Q3, it forecast organic revenue of **$2,564M**, range ≈ **$2,515–2,613M**. The actual organic came in at **$2,614M** — just at the top edge, about +2%. A range, not a point, because a CFO plans around the downside.

4. **`backtest.py` proves the forecast is trustworthy.** Before you trust *tomorrow's* forecast, check whether *yesterday's* would have been right. **Backtesting** = stand at each past quarter, forecast the next using only data available then ("**walk-forward**"; never peeking at the future, which would be **leakage**), and score it. The model's average error (**MAPE**, mean absolute percentage error) is **1.23%** — versus **8.92%** for a dumb "repeat last quarter's growth" baseline. It also discovered the forecast's *own* range was over-confident (it covered the truth only 43% of the time, not 80%), and fixed it with **conformal** intervals — setting the range width from the model's *real* past errors, lifting coverage to **86%**. Those measured errors loop back into `forecast.py` — that's the one feedback arrow on the map.

5. **`variance.py` explains the result.** "We beat plan by $59M" is useless without *why*. It builds a **bridge** that reconciles exactly: forecast organic **$2,564M** → **+$50M** the organic business beat the forecast → **+$388M** the acquisitions → **$3,002M** actual. So versus our forecast, ~89% of the beat was the acquisition (M&A), not organic muscle — a very different story than a pure organic beat.

6. **`anomaly.py` flags what's worth a look.** It scans every quarter for things that look off — broken tie-outs, metrics jumping outside their normal band, actuals landing outside the trustworthy forecast range. FY2026Q3's total revenue is a big outlier versus the organic forecast, so it gets **flagged** — but then **labeled "expected,"** because we *know* the reason: the disclosed $388M acquisition. A genuine surprise with no known cause would be labeled "unexplained — investigate." Flagging *and* judging is the analyst's real skill.

7. **`signals.py` reads the words.** The numbers say *what* happened; management's commentary hints at *what's next*. The LLM reads the press-release narrative and extracts structured tags — sentiment, whether guidance is being raised or lowered, what they emphasized — so tone becomes trackable data.

8. **`summary.py` writes the brief, `verify.py` guards it.** The LLM receives a **FACTS block** (the only numbers it's allowed to use) and drafts a one-page CFO brief. Then **`verify.py`** reads the draft, pulls out every dollar amount and percentage, and checks each against the set of values we actually computed. If the AI wrote a number that isn't real, the brief is **rejected and regenerated**. That gate is what makes an AI safe to point at financial numbers.

9. **You see it on the dashboard, or just ask.** `dashboard.py` shows all of this in tabs; `chat.py` lets you ask in plain English ("what drove the Q3 beat?", "anything anomalous?") and answers only from the computed numbers, every figure run through the same verifier.

### What actually runs when you…

Each stage is also a command you can run on its own (see the `Makefile` / `README.md`). They read and write the files in `data/`:

| Command | What happens |
|---|---|
| `python -m src.ingest` | Reads the raw JSON → writes `data/financials.csv`; prints the reconciliation check. |
| `python -m src.forecast` | Trains ETS, simulates, prints the forecast table + the held-out FY2026Q3 check. |
| `python -m src.backtest` | Walk-forward test; prints accuracy + calibration; writes `data/backtest_report.json`. |
| `python -m src.variance` | Builds the bridge + attribution for a quarter; writes `data/variance_report.json`. |
| `python -m src.anomaly` | Runs the three detectors; prints ranked flags; writes `data/anomaly_report.json`. |
| `python -m src.signals` | Extracts management tone per quarter → `data/signals.csv`. |
| `python -m src.summary` | Drafts + verifies the CFO brief → `data/exec_brief.md`. |
| `python -m src.chat "…"` | Answers one natural-language question. |
| `streamlit run app/dashboard.py` | Opens the 7-tab dashboard, which calls all the functions above and caches the results. |

### How the pieces connect

- **`config.py` is the control panel.** Every assumption lives there, not buried in code: the file paths, the **random seed** (a fixed number that makes the random simulation repeat identically every run, so results are auditable), the 80% confidence level, which model each segment uses. Change a value there and the whole system changes — predictably.
- **`llm/client.py` is the on/off switch for the AI.** If an `ANTHROPIC_API_KEY` is set, the LLM stages use live Claude; if not, they fall back to deterministic **offline** versions (a template brief, a keyword-based chat). So the entire project runs, and is tested, for free — the AI is an upgrade, not a dependency.
- **The data dependencies** (which output feeds which) are exactly the arrows on the map: `financials.csv` feeds forecast/variance/anomaly/signals; `backtest_report.json`'s errors feed the forecast's range; everything feeds `verify.py`'s "allowed values" set, which gates `summary.py` and `chat.py`.
- The key functions you'll see named in Part 4: `run_forecast` (Stage 1), `run_backtest` (Stage 2), `forecast_for` and `build_report` (Stage 3 variance; `anomaly.py` also has a `build_report`), `verify_text` / `build_source_of_truth` (the gate).

## Part 3 — The big ideas that recur

These principles show up in almost every stage. Each one exists to serve the user (a CFO who has to *trust* and *act on* these numbers):

- **Provenance** — every input number traces to a specific filing. *Why a CFO cares:* "where did this come from?" is the first question in any finance review.
- **No leakage** — a forecast or backtest may only ever train on the past, never the future. *Why:* peeking at the answer makes a model look brilliant and then fail in real life.
- **A range, not a point** — outputs are intervals with a stated confidence. *Why:* the downside case is what drives how much cash cushion or hiring restraint you need.
- **Calibration** — an "80% range" should actually contain the truth ~80% of the time. *Why:* a range that's secretly only right 43% of the time badly understates risk.
- **No hallucinated numbers** — the LLM only narrates computed figures, and the verifier mechanically enforces it. *Why:* a confident, wrong number in a board brief is worse than no brief.
- **Interpretable models** — with little data we use simple, explainable math, not black-box deep learning. *Why:* a CFO must be able to ask "why did you predict that?" and get an answer.
- **Offline mode** — the whole thing runs without an API key. *Why:* reproducibility, zero cost, and no single point of failure for a demo.
- **Human in the loop** — the system drafts and flags; a person owns the final judgment. *Why:* AI is the analyst's leverage, not their replacement.

---

## Part 4 — Each stage, in depth (three levels)

The tour above is the map; below is the detail on each stop — **Fundamental** (the intuition), **Technical** (the how), and **Financial** (what it means to a CFO) — with the interview questions you should be able to answer and the honest limits of each stage.

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

## Stage 3.5 — Discrepancy & Anomaly Detection

### Fundamental (the intuition)
This is the **third thing the CFO-org AI team builds** (alongside forecasting and variance), and the POC was missing it. Think of it as a **smoke detector for the numbers**: it scans every metric and every forecast and raises a hand whenever something looks *off*. But a smoke detector that shrieks at toast is useless — so this one does the extra thing a good analyst does: it checks each alarm against what we already know and tells you whether there's a *known reason* (a candle) or *not* (a fire). A revenue jump the company already disclosed as an acquisition is **expected — explained**; a jump with no known cause is **unexplained — investigate**. That distinction is the whole point: the tool doesn't just flag, it adds judgment.

### Technical (the how)
Everything here is deliberately **interpretable** — three transparent detectors, no black box, because every flag has to be defensible to a CFO who asks "why did you flag that?"
- **Reconciliation / discrepancy checks** (`_detect_reconciliation`). Pure accounting identities: does `revenue_product + revenue_subscription` tie to `revenue_total`? does `organic + inorganic` tie to total? does our press-release figure match the independent **SEC XBRL** number? On the real data nothing fires (it already reconciles) — the detector exists to *catch a future mis-keyed number*, the everyday "tie-out" before anyone trusts a figure. (Tested by deliberately corrupting a segment value and confirming it's caught.)
- **Trend / seasonality band breaks** (`_detect_trend_band`). For each metric we compute a **robust z-score**: `z = (value − median) / (1.4826 · MAD)`, where **MAD** is the *median absolute deviation*. Why MAD instead of the ordinary standard deviation? On ~20 points, one big outlier inflates the std so much it *hides itself* (the alarm desensitizes to the very thing it's looking for); the median/MAD pair barely moves, so the outlier still stands out. We score each metric's **year-over-year growth** (not quarter-over-quarter) so PANW's huge fiscal-Q4 seasonal spike doesn't get flagged every single year — YoY compares like-with-like. Metrics with too few comparable points (NGS ARR: 4; margin: 7) are **honestly skipped**, not forced.
- **Forecast-band anomalies** (`_detect_forecast_band`). The "abnormally large variance vs forecast" case — and it reuses the work already done. An actual is anomalous if it lands **outside the calibrated conformal band** (the same 86%-coverage band from Stage 2). Because that band is calibrated to *demonstrated* error, "outside the band" is a statement you can trust, not the model's own optimistic variance. It draws on the leakage-free walk-forward steps for historical surprises, and on `forecast_for(df, q)` (trained strictly on prior quarters) for the focus quarter — so **no leakage** here either.
- **The explained/unexplained classifier.** After detection, a flag is labeled `explained` when a disclosure accounts for most of it — the FY2026Q3 total-revenue break is explained because **$388M of the $438M gap is the disclosed CyberArk + Chronosphere acquisition**, structural rather than a forecasting error. Severity (magnitude) and status (do we know why) are kept **orthogonal**: the dashboard sorts *unexplained* items to the top so a human looks at those first, while explained-but-large items are shown and de-emphasized.
- **Guardrails.** Output is structured data (`anomaly_report.json`); the WHY strings are deterministic templates, and their figures are folded into the verifier's source-of-truth (`verify._add_anomaly_facts`) so that when the chat agent or brief *narrates* an anomaly, the no-hallucination gate still holds. Deterministic (same input → identical list), so it's auditable.

### Financial (the meaning)
- A **discrepancy** is a data-integrity break (the segments don't tie out) — in FP&A this is caught at the *close*, before any analysis, because every downstream number inherits the error. An **anomaly** is a *result* that's surprising given history or plan — the trigger for the "why did this move?" investigation that variance analysis then answers.
- Why the **explained vs unexplained** split is the real value: a CFO doesn't want 50 alarms, they want the *one* that has no known cause. Auto-labeling the CyberArk-driven spike as "expected" and surfacing only the genuinely unexplained items is exactly the analyst judgment that makes the tool trustworthy instead of noisy — and it's the **bridge** competency: knowing what the FP&A user actually needs (signal, not noise).
- It also reinforces the project's honesty theme: the system flags its *own* forecast misses (e.g. the FY2024Q4 organic surprise, the FY2026Q3 boundary miss) rather than hiding them.

### What this stage does NOT do (limits)
- On ~20 points, the MAD itself is estimated from few observations, so the robust-z thresholds are rules of thumb, not guarantees — more history would sharpen them.
- It only scans the metrics we track; an anomaly in an un-modeled line (e.g. a specific cost item) wouldn't be seen.
- "Explained" relies on what the company *disclosed* (the $388M split). An undisclosed driver would show up as "unexplained" — which is the honest outcome, but means the label is only as good as the disclosure.
- It flags; it does not diagnose root cause. A flag is the start of the human's investigation, not the end.

### Interview questions you should now be able to answer
1. *Why a robust z-score (median/MAD) instead of a normal z-score?* With ~20 points, one outlier inflates the standard deviation enough to mask itself; median and MAD are resistant to outliers, so the anomaly still stands out.
2. *How do you avoid flagging seasonality as an anomaly?* Score year-over-year growth (same fiscal quarter), which compares like with like, instead of quarter-over-quarter, which would flag PANW's Q4 spike every year.
3. *What's the difference between a discrepancy and an anomaly?* A discrepancy is a data-integrity break (numbers don't reconcile); an anomaly is a surprising but internally-consistent result. Different detectors, different responses.
4. *Why label anomalies "explained" vs "unexplained"?* A CFO needs the one alarm with no known cause, not a wall of alerts; cross-checking each flag against disclosures (the $388M acquisition) separates expected events from things that genuinely need investigation — that's the analyst judgment the tool adds.
5. *How does anomaly detection stay within the no-hallucination guardrail?* The flags are computed (rule-based), the WHY text is templated from those computed numbers, and every figure is folded into the verifier's source-of-truth, so any narration of an anomaly is still mechanically checked.

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

## Built for the FP&A user — and the road to production

### Fundamental (the intuition)
The hardest part of this kind of work isn't the math — it's being the **bridge** between what's technically possible and what an FP&A team actually needs. An engineer can build a forecast; knowing that a CFO wants a *range because they plan around the downside* is the FP&A judgment. So the project now states, for every output, **who it's for, what decision it supports, and why it's built that way** — justified by user need, not by technique. That framing lives in one place (`src/framing.py`) and is rendered at the top of the dashboard, on each tab, and in the README, so it can't drift.

### Technical (the how)
- **One source of framing.** `framing.LENS` holds a `{who, decision, why}` entry per output; the dashboard renders it via `framing.caption(key)` and a test asserts every output is covered — the "justify by user need" rule is enforced, not aspirational.
- **Chat as the centerpiece.** The Q&A agent (`chat.py`) now routes plain-English questions across intents (forecast, the beat, **anomalies**, RPO, margin, segments, tone), answers with the quarter cited and the **source tagged** ("per the variance bridge", "the anomaly scan"), and is bounded by the same verifier. The live agent is fed the computed **variance read and anomaly flags** as context, and those figures are folded into the verifier's dataset-wide source-of-truth (`verify._add_variance_facts` / `_add_anomaly_facts`) so a narrated answer about the beat or an anomaly still passes the no-hallucination gate. Offline, a deterministic intent responder keeps the tab working at zero cost.
- **The POC→IT handoff.** `PRODUCTIONIZATION.md` documents what the team actually does next: hand the POC to IT to scale. It draws the line between **what stays** (the FP&A logic and the guardrails — the value) and **what gets rebuilt** (data feeds, orchestration, auth, hosting), and spells out live data contracts, the retraining/promotion gate, the MNPI security boundary around the LLM, and the load-bearing guardrails that must not be optimized away.

### Financial (the meaning)
- This is the competency the role prizes: **honesty about forecasts** (a calibrated range, flagged limits, anomalies labeled expected vs. unexplained) and **deep understanding of the data/context** (organic vs. inorganic, what a CFO does with each number). The reframe makes that explicit; the productionization note shows the maturity to ship it responsibly.

### Interview questions you should now be able to answer
1. *Why frame every feature by user need instead of technique?* Because the team's core value is being the bridge — knowing what fits the FP&A user. A range beats a point not because it's fancier, but because a CFO plans around the downside.
2. *What makes the chat agent safe to put in front of a non-technical exec?* It answers only from computed data, cites the quarter and source, and every figure is mechanically verified — a quick question can't become a quick mistake.
3. *What stays and what gets rebuilt when this hands off to IT?* The FP&A models and the guardrails (forecast/variance/anomaly/verifier) stay; the data feeds, orchestration, auth, and hosting get rebuilt. The guardrails are load-bearing and must survive the rewrite.

---

## The Source Data tab & the demo UX

### Fundamental (the intuition)
The demo opens on **Source Data** because the whole story is "from filings to a board brief," and trust starts with the data. This tab makes provenance *clickable*: pick any quarter and metric, and you see the **exact sentence from the SEC filing** that proves the number. It's the financial equivalent of showing your receipts — before anyone looks at a forecast, they can see the inputs are real and checked.

### Technical (the how)
- **A thin read-layer, not new data logic.** `src/provenance.py` only *surfaces* artifacts that already exist: the per-metric **evidence quotes** in `earnings_extracted.json`, the source-filing URLs parsed from `data_dictionary.md`, a **coverage matrix** (`df.notna()` per metric × quarter), and headline **quality stats** computed live via the existing `ingest.reconcile` (cross-source agreement + segment tie-out). No figures are recomputed.
- **What the tab renders:** a pipeline flow diagram (Sources → Extraction → Validation → Clean dataset → powers everything), a provenance table with a link to the actual 8-K, a coverage heatmap (gaps shown, never filled), a scrollable view of all 21 quarters, and the honesty callouts. It's pure data — **no LLM** — so it always works offline.

### Financial (the meaning)
- *"Where did this come from?"* is the first question in any finance review; this tab answers it for **every cell**. The data-quality panel (two independent sources agreeing to the dollar; segments reconciling every quarter) is exactly the **tie-out** a controller performs at close before trusting a number — here it's automated and visible.

## Why the UX is built this way (for a non-technical user)

The audience is an FP&A analyst or CFO-org exec with **zero ML background**, so the interface is designed to be understood cold:
- **Lead with the answer, hide the method.** Each tab opens with a plain-English **"Bottom line"** and the few numbers that matter as large cards; formulas, dense tables, and controls live in **"How this works" / "Show the detail"** expanders (*progressive disclosure*). Clean surface, depth on demand.
- **No bare jargon.** Every technical term (organic/inorganic, RPO, the 80% range, ETS, conformal, robust z-score) has a plain-English label and a one-sentence hover tooltip.
- **Charts over tables**, each with a one-line "how to read this" caption.
- **Palo Alto Networks brand theme**, with one careful rule: **brand orange is for branding only** (header, links, active tab, the non-semantic forecast line); **meaning** is carried by separate semantic colors — favorable **green**, unfavorable **red**, caution/expected **amber** — so a green/red number never gets confused with branding. This is the same "bridge" competency as the rest of the project: the tool fits the user, not the other way around.

### Chart clarity passes (Variance & Forecast tabs)

Two charts were tuned specifically so a non-technical viewer can't misread them:
- **Variance waterfall** — the organic-outperformance step is **green** (a real gain) and the acquisition step is **gray** (neither good nor bad), so the headline insight — *most of the beat was the acquisition* — is visible in the bar colors, not buried in labels. A dotted line marks management guidance, and the cards are grouped under **"vs our forecast"** and **"vs guidance"** subheaders so the two different baselines are never confused. The tab's one-line **bottom line** ("…~89% of that was the CyberArk acquisition…") is built from computed values and **passes the no-hallucination verifier** (a test enforces it). Detail-table columns use plain finance labels and the variance figures are tinted green/red by favorability.
- **Forecast chart** — the dashed forecast line now **continues from the last actual point** (instead of floating to the right), a faint **"forecast →"** boundary marks where history ends, the legend says **"Forecast (organic)"** with a note that acquisitions are added separately (so the \$2,564M organic forecast isn't misread against the \$3,002M reported total), and the headline quarter's point is **labeled on the line** so the card and the chart point are visibly the same. The y-axis stays from-zero (honest); only labels/colors changed.

## Glossary

| Term | One-line definition |
|---|---|
| **Revenue** | The money a company earns from selling its products/services in a period. |
| **Quarter** | A three-month slice of a company's fiscal year (e.g. `FY2026Q3`). |
| **Fiscal year** | A company's 12-month accounting year; PANW's ends July 31. |
| **CSV / table** | A rows-and-columns data file; here, one row per quarter. |
| **Python module** | A single code file doing one job (e.g. `forecast.py`); the system is ~10 of them in `src/`. |
| **Pipeline** | A chain of steps where each step's output feeds the next. |
| **Model / training** | A formula whose settings are *learned* ("trained") from past data to make predictions. |
| **Random seed** | A fixed number that makes a random simulation repeat identically each run, so results are auditable. |
| **Dashboard / Streamlit** | The interactive web page (built with the Streamlit library) that shows the results in tabs. |
| **LLM (large language model)** | An AI like Claude that writes text; here it only *narrates* computed numbers, never calculates. |
| **FACTS block** | The fixed list of computed numbers handed to the LLM as the only figures it is allowed to use. |
| **Provenance** | The traceable source of a number — which filing it came from. |
| **Evidence quote** | The verbatim sentence from a filing that proves a specific figure; stored per metric. |
| **Coverage map** | A grid showing which metrics were disclosed in which quarters; blanks are real gaps, never estimates. |
| **Data tie-out** | Checking that figures reconcile (segments sum to total; a second source agrees) before trusting them. |
| **Progressive disclosure** | UI principle: show the answer first, tuck the method/detail behind an expander. |
| **Semantic color** | Color used to carry meaning (favorable green / unfavorable red / caution amber), kept separate from brand color. |
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
| **Anomaly detection** | Automatically flagging data points or results that depart from their expected pattern. |
| **Discrepancy / reconciliation** | A break in an accounting identity (numbers that should tie out don't); reconciliation is the tie-out check. |
| **Robust z-score** | How many robust-sigmas a value sits from the median: `(value − median) / (1.4826 · MAD)`; resistant to outliers. |
| **MAD (median absolute deviation)** | The median of the absolute deviations from the median — an outlier-resistant measure of spread. |
| **Trend / control band** | The normal range a metric is expected to stay within; breaking it flags an anomaly. |
| **Severity vs status** | Severity = how unusual (info/warning/critical); status = whether we know why (explained/unexplained) — kept orthogonal. |
| **Explained vs unexplained anomaly** | A flag a disclosure accounts for (expected, e.g. an acquisition) vs one with no known cause (investigate). |
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

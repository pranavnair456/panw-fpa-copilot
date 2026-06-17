# DEMO_SCRIPT.md — walking the dashboard, tab by tab

A presenter's script for demoing the **PANW AI FP&A Copilot**. Each section has
**Say** (talking points), **Show** (what to click), the **key numbers** (so you
quote them exactly), the **design choice / why it serves the FP&A user**, and
**If asked** (likely questions + crisp answers). Total runtime ~8–10 min; the
starred ✦ items are the must-hit beats if you're short on time.

> **Setup:** `streamlit run app/dashboard.py` (or the live Streamlit URL). The badge
> under the tabs reads **🟢 Claude (live)** when `ANTHROPIC_API_KEY` is set, **⚪ offline**
> otherwise — say "every tab works either way; offline uses deterministic fallbacks so
> the whole thing runs at zero cost." All dollar figures are in **$ millions**.

---

## 0 · The opener (30 seconds) — the "Who this is for" block ✦

**Say:** "This is an AI copilot for an FP&A team inside a CFO org. It runs the loop a
financial-planning analyst actually does — **plan** the number, **prove** you can trust
it, **explain** why reality differed, **flag** what's worth investigating, and **draft**
the board brief. Two rules hold everywhere: **every number traces to an SEC filing**, and
**the AI is only ever allowed to narrate numbers it's given — never invent them.**"

**Show:** Point at the gray "👤 Who this is for / what it answers" box at the top, then the
tab row. "Each tab also tells you *who it's for and what decision it supports* — I built
this around the user's need, not the technique."

**Frame the data once:** "It's built on **21 quarters** of Palo Alto Networks public
financials, FY2021Q3 through FY2026Q3 — and the timely hook is the **~$25B CyberArk
acquisition** that closed February 2026, plus Chronosphere. That M&A is the thread
through the whole demo."

---

## 1 · 🔮 Forecast — *plan the number* ✦

**Show:** Land on the Forecast tab. Point at the fan chart (history in blue, forecast in
orange dashed, the shaded 80% band). Drag the **horizon** slider 1→4. Toggle the
**interval method** conformal ↔ mc.

**Say:** "We forecast each revenue segment with an interpretable **ETS** model — level,
trend, and PANW's big fiscal-Q4 seasonal spike — then sum them. The output isn't a single
number, it's an **80% range**."

**Design choice (lead with this):** "A CFO plans around the **downside**, not the
midpoint — so a range is the honest, useful answer; a point forecast pretends to a
precision nobody has. And we forecast the **organic** business, so an acquisition can't
masquerade as underlying momentum."

**Key numbers / the proof point on this tab:** Scroll to the **out-of-sample check** info
box: the model's organic forecast for the held-out FY2026Q3 was **$2,564M** vs actual
organic **$2,614M** — about **+2%**, landing right at the band edge.

**If asked:**
- *Why not deep learning?* "21 data points. An LSTM has thousands of parameters — it would
  memorize noise. Model complexity has to match data size; that's why ETS."
- *What's conformal vs mc?* "Hold that — the Backtest tab proves the band is honest."

---

## 2 · ✅ Backtest & Validation — *prove you can trust it* ✦

**Show:** The green headline banner, the four MAPE metric cards, the two calibration cards,
and the actual-vs-forecast chart with the band.

**Say:** "Never trust a forecast you haven't tested on history. This is **walk-forward**
backtesting — stand at each past quarter, forecast the next using *only* data available
then, roll forward. A test asserts no future data ever leaks into training."

**Key numbers (quote exactly):**
- Model **MAPE 1.23%** vs naive baseline **8.92%** → **86% better**.
- "But I report the tough benchmarks honestly: seasonal-naive **1.00%**, and **management
  guidance 0.94%**. The model **roughly matches** those — which is *expected* for a
  backlog-heavy business where management has great visibility. I don't oversell it."
- Calibration: the model's own Monte Carlo band covered only **43%** of outcomes (nominal
  80% — overconfident). **Conformal** intervals — width learned from actual out-of-sample
  errors — restore coverage to **86%**.

**Design choice:** "An '80% band' that's really right 43% of the time would badly
understate downside risk a CFO is sizing. Conformal fixes that by trusting *demonstrated*
error over the model's optimism. This is the single most important methodological idea
in the project: **trust measured error, not the model's self-assessment.**"

**The honesty beat:** "Notice I'm showing you where the model *doesn't* win. You can't
trust a tool that only reports its victories."

**If asked:**
- *Why walk-forward, not a random split?* "Time series have order — a random split lets you
  train on the future. That's leakage; it's the cardinal sin, and there's a test guarding it."
- *Only 7 backtest quarters?* "Correct, and I say so — calibration on a small sample is
  itself uncertain. The conformal finite-sample correction helps; more history tightens it."

---

## 3 · 📐 Variance & Attribution — *explain why reality differed* ✦

**Show:** Keep quarter = **FY2026Q3**. Walk the **waterfall bridge** left→right, then the
four tables, then read one note.

**Say:** "When the actual lands, the CFO's first question is *why*. 'We beat by $59M' is
useless without the decomposition. This does it automatically and it **reconciles exactly**."

**Walk the bridge (the centerpiece):**
"Forecast organic **$2,564M** → **+$50M** organic outperformance → **+$388M** inorganic,
the CyberArk + Chronosphere acquisitions → **$3,002M** actual reported. The pieces sum to
the actual — a variance with an unexplained residual is a broken one."

**Key numbers:**
- Total **$3,002M** = organic **$2,614M** + inorganic **$388M**.
- vs guidance midpoint **$2,943M**: **+$59M (+2.0%)**, Favorable.
- **88.6%** of the beat *versus our forecast* was the acquisition.
- Drivers: **RPO** rose **$2,400M** (of which **$1,800M acquired**); **NGS ARR** rose
  **$1,800M** (of which **$1,600M acquired**). The indicator surge was mostly M&A.

**The sophisticated read (say this slowly — it's the money line):** "Here's the nuance.
Versus *our forecast*, the beat is **~89% acquisition**. But versus *guidance* — which was
issued *after* CyberArk closed, so it already embedded the deal — the **+2% beat is organic
execution**. Two correct answers to 'did they beat?' depending on the baseline. Knowing
which one the audience means is the FP&A judgment."

**Design choice:** "Organic vs inorganic is exactly how analysts judge *real* growth, and
it's what decides whether you lift the run-rate. A beat that's 89% M&A is a completely
different story than organic execution."

**If asked:**
- *Price/volume split?* "No unit/ASP data for software, so I do the honest analog —
  segment-mix attribution — and label it as such. I don't fabricate a split."

---

## 4 · 🚨 Anomalies — *flag what's worth investigating* ✦ (the newest, most role-specific tab)

**Show:** The three count metrics, then the **🔴 Unexplained** expanders (open the critical
one), then **🟢 Expected**, then the full table.

**Say:** "This is the third thing a CFO-org AI team builds — alongside forecasting and
variance — **discrepancy and anomaly detection**. It's a smoke detector for the numbers,
but a smart one: it flags what looks off, then tells you whether there's a *known reason*."

**Key numbers / what it found:** "It scanned 21 quarters and flagged **7 items: 6 unexplained,
1 expected.** Three interpretable detectors — accounting tie-outs, trend/seasonality band
breaks via a robust z-score, and actuals outside the calibrated forecast band."

**The headline beat (open the critical/explained item):** "FY2026Q3 total revenue is a
**critical** anomaly — **$3,002M came in $438M above the $2,564M organic forecast** — but
it's labeled **EXPECTED**, because **$388M of that is the disclosed CyberArk + Chronosphere
acquisition**. The tool didn't just scream; it knew the candle from the fire."

**Point at an unexplained one:** "These RPO spikes in 2022–23 are flagged *unexplained* —
that's the model honestly saying 'the backlog grew abnormally fast here, a human should
look.' And note it **skipped NGS ARR and margin** — too few data points to scan reliably;
it says so rather than forcing a flag."

**Design choice (the bridge line):** "A CFO doesn't want 50 alerts, they want the **one with
no known cause**. So I keep *severity* (how unusual) separate from *status* (do we know
why), and sort the unexplained ones to the top. That expected/unexplained label **is** the
analyst judgment — it's the competency, encoded."

**Guardrail callout:** "It's all rule-based and interpretable — robust median/MAD stats,
accounting identities, and the same calibrated band — no black box. Every flag is something
I can defend to a CFO."

**If asked:**
- *Why MAD, not standard deviation?* "On 20 points, one outlier inflates the std enough to
  hide itself. Median and MAD barely move, so the outlier still stands out."
- *Why year-over-year growth?* "To neutralize PANW's Q4 seasonal spike — otherwise you'd
  flag Q4 every single year."

---

## 5 · 🗣️ Signals — *the qualitative overlay*

**Show:** The per-quarter signal table (sentiment, guidance tone, topic emphasis), then the
tone-vs-next-quarter-surprise scatter with its correlation.

**Say:** "The numbers tell you *what* happened; management's words hint at *what's coming*.
We use Claude to extract a **schema-validated** record per quarter — sentiment, guidance
tone, confidence, what they emphasized — so it's typed, joinable data, not free text."

**Design choice:** "Two companies can post the same number while one signals confidence and
the other hedges. Capturing tone as structured data lets you track it and test it against
what actually happened — which the scatter does."

**The honesty beat:** "The predictive signal here is **weak**, and I report that rather than
dress it up. Source is press-release commentary, not the full call — that's a documented
limitation and a production upgrade."

**If asked:**
- *Why structured output?* "Schema-validated extraction guarantees typed, joinable fields
  instead of free text I'd have to parse and might mis-read."

---

## 6 · 📝 Exec Summary — *draft the board brief* + the integrity gate ✦

**Show:** Quarter = FY2026Q3. Read the **green ✅ verification badge** first, then the brief.
Click **Download brief (Markdown)**.

**Say:** "'Data ingestion to executive summary' is the FP&A dream — the analyst's manual
write-up, automated. The LLM receives a **FACTS block** of the numbers we already computed
and writes the prose. It is **forbidden** from inventing a figure."

**The differentiator (this is the trust moment):** "And I don't just *promise* that — I
**mechanically check it.** The badge says *all figures verified against computed data*. A
harness parses every dollar amount and percentage out of the generated text and matches it
against the computed source of truth. If anything doesn't match, the brief is **rejected
and regenerated**."

**Prove it (optional, powerful):** "I have a negative test that feeds it a brief containing
a fake **$3,500M** and **99%** — both get caught. That's what makes AI *deployable* around
financial numbers: it turns 'the model promised not to lie' into 'we checked, here's proof.'"

**If asked:**
- *What if Claude still hallucinates?* "It can't get past the gate — an unverifiable figure
  is a hard reject, with a retry loop. Offline, a deterministic template brief passes by
  construction, so the tab always works."

---

## 7 · 💬 Chat — *the centerpiece for a non-technical user* ✦

**Show:** Click the **"Is anything anomalous this quarter?"** example button, then
**"What drove the FY2026Q3 revenue beat?"**. Point at the green **✅ verified** badge and the
source tag on each answer.

**Say:** "This is what I'd put in front of a non-technical FP&A user or an exec. Plain
English in — a **verified, quarter-cited, source-tagged** answer out. It only ever answers
from the computed pipeline — financials, forecast, variance, and the anomaly scan — and
**every figure routes through the same no-hallucination verifier** as the brief."

**On the anomaly answer:** "Watch — it surfaces the **explained** CyberArk anomaly and the
top **unexplained** one, exactly like the Anomalies tab, but conversationally."

**Design choice:** "A quick question shouldn't become a quick mistake. The verifier on the
chat answer is what makes a self-serve agent safe to hand a CFO."

**If asked:**
- *Does it make stuff up?* "If it cites a number not in the computed data, the badge flags
  it — the user sees the warning rather than trusting it silently."

---

## Closing (45 seconds) ✦

**Say:** "So that's the full FP&A loop — plan, prove, explain, flag, draft — with two
guardrails holding throughout: **provenance on every input**, and **a mechanical
no-hallucination gate on every generated word.** Three things make it interview-grade: the
**number-verification harness**, the **chat agent under that same discipline**, and
**honesty everywhere** — calibrated ranges, flagged limits, anomalies labeled expected vs
unexplained."

**The handoff line (shows you get the role):** "And because this team builds POCs and hands
them to IT to scale, I wrote a **PRODUCTIONIZATION.md** — what stays (the FP&A logic and the
guardrails), what gets rebuilt (live data feeds, orchestration, auth, hosting), how the
model retrains behind a validation gate, and the MNPI security boundary around the LLM."

---

## Appendix — anticipated tough questions

| Question | Answer |
|---|---|
| "Your model only ties guidance — what's the value?" | "Exactly the honest finding: for a backlog-driven business, the value-add isn't beating the point forecast — it's the **calibrated uncertainty** and the **organic/inorganic decomposition**. I say that out loud rather than overselling MAPE." |
| "How do I know the data is right?" | "Two independent sources — press releases *and* the SEC XBRL API — cross-checked to the dollar, plus a segment-sum reconciliation test on every quarter." |
| "Isn't 21 quarters too few?" | "Yes, and it's the *reason* for every model choice: interpretable ETS over deep learning, conformal bands over model variance, robust stats for anomalies. The constraint drove the design — I don't paper over it." |
| "What would you build next with real data?" | "Monthly actuals with bookings/pipeline drivers, full earnings-call transcripts for signals, the verifier extended to qualitative claims, per-user auth, and a scheduled refresh on each close — all in PRODUCTIONIZATION.md." |
| "Offline mode?" | "No API key needed — deterministic fallbacks for signals, the brief, and chat. The whole project runs and is tested (32 tests) at zero cost; live Claude activates when a key is set." |

**Recovery tip:** if a live LLM tab is slow or errors, say "this is the live Claude path —
offline it falls back deterministically," switch to a computed tab (Forecast/Variance/
Anomalies), and come back. Nothing in the core loop depends on the API.

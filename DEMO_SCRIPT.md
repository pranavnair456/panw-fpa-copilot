# Demo script — PANW AI FP&A Copilot (concise)

~5 minutes. Tabs run left to right: **Source Data → Forecast → Variance → Anomalies → Exec Summary → Chat.** All figures in $millions.

**Open (15s):** "This is an FP&A copilot for a CFO org. It runs the quarterly loop — plan, prove, explain, flag, draft the board brief — on Palo Alto Networks' public filings, with two rules: every number traces to an SEC filing, and the AI never invents one. The thread through the demo is the ~$25B CyberArk acquisition that closed in FY2026Q3."

**1. Source Data** — "Everything starts with trustworthy data. Each number is copied verbatim from an SEC filing — here's the exact quote that proves it — and cross-checked against a second independent source: **16/16 quarters match to the dollar, segments reconcile, zero estimated values.** Nothing is filled in."

**2. Forecast** — "We forecast next quarter's organic revenue as a **range, not a point** — about **\$2,564M**, likely **\$2,515–2,613M** — because a CFO plans around the downside. We tested it on history and the 80% range was right ~**86%** of the time, so the band is honest."

**3. Variance** — "FY2026Q3 came in at **\$3,002M**, beating guidance by **+\$59M (+2.0%)**. But the bridge shows most of the beat was the **\$388M acquisition** — the core business beat our forecast by only ~**\$50M**. Organic vs M&A is the difference between a real beat and a bought one."

**4. Anomalies** — "We scan all 21 quarters for things that look off, then **judge** them. FY2026Q3's revenue spike is flagged but labeled **expected** — we know it's the disclosed CyberArk deal. A CFO wants the one alarm with no known cause, not fifty."

**5. Exec Summary** — "The AI drafts the one-page board brief from those numbers — and **every figure is automatically checked** against the computed data. If it writes a number that isn't real, the draft is rejected. That's what makes AI safe around financials."

**6. Chat** — "Ask in plain English — *'what drove the Q3 beat?'*, *'anything anomalous?'* — and get a verified, quarter-cited answer from the same numbers." *(Click an example button.)*

**Close (10s):** "From filings to a board brief — every number sourced, every range honest, every AI word checked. That's the bridge between what's technically possible and what an FP&A team actually needs."

**If asked / recovery:** the model roughly matches management guidance (expected for a backlog-heavy business — the value-add is the calibrated range + organic/inorganic split, and I say so). Everything runs offline with no API key; if a live AI tab lags, switch to a computed tab and come back.

"""User-need framing for every output — the FP&A-bridge lens.

The team this project auditions for prizes one competency above all: knowing
*what fits the FP&A user*. So every output here is justified by a USER NEED, not
by the technique behind it. This module is the single source of that framing —
rendered at the top of the dashboard, on each tab, and in the README — so the
"who is this for / what decision does it support / why this design" answer lives
in exactly one place and can't drift.

Each entry answers three questions in plain terms:
  who      — the FP&A persona who uses this output
  decision — the real decision it supports
  why      — why THIS design choice serves that user's need (not the technique)
"""
from __future__ import annotations

# One-liner shown at the very top of the app and README.
TAGLINE = (
    "Built for an FP&A team inside a CFO organization. It runs the quarterly loop a "
    "financial-planning analyst actually does — **plan** the number, **prove** you can "
    "trust it, **explain** why reality differed, **flag** what's worth investigating, "
    "and **draft** the board-ready brief — with every figure traced to a filing and an "
    "AI that only narrates numbers it is not allowed to invent."
)

LENS: dict[str, dict[str, str]] = {
    "forecast": {
        "title": "Forecast",
        "who": "FP&A planning team and the CFO.",
        "decision": "How much revenue to plan around — and how much downside cushion "
                    "(cash, hiring pace) to hold.",
        "why": "We show an 80% range, not a single number, because a CFO plans around "
               "the downside case, not the midpoint — and we forecast the *organic* "
               "business so an acquisition can't masquerade as underlying momentum.",
    },
    "backtest": {
        "title": "Backtest & validation",
        "who": "Anyone who has to rely on the forecast — CFO, FP&A lead.",
        "decision": "Whether to trust this forecast at all, and how wide to treat its "
                    "error bars.",
        "why": "A forecast you haven't tested on history is a guess. We prove it beats "
               "a naive baseline and that the 80% band really covers ~80% of outcomes — "
               "so the range can size real risk, not just decorate a slide.",
    },
    "variance": {
        "title": "Variance & attribution",
        "who": "The analyst preparing the quarterly close and the CFO's review.",
        "decision": "What to tell the board about *why* results differed from plan — and "
                    "whether the beat is durable enough to raise the run-rate.",
        "why": "'We beat by $59M' is useless without the why. We split organic vs "
               "acquisition because a beat that's 89% M&A tells a completely different "
               "story than organic execution — and that distinction drives guidance.",
    },
    "anomaly": {
        "title": "Discrepancy & anomaly detection",
        "who": "The analyst and controller closing the quarter.",
        "decision": "What single item to investigate before signing off — and what to "
                    "safely ignore.",
        "why": "A CFO doesn't want 50 alerts, they want the one with no known cause. We "
               "flag statistically, then label each as *expected* (a disclosed "
               "acquisition) or *unexplained* — so attention goes to the genuine "
               "surprise, not to toast setting off the smoke alarm.",
    },
    "signals": {
        "title": "Transcript signals",
        "who": "The analyst overlaying a qualitative read on the quant.",
        "decision": "Whether management's tone corroborates or contradicts the numbers.",
        "why": "Two companies can post the same number while one signals confidence and "
               "the other hedges. We capture tone as structured data so it can be "
               "tracked over time and tested against what actually happened next.",
    },
    "summary": {
        "title": "Executive summary",
        "who": "The CFO, IR, and the analyst who would otherwise hand-write it.",
        "decision": "What one page to put in front of the board this quarter.",
        "why": "The analyst's manual write-up, automated — but with a hard integrity "
               "gate so the CFO can trust every figure. The verifier turns 'the AI "
               "promised not to lie' into 'we mechanically checked, and here's proof.'",
    },
    "chat": {
        "title": "Chat with your financials",
        "who": "Any non-technical FP&A user or executive.",
        "decision": "Get an instant, sourced answer to an ad-hoc question without "
                    "pinging an analyst.",
        "why": "Plain-English question in, a verified and quarter-cited answer out — "
               "routed through the same no-hallucination gate, so a quick question "
               "never becomes a quick mistake.",
    },
}


def caption(key: str) -> str:
    """Markdown one-liner for a dashboard tab: who · decision · why (user need)."""
    e = LENS[key]
    return (f"**Who this is for:** {e['who']}  \n"
            f"**Decision it supports:** {e['decision']}  \n"
            f"**Why it's built this way:** {e['why']}")

"""Stage 4 — Transcript NLP signal layer.

Turns each quarter's management commentary (the prepared CEO/CFO remarks + outlook
in the 8-K earnings release) into a structured, schema-valid signal record:
sentiment, guidance tone, confidence vs hedging, and topic emphasis. With a
Claude API key this uses the LLM (schema-validated `messages.parse`); without
one it falls back to a transparent heuristic so the pipeline still runs and the
dashboard is populated (each row tags its `source`).

Output: data/signals.csv (one row per quarter, joinable to financials by quarter)
plus a revenue-surprise column to test whether tone predicts the next print.

Note: we use the press-release management commentary as the signal source
(fully sourced + reproducible). Full earnings-call transcripts incl. analyst Q&A
would be the production source — see LEARNING.md.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from src import config
from src.llm.client import client

RAW_DIR = config.RAW / "earnings"
TOPICS = ["ngs_arr", "platformization", "cyberark_acquisitions", "margin"]


class Emphasis(BaseModel):
    ngs_arr: int = Field(description="0-3: emphasis on Next-Gen Security ARR")
    platformization: int = Field(description="0-3: emphasis on platformization")
    cyberark_acquisitions: int = Field(description="0-3: emphasis on CyberArk/M&A")
    margin: int = Field(description="0-3: emphasis on margin/profitability")


class QuarterSignal(BaseModel):
    management_sentiment: Literal["positive", "neutral", "cautious", "negative"]
    guidance_tone: Literal["raising", "holding", "lowering"]
    confidence: Literal["confident", "balanced", "hedged"]
    emphasis: Emphasis
    key_quote: str = Field(description="One short verbatim quote capturing the tone")


def commentary_text(quarter: str) -> str:
    """Prepared remarks + outlook from the press release (drop the tables)."""
    txt = (RAW_DIR / f"{quarter}.txt").read_text(errors="ignore")
    # Cut at the financial statements so we keep narrative, not number tables.
    cut = re.search(r"CONDENSED CONSOLIDATED|Reconciliation of", txt, re.IGNORECASE)
    return txt[: cut.start()] if cut else txt[:6000]


SYSTEM = (
    "You are an equity analyst extracting forward-looking signals from a "
    "company's earnings commentary. Judge tone and emphasis from the text only; "
    "do not invent facts. Emphasis scores are 0 (absent) to 3 (heavily stressed)."
)


def _llm_signal(quarter: str, text: str) -> tuple[QuarterSignal, str]:
    sig = client.extract(
        system=SYSTEM,
        user=f"Earnings commentary for Palo Alto Networks {quarter}:\n\n{text}",
        schema=QuarterSignal, model=config.EXTRACTION_MODEL,
    )
    return sig, config.EXTRACTION_MODEL


def _heuristic_signal(quarter: str, text: str, row, prior) -> tuple[QuarterSignal, str]:
    low = text.lower()
    # Emphasis from keyword frequency -> 0-3.
    def score(*kws):
        n = sum(low.count(k) for k in kws)
        return min(3, n)
    emph = Emphasis(
        ngs_arr=score("next-generation security", "ngs arr", "next-gen"),
        platformization=score("platformiz", "platform"),
        cyberark_acquisitions=score("cyberark", "chronosphere", "acquisition"),
        margin=score("margin", "profitability", "operating income"),
    )
    # Guidance tone: guided next-Q QoQ growth vs trailing QoQ growth.
    guided_mid = (row["guidance_revenue_next_q_low"] + row["guidance_revenue_next_q_high"]) / 2
    guided_growth = guided_mid / row["revenue_total"] - 1
    trailing_growth = row["revenue_total"] / prior["revenue_total"] - 1
    tone = ("raising" if guided_growth > trailing_growth + 0.01
            else "lowering" if guided_growth < trailing_growth - 0.01 else "holding")
    # Sentiment: did this quarter beat the guidance issued last quarter?
    beat = row["revenue_total"] - (prior["guidance_revenue_next_q_low"]
                                   + prior["guidance_revenue_next_q_high"]) / 2
    sentiment = ("positive" if beat > 0 else "cautious" if beat < 0 else "neutral")
    quote_m = re.search(r'"([^"]{40,200})"', text)
    return QuarterSignal(
        management_sentiment=sentiment, guidance_tone=tone, confidence="balanced",
        emphasis=emph, key_quote=quote_m.group(1) if quote_m else "",
    ), "heuristic"


def build(df: pd.DataFrame | None = None) -> pd.DataFrame:
    from src.forecast import load
    df = load() if df is None else df
    rows = []
    for i, row in df.iterrows():
        q = row["fiscal_quarter"]
        if not (RAW_DIR / f"{q}.txt").exists():
            continue
        text = commentary_text(q)
        prior = df.iloc[i - 1] if i > 0 else row
        if client.available:
            sig, source = _llm_signal(q, text)
        else:
            sig, source = _heuristic_signal(q, text, row, prior)
        # Revenue surprise = actual vs the guidance issued the prior quarter.
        gp_lo, gp_hi = prior["guidance_revenue_next_q_low"], prior["guidance_revenue_next_q_high"]
        surprise = (row["revenue_total"] - (gp_lo + gp_hi) / 2) / ((gp_lo + gp_hi) / 2) * 100 \
            if i > 0 and pd.notna(gp_lo) else None
        rows.append({
            "fiscal_quarter": q,
            "management_sentiment": sig.management_sentiment,
            "guidance_tone": sig.guidance_tone,
            "confidence": sig.confidence,
            "emphasis_ngs_arr": sig.emphasis.ngs_arr,
            "emphasis_platformization": sig.emphasis.platformization,
            "emphasis_cyberark": sig.emphasis.cyberark_acquisitions,
            "emphasis_margin": sig.emphasis.margin,
            "key_quote": sig.key_quote,
            "revenue_surprise_pct": round(surprise, 2) if surprise is not None else None,
            "source": source,
        })
    out = pd.DataFrame(rows)
    out.to_csv(config.SIGNALS_CSV, index=False)
    return out


if __name__ == "__main__":
    df = build()
    mode = "Claude (live)" if client.available else "heuristic (offline — set ANTHROPIC_API_KEY for LLM)"
    print(f"Wrote {config.SIGNALS_CSV}  ({len(df)} quarters)  source: {mode}\n")
    cols = ["fiscal_quarter", "management_sentiment", "guidance_tone", "confidence",
            "emphasis_ngs_arr", "emphasis_cyberark", "revenue_surprise_pct"]
    print(df[cols].to_string(index=False))
    # Does a 'raising' tone precede positive surprises next quarter?
    tone_num = {"raising": 1, "holding": 0, "lowering": -1}
    df["_tone"] = df["guidance_tone"].map(tone_num)
    df["_next_surprise"] = df["revenue_surprise_pct"].shift(-1)
    corr = df[["_tone", "_next_surprise"]].dropna().corr().iloc[0, 1]
    print(f"\nSignal test: corr(guidance tone, NEXT-quarter revenue surprise) = {corr:+.2f}")

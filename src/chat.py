"""Chat-with-your-financials agent (V3 differentiator).

A natural-language interface that answers questions ("what drove the Q3 beat?")
ONLY from the computed pipeline — financials, forecast, variance — with the
quarter cited, and every figure routed through the number-verification harness.
This showcases agentic AI bound by the same no-hallucination discipline as the
rest of the system: if the model cites a number that isn't in the computed data,
the answer is flagged.

Offline (no key) a lightweight keyword responder handles common questions from
the data so the chat tab still works; the live Claude agent activates with a key.
"""
from __future__ import annotations
from dataclasses import dataclass

import pandas as pd

from src import config
from src.llm.client import client
from src import verify
from src.forecast import load


@dataclass
class ChatAnswer:
    text: str
    verified: bool
    violations: list
    source: str


def dataset_context() -> str:
    """A compact, self-contained dump of the computed numbers for the agent."""
    df = load()
    cols = ["fiscal_quarter", "revenue_total", "revenue_organic", "inorganic_revenue",
            "revenue_product", "revenue_subscription", "rpo", "ngs_arr",
            "non_gaap_op_margin", "guidance_revenue_next_q_low", "guidance_revenue_next_q_high"]
    table = df[cols].to_string(index=False)
    parts = [
        "PANW quarterly financials (all $ in millions; FY ends Jul 31):",
        table,
        "\nNotes: revenue_organic excludes acquisition revenue; FY2026Q3 inorganic "
        "$388M = CyberArk + Chronosphere (also $1,800M of RPO and $1,600M of NGS ARR). "
        "billings discontinued after FY2024Q1; NGS ARR first disclosed FY2024Q4.",
    ]
    if config.SIGNALS_CSV.exists():
        sig = pd.read_csv(config.SIGNALS_CSV)
        parts.append("\nTranscript signals (per quarter):\n" + sig[
            ["fiscal_quarter", "management_sentiment", "guidance_tone", "revenue_surprise_pct"]
        ].to_string(index=False))
    return "\n".join(parts)


SYSTEM = (
    "You are an FP&A analyst answering questions about Palo Alto Networks using ONLY "
    "the DATA provided. Rules: (1) Every number you state must appear in the DATA — "
    "never invent or estimate. (2) Cite the fiscal quarter for any figure. (3) If the "
    "answer isn't in the DATA, say so plainly. (4) Be concise and concrete."
)


def _offline_answer(question: str) -> str:
    """Deterministic keyword responder for offline mode (no API key)."""
    df = load()
    last = df.iloc[-1]
    q = question.lower()
    if "forecast" in q or "next" in q or "predict" in q:
        from src.forecast import run_forecast, load_conformal_errors
        fc = run_forecast(df=df, conformal_errors=load_conformal_errors())
        i = 1 if len(fc.future_quarters) > 1 else 0
        return (f"The backtested model forecasts {fc.future_quarters[i]} organic revenue of "
                f"${fc.total_point[i]:,.0f}M (80% interval ${fc.total_low[i]:,.0f}-"
                f"${fc.total_high[i]:,.0f}M). [offline mode — set ANTHROPIC_API_KEY for full chat]")
    if "inorganic" in q or "cyberark" in q or "acquisition" in q or "drove" in q or "beat" in q:
        return (f"In {last['fiscal_quarter']}, total revenue was ${last['revenue_total']:,.0f}M, "
                f"of which ${last['inorganic_revenue']:,.0f}M was inorganic (CyberArk + Chronosphere); "
                f"organic revenue was ${last['revenue_organic']:,.0f}M. The beat versus our forecast "
                f"was mostly acquisition-driven. [offline mode — set ANTHROPIC_API_KEY for full chat]")
    if "rpo" in q or "backlog" in q:
        return (f"{last['fiscal_quarter']} RPO (backlog) was ${last['rpo']:,.0f}M. "
                f"[offline mode — set ANTHROPIC_API_KEY for full chat]")
    return (f"Latest quarter {last['fiscal_quarter']}: total revenue ${last['revenue_total']:,.0f}M "
            f"(organic ${last['revenue_organic']:,.0f}M). Ask about revenue, the forecast, RPO, or "
            f"what drove the beat. [offline mode — set ANTHROPIC_API_KEY for full chat]")


def ask(question: str) -> ChatAnswer:
    facts = verify.build_dataset_facts()
    if not client.available:
        text = _offline_answer(question)
        viol = verify.verify_text(text, facts)
        return ChatAnswer(text, len(viol) == 0, viol, "offline")

    text = client.generate(
        system=SYSTEM,
        user=f"DATA:\n{dataset_context()}\n\nQUESTION: {question}",
        model=config.CHAT_MODEL, max_tokens=1200,
    )
    viol = verify.verify_text(text, facts)
    if viol:  # append a transparency warning rather than silently trusting
        flagged = ", ".join(v.raw for v in viol)
        text += (f"\n\n⚠️ Verification: {len(viol)} figure(s) not found in the computed "
                 f"data ({flagged}) — treat with caution.")
    return ChatAnswer(text, len(viol) == 0, viol, config.CHAT_MODEL)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What drove the FY2026Q3 revenue beat?"
    a = ask(q)
    print(f"Q: {q}\n\n{a.text}\n\n[source: {a.source} | verified: {a.verified}]")

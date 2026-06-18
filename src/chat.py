"""Chat-with-your-financials agent — the demo centerpiece (V3 differentiator).

A natural-language interface a NON-TECHNICAL FP&A user or executive can use:
ask a plain-English question ("what drove the Q3 beat?", "is anything anomalous
this quarter?") and get a concise, **quarter-cited, source-tagged** answer drawn
ONLY from the computed pipeline — financials, forecast, variance, and the
anomaly scan — with every figure routed through the no-hallucination verifier.
This is agentic AI under the same discipline as the rest of the system: a number
the model can't back with computed data is flagged, not trusted.

Offline (no key) a deterministic intent responder answers the common questions
from the data so the tab always works; the live Claude agent activates with a key
and gets the same computed facts (financials + variance + anomalies + signals) as
its only allowed source.
"""
from __future__ import annotations
from dataclasses import dataclass

import pandas as pd

from src import config
from src.llm.client import client
from src import verify
from src.forecast import load
from src.fmt import fmt_money, fmt_pct


@dataclass
class ChatAnswer:
    text: str
    verified: bool
    violations: list
    source: str


# --------------------------------------------------------------- shared facts
def _latest_inorganic_quarter(df: pd.DataFrame) -> str:
    """The most recent quarter with disclosed acquisition revenue (the variance /
    anomaly focus quarter); falls back to the last quarter."""
    inorg = df[df["inorganic_revenue"] > 0]
    return (inorg["fiscal_quarter"].iloc[-1] if not inorg.empty
            else df["fiscal_quarter"].iloc[-1])


def _variance_summary_line(quarter: str) -> str:
    from src.variance import build_report
    s = build_report(quarter).summary
    share = (f" Acquisitions account for {fmt_pct(s['inorganic_share_of_beat_%'])} of the "
             f"beat versus forecast."
             if s.get("inorganic_share_of_beat_%") is not None else "")
    return (f"{quarter}: total revenue {fmt_money(s['actual_total'])} = organic "
            f"{fmt_money(s['actual_organic'])} + inorganic {fmt_money(s['inorganic'])} "
            f"(CyberArk + Chronosphere). Organic beat our {fmt_money(s['forecast_organic'])} "
            f"forecast by {fmt_money(s['organic_beat_$'])}; vs guidance midpoint "
            f"{fmt_money(s['guidance_midpoint'])} the result was {fmt_money(s['vs_guidance_$'])} "
            f"({fmt_pct(s['vs_guidance_%'], signed=True)}, {s['vs_guidance_flag']}).{share}")


def _anomaly_lines(quarter: str) -> tuple[str, list]:
    """A plain-English summary of the anomaly scan + the raw flag list."""
    from src.anomaly import build_report
    rep = build_report(quarter, run_bt=False)
    unexpl = [a for a in rep.anomalies if a.status == "unexplained"]
    expl = [a for a in rep.anomalies if a.status == "explained"]
    head = (f"The scan flagged {len(rep.anomalies)} item(s): {len(unexpl)} unexplained "
            f"(worth investigating) and {len(expl)} expected (explained by disclosure).")
    return head, rep.anomalies


def dataset_context() -> str:
    """A compact, self-contained dump of the computed numbers for the live agent."""
    df = load()
    fq = _latest_inorganic_quarter(df)
    cols = ["fiscal_quarter", "revenue_total", "revenue_organic", "inorganic_revenue",
            "revenue_product", "revenue_subscription", "rpo", "ngs_arr",
            "non_gaap_op_margin", "guidance_revenue_next_q_low", "guidance_revenue_next_q_high"]
    parts = [
        "PANW quarterly financials (all $ in millions; FY ends Jul 31):",
        df[cols].to_string(index=False),
        f"\nNotes: revenue_organic excludes acquisition revenue; FY2026Q3 inorganic "
        f"{fmt_money(388)} = CyberArk + Chronosphere (also {fmt_money(1800)} of RPO and "
        f"{fmt_money(1600)} of NGS ARR). "
        "billings discontinued after FY2024Q1; NGS ARR first disclosed FY2024Q4.",
        f"\nVariance read — {_variance_summary_line(fq)}",
    ]
    head, anomalies = _anomaly_lines(fq)
    parts.append("\nAnomaly scan. " + head)
    for a in anomalies:
        parts.append(f"  - [{a.severity}/{a.status}] {a.quarter} {a.metric}: {a.why}")
    if config.SIGNALS_CSV.exists():
        sig = pd.read_csv(config.SIGNALS_CSV)
        parts.append("\nTranscript signals (per quarter):\n" + sig[
            ["fiscal_quarter", "management_sentiment", "guidance_tone", "revenue_surprise_pct"]
        ].to_string(index=False))
    return "\n".join(parts)


SYSTEM = (
    "You are an FP&A analyst answering questions about Palo Alto Networks for a "
    "non-technical finance user, using ONLY the DATA provided (financials, the "
    "variance read, the anomaly scan, and transcript signals). Rules: (1) Every "
    "number you state must appear in the DATA — never invent or estimate. (2) Always "
    "cite the fiscal quarter for any figure, and name the source (e.g. 'per the "
    "variance bridge' / 'the anomaly scan'). (3) If something isn't in the DATA, say "
    "so plainly rather than guessing. (4) Be concise and concrete — a few sentences."
)

_OFFLINE = "[offline mode — set ANTHROPIC_API_KEY for the full conversational agent]"


# ------------------------------------------------------------- offline router
def _offline_answer(question: str) -> str:
    """Deterministic, source-tagged intent responder for offline mode."""
    df = load()
    last = df.iloc[-1]
    fq = _latest_inorganic_quarter(df)
    q = question.lower()

    def kw(*words):
        return any(w in q for w in words)

    if kw("anomal", "unusual", "discrepan", "flag", "off", "stand out", "investigat"):
        head, anomalies = _anomaly_lines(fq)
        unexpl = [a for a in anomalies if a.status == "unexplained"]
        expl = [a for a in anomalies if a.status == "explained"]
        lines = [f"{head} (source: anomaly scan)"]
        if expl:
            lines.append("Expected (explained): " + expl[0].why)
        if unexpl:
            lines.append("Most notable unexplained: " + unexpl[0].why)
        return " ".join(lines) + f" {_OFFLINE}"

    if kw("forecast", "next", "predict", "outlook", "guide"):
        from src.forecast import run_forecast, load_conformal_errors
        fc = run_forecast(df=df, conformal_errors=load_conformal_errors())
        i = 1 if len(fc.future_quarters) > 1 else 0
        return (f"The backtested model forecasts {fc.future_quarters[i]} organic revenue of "
                f"{fmt_money(fc.total_point[i])} (80% interval {fmt_money(fc.total_low[i])}–"
                f"{fmt_money(fc.total_high[i])}) (source: forecast). The range matters more than "
                f"the point — plan around the downside. {_OFFLINE}")

    if kw("drove", "beat", "variance", "vs guidance", "vs forecast", "why"):
        return _variance_summary_line(fq) + f" (source: variance bridge) {_OFFLINE}"

    if kw("inorganic", "cyberark", "chronosphere", "acquisition", "m&a"):
        return (f"In {fq}, {fmt_money(last['inorganic_revenue'])} of total revenue "
                f"({fmt_money(last['revenue_total'])}) was inorganic — the CyberArk and "
                f"Chronosphere acquisitions; organic revenue was "
                f"{fmt_money(last['revenue_organic'])} (source: financials). {_OFFLINE}")

    if kw("rpo", "backlog"):
        return (f"{fq} RPO (backlog) was {fmt_money(last['rpo'])}, of which {fmt_money(1800)} is "
                f"acquired (CyberArk + Chronosphere) (source: financials / variance). {_OFFLINE}")

    if kw("margin", "profit"):
        if pd.notna(last["non_gaap_op_margin"]):
            return (f"{last['fiscal_quarter']} non-GAAP operating margin was "
                    f"{fmt_pct(last['non_gaap_op_margin'])} (source: financials). {_OFFLINE}")

    if kw("product", "subscription", "segment", "mix"):
        return (f"{last['fiscal_quarter']} revenue split: product "
                f"{fmt_money(last['revenue_product'])} and subscription & support "
                f"{fmt_money(last['revenue_subscription'])} (source: financials). {_OFFLINE}")

    if kw("sentiment", "tone", "management", "confiden"):
        if config.SIGNALS_CSV.exists():
            s = pd.read_csv(config.SIGNALS_CSV)
            r = s[s["fiscal_quarter"] == fq]
            if not r.empty:
                r = r.iloc[0]
                return (f"For {fq}, management sentiment read as '{r['management_sentiment']}' "
                        f"with a '{r['guidance_tone']}' guidance tone (source: transcript "
                        f"signals). {_OFFLINE}")

    return (f"Latest quarter {last['fiscal_quarter']}: total revenue "
            f"{fmt_money(last['revenue_total'])} (organic {fmt_money(last['revenue_organic'])}) "
            f"(source: financials). Ask me about the forecast, what drove the beat, "
            f"anything anomalous, RPO, margin, segments, or management tone. {_OFFLINE}")


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

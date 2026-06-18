"""Stage 5 — LLM executive summary ("data ingestion to executive summary").

The LLM receives the ALREADY-COMPUTED forecast, variance decomposition, and
transcript signals, and writes a one-page CFO brief. It is forbidden from
inventing or altering any number — and `src/verify.py` enforces that: every
figure in the output is cross-checked against the computed source of truth, and
a brief with any unverifiable number is rejected and regenerated.

Offline (no API key) a deterministic template brief is produced from the same
computed numbers — it passes verification by construction, so the dashboard and
tests work end-to-end. Output: data/exec_brief.md.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from src import config
from src.llm.client import client
from src.variance import build_report
from src.forecast import run_forecast, load_conformal_errors, load as load_fin
from src import verify
from src.fmt import fmt_money, fmt_pct


@dataclass
class Brief:
    quarter: str
    text: str
    verified: bool
    violations: list
    source: str


def gather_facts(quarter: str) -> dict:
    df = load_fin()
    row = df[df["fiscal_quarter"] == quarter].iloc[0]
    rep = build_report(quarter, df=df)
    fc = run_forecast(df=df[df["period_end_date"] <= row["period_end_date"]],
                      conformal_errors=load_conformal_errors())
    sig = None
    if config.SIGNALS_CSV.exists():
        s = pd.read_csv(config.SIGNALS_CSV)
        s = s[s["fiscal_quarter"] == quarter]
        sig = s.iloc[0].to_dict() if not s.empty else None
    # Forward look = first forecast quarter strictly AFTER the reporting quarter
    # (index 0 is the reporting quarter's own organic estimate).
    fwd = [i for i, fq in enumerate(fc.future_quarters) if fq > quarter]
    fwd_idx = fwd[0] if fwd else 0
    return {"row": row, "rep": rep, "fc": fc, "sig": sig,
            "fwd_idx": fwd_idx, "next_q": fc.future_quarters[fwd_idx]}


def _facts_block(f: dict) -> str:
    """The ONLY numbers the LLM may use — passed in, never invented."""
    s, b, d = f["rep"].summary, f["rep"].bridge, f["rep"].driver_attribution
    lines = [
        f"Quarter: {f['rep'].quarter}",
        f"Total revenue (actual): {fmt_money(s['actual_total'])}",
        f"  - Organic: {fmt_money(s['actual_organic'])}; Inorganic (CyberArk+Chronosphere): {fmt_money(s['inorganic'])}",
        f"Management guidance midpoint: {fmt_money(s['guidance_midpoint'])}; "
        f"variance vs guidance: {fmt_money(s['vs_guidance_$'])} ({fmt_pct(s['vs_guidance_%'], signed=True)}, {s['vs_guidance_flag']})",
        f"Our model forecast (organic): {fmt_money(s['forecast_organic'])}; organic beat vs forecast: {fmt_money(s['organic_beat_$'])}",
        f"Inorganic share of the beat vs forecast: {fmt_pct(s['inorganic_share_of_beat_%'])}",
        "Variance bridge: " + " -> ".join(f"{r['step']} {fmt_money(r['amount'])}" for r in b.to_dict("records")),
    ]
    for r in d.to_dict("records"):
        lines.append(f"Driver {r['driver']}: {fmt_money(r['prior'])} -> {fmt_money(r['current'])} "
                     f"({fmt_money(r['change'])}, {fmt_pct(r['change_pct'], signed=True)}; "
                     f"{fmt_money(r['inorganic_part'])} inorganic / {fmt_money(r['organic_part'])} organic)")
    nq = f["next_q"]
    lines.append(f"Forecast {nq} organic revenue: {fmt_money(f['fc'].total_point[f['fwd_idx']])} "
                 f"(80% band {fmt_money(f['fc'].total_low[f['fwd_idx']])}-{fmt_money(f['fc'].total_high[f['fwd_idx']])})")
    if f["sig"]:
        sg = f["sig"]
        lines.append(f"Transcript signal: sentiment={sg['management_sentiment']}, "
                     f"guidance tone={sg['guidance_tone']}, confidence={sg['confidence']}")
    return "\n".join(lines)


SYSTEM = (
    "You are a CFO's FP&A analyst writing a one-page executive brief on a quarter's "
    "results. CRITICAL RULES: (1) Use ONLY the numbers in the FACTS block provided — "
    "never invent, estimate, or alter a figure. (2) Every dollar amount or percentage "
    "you write must come from the FACTS. (3) Write in clear analyst prose, not a data "
    "dump. Structure: headline, the forecast read, the variance story (lead with "
    "organic vs inorganic), the driver/signal read, and 'what to watch'. ~250-350 words."
)


def _offline_brief(f: dict) -> str:
    s = f["rep"].summary
    d = {r["driver"]: r for r in f["rep"].driver_attribution.to_dict("records")}
    nq = f["next_q"]
    rpo = d["RPO (backlog)"]
    return f"""# Executive Brief — Palo Alto Networks, {f['rep'].quarter}

**Headline.** Total revenue landed at **{fmt_money(s['actual_total'])}**, {fmt_money(s['vs_guidance_$'])} ({fmt_pct(s['vs_guidance_%'], signed=True)}) versus the guidance midpoint of {fmt_money(s['guidance_midpoint'])} — a {s['vs_guidance_flag'].lower()} result.

**The variance story.** The headline beat is mostly inorganic: {fmt_money(s['inorganic'])} came from the CyberArk and Chronosphere acquisitions. Against our model's organic forecast of {fmt_money(s['forecast_organic'])}, the underlying business beat by just {fmt_money(s['organic_beat_$'])} — acquisitions account for {fmt_pct(s['inorganic_share_of_beat_%'])} of the total upside to forecast. Read against guidance (which already embedded the deals), the {fmt_money(s['vs_guidance_$'])} beat reflects organic execution, not the acquisitions themselves.

**Drivers.** Remaining performance obligations (backlog) rose to **{fmt_money(rpo['current'])}** ({fmt_pct(rpo['change_pct'], signed=True)} Q/Q), but {fmt_money(rpo['inorganic_part'])} of that increase is acquired — only {fmt_money(rpo['organic_part'])} is organic, consistent with the modest organic revenue beat.

**Forecast.** Our backtested model projects {nq} organic revenue of **{fmt_money(f['fc'].total_point[f['fwd_idx']])}** (80% interval {fmt_money(f['fc'].total_low[f['fwd_idx']])}–{fmt_money(f['fc'].total_high[f['fwd_idx']])}).

**What to watch.** Whether organic NGS ARR growth re-accelerates as the acquisitions annualize, and how cleanly the acquired revenue converts the elevated backlog into recognized revenue over the next 2-3 quarters.
"""


def generate_brief(quarter: str = "FY2026Q3", max_retries: int = 1) -> Brief:
    f = gather_facts(quarter)
    if not client.available:
        text = _offline_brief(f)
        ok, viol = verify.verify_brief(text, quarter)
        return Brief(quarter, text, ok, viol, "offline-template")

    facts = _facts_block(f)
    user = f"FACTS (the only numbers you may use):\n{facts}\n\nWrite the executive brief."
    for attempt in range(max_retries + 1):
        text = client.generate(system=SYSTEM, user=user, model=config.SUMMARY_MODEL)
        ok, viol = verify.verify_brief(text, quarter)
        if ok:
            return Brief(quarter, text, True, [], config.SUMMARY_MODEL)
        # Feed the violations back and regenerate.
        bad = ", ".join(v.raw for v in viol)
        user += (f"\n\nYour previous draft contained figures NOT in the FACTS "
                 f"({bad}). Rewrite using only FACTS numbers.")
    return Brief(quarter, text, False, viol, config.SUMMARY_MODEL)


def save(brief: Brief, path=None):
    path = path or config.EXEC_BRIEF_MD
    path.write_text(brief.text)
    return path


if __name__ == "__main__":
    b = generate_brief("FY2026Q3")
    print(f"Source: {b.source} | verified: {b.verified} | "
          f"violations: {[v.raw for v in b.violations]}\n")
    print(b.text)
    print(f"\nSaved {save(b)}")

"""Provenance & data-quality read-layer for the Source Data tab.

A thin, side-effect-free surface over artifacts that ALREADY exist — it rebuilds
no data logic. It exposes, for the dashboard:
  * the per-metric verbatim evidence quotes (`earnings_extracted.json`),
  * the source-filing URL per quarter (parsed from `data_dictionary.md`),
  * a coverage matrix (which metric is disclosed in which quarter — gaps shown),
  * headline data-quality stats (cross-source agreement + segment reconciliation,
    computed live via `ingest.reconcile`).

Everything here is pure pandas/JSON/regex — no API key, no model — so the Source
Data tab always works offline.
"""
from __future__ import annotations
import json
import re

import pandas as pd

from src import config

CIK = config.CIK  # 1327567

# Metrics we surface, in display order: (csv column, plain-English label).
DISPLAY_METRICS: list[tuple[str, str]] = [
    ("revenue_total", "Total revenue"),
    ("revenue_product", "Product revenue"),
    ("revenue_subscription", "Subscription & support revenue"),
    ("inorganic_revenue", "Acquisition (inorganic) revenue"),
    ("rpo", "Backlog (RPO)"),
    ("ngs_arr", "Next-Gen Security ARR"),
    ("billings", "Billings"),
    ("non_gaap_op_margin", "Operating margin (non-GAAP)"),
    ("non_gaap_eps_reported", "Earnings per share (non-GAAP)"),
    ("guidance_revenue_next_q_low", "Next-quarter guidance (low)"),
    ("guidance_revenue_next_q_high", "Next-quarter guidance (high)"),
]


def _raw():
    return json.loads(config.EARNINGS_JSON.read_text())["quarters"]


def load_evidence() -> dict[str, dict[str, str]]:
    """{fiscal_quarter: {metric: verbatim evidence quote}} from the raw extraction."""
    return {q["fiscal_quarter"]: (q.get("evidence") or {}) for q in _raw()}


def accn_for(quarter: str) -> str | None:
    """SEC accession number of the source 8-K for a quarter."""
    return next((q.get("accn") for q in _raw() if q["fiscal_quarter"] == quarter), None)


def _edgar_dir(accn: str) -> str:
    """Fallback link: the EDGAR folder that holds the filing's documents."""
    return f"https://www.sec.gov/Archives/edgar/data/{CIK}/{accn.replace('-', '')}/"


def source_links() -> dict[str, str]:
    """{fiscal_quarter: source-filing URL}, parsed from the provenance table in
    `data_dictionary.md`; falls back to the EDGAR accession folder if a row is
    missing so every quarter always resolves to a real filing."""
    links: dict[str, str] = {}
    text = config.DATA_DICT.read_text()
    # rows look like: | FY2026Q3 | `accn` | [file.htm](https://www.sec.gov/...) |
    row = re.compile(r"\|\s*(FY\d{4}\s*Q\d)\s*\|[^|]*\|\s*\[[^\]]*\]\((https?://[^)]+)\)")
    for m in row.finditer(text):
        q = m.group(1).replace(" ", "")
        links[q] = m.group(2)
    # Fill any gaps from the accession number.
    for q in _raw():
        fq, accn = q["fiscal_quarter"], q.get("accn")
        if fq not in links and accn:
            links[fq] = _edgar_dir(accn)
    return links


def coverage_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean (1/0) present-vs-blank matrix: rows = display metrics, columns =
    fiscal quarters. 1 = disclosed that quarter; 0 = not disclosed (never filled in)."""
    cols = [c for c, _ in DISPLAY_METRICS if c in df.columns]
    labels = {c: lbl for c, lbl in DISPLAY_METRICS}
    mat = df.set_index("fiscal_quarter")[cols].notna().astype(int).T
    mat.index = [labels[c] for c in cols]
    return mat


def quality_stats(df: pd.DataFrame) -> dict:
    """Headline data-quality numbers, computed live via the existing reconciliation."""
    from src.ingest import reconcile
    rep = reconcile(df)
    checked = rep["xbrl_revenue"].notna()
    return {
        "n_quarters": int(len(df)),
        "n_xbrl_checked": int(checked.sum()),
        "n_xbrl_match": int((rep["xbrl_matches"] & checked).sum()),
        "segment_ok": bool(rep["segment_reconciles"].all()),
        "n_segment": int(len(rep)),
    }

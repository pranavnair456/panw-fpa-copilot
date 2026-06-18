"""Shared money/percent formatting — ONE standard, used app-wide.

Every dollar figure across the app (cards, prose, tables, charts, the exec
brief, chat) is rendered through these helpers so numbers read like a financial
document. Display only — never changes an underlying value.

Conventions:
  * Auto unit scaling: a standalone figure >= $1,000M shows in $B (2 decimals,
    e.g. $3.00B, $18.40B); otherwise $M (whole numbers, commas, e.g. $594M).
  * Dollar negatives in finance-style parentheses: $(50)M.
  * Percentages: one decimal with a % sign (+2.0%, -1.9%) — parentheses are for
    dollars only (keeps the verifier's % parser valid).
"""
from __future__ import annotations
import math

_B_THRESHOLD = 1000.0  # values are in $M; >= 1000M == >= $1B


def _is_missing(v) -> bool:
    if v is None:
        return True
    try:
        return isinstance(v, float) and math.isnan(v)
    except TypeError:
        return False


def fmt_money(v, scale: str = "auto") -> str:
    """'$3.00B' (>=$1B, 2dp) / '$594M' (whole) / '$(50)M'. scale: 'auto'|'B'|'M'."""
    if _is_missing(v):
        return "—"
    v = float(v)
    a = abs(v)
    if scale == "auto":
        scale = "B" if a >= _B_THRESHOLD else "M"
    core = f"{a / 1000:,.2f}B" if scale == "B" else f"{a:,.0f}M"
    return f"$({core[:-1]}){core[-1]}" if v < 0 else f"${core}"


def fmt_pct(v, signed: bool = False) -> str:
    """One decimal + '%': '2.0%', '+2.0%', '-1.9%'."""
    if _is_missing(v):
        return "—"
    return f"{float(v):+.1f}%" if signed else f"{float(v):.1f}%"


def money_cell(v, scale: str) -> str:
    """Bare number for a table cell whose header states the unit:
    scale 'B' -> '3.00' (2dp) / 'M' -> '59' (whole); negatives '(50)'."""
    if _is_missing(v):
        return "—"
    v = float(v)
    a = abs(v)
    core = f"{a / 1000:,.2f}" if scale == "B" else f"{a:,.0f}"
    return f"({core})" if v < 0 else core


def col_scale(series) -> str:
    """'B' if the column's typical magnitude (median |value|) >= $1B, else 'M'."""
    vals = [abs(float(x)) for x in series if not _is_missing(x)]
    if not vals:
        return "M"
    vals.sort()
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return "B" if median >= _B_THRESHOLD else "M"


def fmt_eps(v) -> str:
    """Per-share earnings, always dollars-and-cents: '$2.45'."""
    if _is_missing(v):
        return "—"
    return f"${float(v):,.2f}"

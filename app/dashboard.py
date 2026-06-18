"""Streamlit dashboard — the demo surface for the PANW AI FP&A Copilot.

Six tabs, in the demo's "data ingestion → executive summary" order:
  Source Data | Forecast | Variance | Anomalies | Exec Summary | Chat

Designed for a non-technical FP&A / CFO-org user: every tab leads with a plain-
English bottom line + the few numbers that matter, defines every term in a hover
tooltip, and tucks methodology and dense tables inside "How this works" expanders.
Themed in Palo Alto Networks' brand (orange = branding only; green/red/amber carry
meaning). Backtest and Signals still run under the hood (and in tests) — they're
just not shown as tabs.  Run:  streamlit run app/dashboard.py
"""
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# On Streamlit Community Cloud the API key arrives via st.secrets, not an env var.
# Bridge it in BEFORE importing the LLM client (which reads the key at construction).
try:
    if not os.environ.get("ANTHROPIC_API_KEY") and "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config
from src import provenance as pv
from src.forecast import run_forecast, load_conformal_errors
from src.backtest import run_backtest                 # still used (powers Anomalies)
from src.variance import build_report, plain_bottom_line
from src.anomaly import build_report as build_anomalies
from src.summary import generate_brief
from src.chat import ask as chat_ask
from src.llm.client import client as llm

st.set_page_config(page_title="PANW AI FP&A Copilot", layout="wide")

# ---- Brand palette ---------------------------------------------------------
ORANGE = "#FA582D"   # PANW Outrageous Orange — branding/highlights ONLY
DARK = "#141414"
GRAY = "#F5F5F5"
FAV = "#00CC66"      # favorable (semantic)
UNFAV = "#D9362B"    # unfavorable (semantic)
CAUTION = "#FFCB06"  # caution / expected (semantic)
INFO = "#5B8DEF"     # informational (semantic, non-brand blue)
INORG = "#9AA0A6"    # acquisition / inorganic (neutral gray — not good/bad)

BRAND_CSS = f"""
<style>
  .brandhead {{ background:{ORANGE}; padding:18px 24px; border-radius:10px;
    margin-bottom:6px; }}
  .brandhead .t {{ color:#fff; font-size:1.6rem; font-weight:800; letter-spacing:.01em; }}
  .brandhead .s {{ color:#fff; opacity:.92; font-size:.95rem; }}
  /* metric cards */
  div[data-testid="stMetric"] {{ background:{GRAY}; border:1px solid #ECECEC;
    border-radius:10px; padding:14px 16px; }}
  div[data-testid="stMetricValue"] {{ color:{DARK}; font-weight:700; }}
  /* the plain-English bottom line */
  .bottomline {{ background:{GRAY}; border-left:5px solid {ORANGE}; padding:12px 16px;
    border-radius:8px; margin:4px 0 14px 0; font-size:1.03rem; color:{DARK}; }}
  .bottomline .tag {{ color:{ORANGE}; font-weight:800; text-transform:uppercase;
    font-size:.72rem; letter-spacing:.06em; margin-right:8px; }}
  /* pipeline flow */
  .flow {{ display:flex; flex-wrap:wrap; align-items:stretch; gap:6px; margin:6px 0; }}
  .flow .box {{ flex:1; min-width:120px; background:{GRAY}; border:1px solid #E4E4E4;
    border-radius:10px; padding:12px; text-align:center; color:{DARK};
    font-weight:600; font-size:.92rem; }}
  .flow .box small {{ font-weight:400; color:#5b5b5b; }}
  .flow .box.powers {{ border:2px solid {ORANGE}; }}
  .flow .arrow {{ display:flex; align-items:center; color:{ORANGE}; font-weight:800;
    font-size:1.3rem; }}
  /* tab labels a touch larger */
  button[data-baseweb="tab"] p {{ font-size:1.0rem; font-weight:600; }}
  h2, h3 {{ color:{DARK}; }}
</style>
"""
st.markdown(BRAND_CSS, unsafe_allow_html=True)


# ---- small helpers ---------------------------------------------------------
def md(text) -> str:
    """Escape $ so Streamlit markdown doesn't render dollar amounts as LaTeX math."""
    return str(text).replace("$", "\\$")


def fmt_m(v) -> str:
    return f"${v:,.0f}M"


def fmt_pct(v, signed=False) -> str:
    return (f"{v:+.1f}%" if signed else f"{v:.1f}%")


def bottom_line(html: str):
    """Render the plain-English 'Bottom line' callout (HTML → $ stays literal)."""
    st.markdown(f'<div class="bottomline"><span class="tag">Bottom line</span>{html}</div>',
                unsafe_allow_html=True)


def how_to_read(text: str):
    st.caption(f"*How to read this:* {text}")


# Plain-English names for raw metric/column identifiers (used by Anomalies).
METRIC_NAMES = {
    "revenue_total": "Total revenue",
    "revenue_organic": "Organic revenue",
    "revenue_product": "Product revenue",
    "revenue_subscription": "Subscription & support revenue",
    "inorganic_revenue": "Acquisition (inorganic) revenue",
    "rpo": "Backlog (RPO)",
    "ngs_arr": "Next-Gen Security ARR",
    "non_gaap_op_margin": "Operating margin",
    "segment_reconciliation": "Segment reconciliation",
    "organic_reconciliation": "Organic/inorganic reconciliation",
    "xbrl_cross_check": "Independent (XBRL) cross-check",
}


def prettify_metric(m: str) -> str:
    return METRIC_NAMES.get(m, m.replace("_", " ").capitalize())


# Plain finance labels for the detail-table columns (no snake_case shown to users).
COL_RENAME = {
    "line": "Line", "actual": "Actual", "plan": "Plan", "variance": "Variance",
    "variance_pct": "Variance %", "flag": "Status", "unit": "Unit",
    "driver": "Driver", "prior": "Prior", "current": "Current", "change": "Change",
    "change_pct": "Change %", "inorganic_part": "From acquisition", "organic_part": "Organic",
    "inorganic_pct": "Acquisition %", "organic_pct": "Organic %",
}


def pretty_table(df_in):
    return df_in.rename(columns=COL_RENAME)


# Plain row labels: drop the baseline already in the table title; make organic vs total explicit.
LINE_RENAME = {
    "Total revenue vs guidance midpoint": "Midpoint",
    "Total revenue vs guidance low": "Low",
    "Total revenue vs guidance high": "High",
    "Product revenue vs forecast": "Product",
    "Subscription & support vs forecast": "Subscription & support",
    "Organic revenue vs forecast": "Organic revenue (like-for-like)",
    "Total revenue vs forecast (organic basis)": "Total reported revenue (includes acquisition)",
}


def relabel_lines(df_in):
    if "line" not in df_in.columns:
        return df_in
    return df_in.assign(line=df_in["line"].map(lambda x: LINE_RENAME.get(x, x)))


def tint_variance(df_pretty):
    """Tint the Variance / Variance % cells green (favorable) or red (unfavorable)
    by the row's Status, so good-vs-bad reads at a glance."""
    cols = list(df_pretty.columns)

    def _row(r):
        c = FAV if r.get("Status") == "Favorable" else (
            UNFAV if r.get("Status") == "Unfavorable" else "")
        return [f"color:{c}; font-weight:600" if (col in ("Variance", "Variance %") and c)
                else "" for col in cols]
    return df_pretty.style.apply(_row, axis=1)


# Whole $M for money columns; one decimal for percents. No six-decimal floats shown to users.
_NUM_FMT = {
    "Actual": "{:,.0f}", "Plan": "{:,.0f}", "Variance": "{:,.0f}", "Variance %": "{:.1f}",
    "Prior": "{:,.0f}", "Current": "{:,.0f}", "Change": "{:,.0f}", "Change %": "{:.1f}",
    "From acquisition": "{:,.0f}", "Organic": "{:,.0f}",
    "Acquisition %": "{:.1f}", "Organic %": "{:.1f}",
}


def fmt_numbers(obj):
    """Apply whole-$M / one-decimal-% formatting to a DataFrame or Styler."""
    styler = obj.style if isinstance(obj, pd.DataFrame) else obj
    fmt = {c: f for c, f in _NUM_FMT.items() if c in styler.data.columns}
    return styler.format(fmt)


def variance_view(df):      # vs_guidance / segment / vs_forecast (F/U tinted)
    return fmt_numbers(tint_variance(pretty_table(relabel_lines(df))))


def driver_view(df):        # leading indicators (no F/U tint)
    return fmt_numbers(pretty_table(df))


def brand_layout(fig, height=420, ytitle="", xtitle=""):
    fig.update_layout(
        height=height, template="plotly_white",
        font=dict(family="sans-serif", color=DARK),
        paper_bgcolor="white", plot_bgcolor="white",
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title=ytitle, xaxis_title=xtitle,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0),
    )
    return fig


# ---- cached data access ----------------------------------------------------
@st.cache_data
def get_data():
    df = pd.read_csv(config.FINANCIALS_CSV, parse_dates=["period_end_date"])
    return df.sort_values("period_end_date").reset_index(drop=True)


@st.cache_data
def get_backtest_report():
    return run_backtest()


@st.cache_data
def get_variance(quarter):
    return build_report(quarter)


@st.cache_data
def get_anomalies(quarter):
    return build_anomalies(quarter, backtest=get_backtest_report())


@st.cache_data(show_spinner="Drafting executive brief…")
def get_brief(quarter):
    return generate_brief(quarter)


@st.cache_data
def get_quality():
    return pv.quality_stats(get_data())


df = get_data()
errors = load_conformal_errors()

# ---- branded header --------------------------------------------------------
st.markdown(
    '<div class="brandhead"><div class="t">PANW AI FP&amp;A Copilot</div>'
    '<div class="s">From SEC filings to a board-ready brief — every figure traced to a '
    'filing, and an AI that never invents a number.</div></div>',
    unsafe_allow_html=True)

_llm_badge = ("AI assistant: live" if llm.available
              else "AI assistant: offline (works fully; set a key for live answers)")
st.caption(_llm_badge)

tab_src, tab_fc, tab_var, tab_anom, tab_sum, tab_chat = st.tabs(
    ["Source Data", "Forecast", "Variance", "Anomalies", "Exec Summary", "Chat"])

# Plain-English tooltips reused across tabs
HELP = {
    "organic": "Revenue from the existing business — excludes anything gained through an acquisition.",
    "inorganic": "Revenue that came from an acquisition (here, CyberArk + Chronosphere), not the core business.",
    "range": "We're about 80% confident the real number lands inside this range.",
    "guidance": "The revenue range management publicly told investors to expect for the quarter.",
    "rpo": "Remaining Performance Obligations — signed contracts not yet recognized as revenue; a leading indicator of future sales.",
    "verified": "Every dollar amount and percentage in the text was automatically checked against the computed data — nothing is made up.",
    "xbrl": "A second, independent machine-readable feed of the same numbers, straight from the SEC.",
}

# ============================================================ Source Data tab
with tab_src:
    st.subheader("Where every number comes from")
    bottom_line("Every figure in this app is copied <b>verbatim from an official SEC filing</b> "
                "and cross-checked against a second, independent source. Nothing is estimated, "
                "averaged, or filled in.")

    q = get_quality()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Quarters of data", q["n_quarters"],
              help="One row per fiscal quarter, FY2021Q3 → FY2026Q3.")
    c2.metric("Cross-checked to the dollar", f'{q["n_xbrl_match"]} / {q["n_xbrl_checked"]}',
              help="Quarters where the press-release total matches the SEC's independent XBRL "
                   "feed exactly. " + HELP["xbrl"])
    c3.metric("Segments tie out", f'{q["n_segment"]} / {q["n_segment"]}' if q["segment_ok"] else "FAIL",
              help="Product + Subscription revenue equals total revenue, every quarter.")
    c4.metric("Estimated values", "0",
              help="We never interpolate. If a number wasn't disclosed, the cell stays blank.")

    # 1) Pipeline flow
    st.markdown("##### The pipeline")
    st.markdown(
        '<div class="flow">'
        '<div class="box">Sources<br><small>SEC 8-K releases · SEC XBRL API · transcripts</small></div>'
        '<div class="arrow">&rarr;</div>'
        '<div class="box">Extraction<br><small>each figure copied with a quote proving it</small></div>'
        '<div class="arrow">&rarr;</div>'
        '<div class="box">Validation<br><small>two sources agree · segments reconcile</small></div>'
        '<div class="arrow">&rarr;</div>'
        '<div class="box">Clean dataset<br><small>one tidy, sourced table</small></div>'
        '<div class="arrow">&rarr;</div>'
        '<div class="box powers">Powers<br><small>Forecast · Variance · Anomalies · Summary · Chat</small></div>'
        '</div>', unsafe_allow_html=True)
    how_to_read("data flows left to right — every number is proven and double-checked "
                "before it powers anything downstream.")

    # 2) Provenance — prove any number
    st.markdown("##### Prove any number")
    st.caption("Pick a quarter and see, for each metric, the exact wording from the filing that proves it.")
    pq = st.selectbox("Quarter", df["fiscal_quarter"].tolist()[::-1], index=0, key="prov_q")
    evidence = pv.load_evidence().get(pq, {})
    links = pv.source_links()
    prow = df[df["fiscal_quarter"] == pq].iloc[0]

    def _fmt_val(col, val):
        if pd.isna(val):
            return "—"
        if col == "non_gaap_op_margin":
            return fmt_pct(val)
        if "eps" in col:
            return f"${val:,.2f}"
        return fmt_m(val)

    prov_rows = []
    for col, label in pv.DISPLAY_METRICS:
        if col not in df.columns:
            continue
        quote = evidence.get(col, "")
        prov_rows.append({"Metric": label, "Value": _fmt_val(col, prow[col]),
                          "Evidence (verbatim from the filing)": quote or "—"})
    st.dataframe(pd.DataFrame(prov_rows), width="stretch", hide_index=True)
    if pq in links:
        st.markdown(f"[View the source 8-K filing for {pq} &rarr;]({links[pq]})")

    # 3) Data-quality: coverage map
    with st.expander("Show the detail — data coverage & quality"):
        st.caption("Which metrics were disclosed in which quarter. Blanks are genuine "
                   "non-disclosures, never estimates.")
        cov = pv.coverage_matrix(df)
        fig = go.Figure(go.Heatmap(
            z=cov.values, x=list(cov.columns), y=list(cov.index),
            colorscale=[[0, "#E8E8E8"], [1, DARK]], showscale=False, xgap=2, ygap=2,
            hovertemplate="%{y} · %{x}: %{customdata}<extra></extra>",
            customdata=[["disclosed" if v else "not disclosed" for v in row] for row in cov.values],
        ))
        brand_layout(fig, height=360)
        st.plotly_chart(fig, width="stretch")
        how_to_read("dark = the metric was disclosed that quarter; light = not disclosed "
                    "(e.g. billings stops after FY2024Q1; NGS ARR starts FY2024Q4).")

    # 4) Full dataset preview
    with st.expander("Show the detail — the full 21-quarter dataset"):
        cols = ["fiscal_quarter", "period_end_date", "revenue_total", "revenue_product",
                "revenue_subscription", "revenue_organic", "inorganic_revenue", "rpo",
                "ngs_arr", "billings", "non_gaap_op_margin", "non_gaap_eps_reported",
                "guidance_revenue_next_q_low", "guidance_revenue_next_q_high"]
        st.dataframe(df[[c for c in cols if c in df.columns]], width="stretch",
                     hide_index=True, height=380)

    # 5) Honesty callouts
    st.markdown("##### Our honesty rules")
    st.markdown(
        "- **No interpolation.** A number we couldn't source is left blank — never guessed.\n"
        "- **Acquisitions only where disclosed.** Inorganic revenue is recorded only where PANW "
        "stated a figure — so far one quarter: **FY2026Q3 = \\$388M** (CyberArk + Chronosphere).\n"
        "- **Stock splits handled.** PANW split its stock twice; per-share earnings are restated "
        "to today's basis so the history is comparable.")

# ============================================================== Forecast tab
with tab_fc:
    st.subheader("Revenue forecast")

    # Controls sit above the chart so the forecast reacts in plain sight.
    c1, c2 = st.columns(2)
    horizon = c1.slider("Quarters ahead to forecast", 1, 4, config.FORECAST_HORIZON,
                        help="How many future quarters to project.")
    method = c2.radio("Range method",
                      ["honest range (based on past accuracy)", "model's own estimate"],
                      horizontal=True,
                      help="The honest range sets the band from real past errors (well-calibrated). "
                           "The model's own estimate was over-confident in testing.")
    config.INTERVAL_METHOD = "conformal" if method.startswith("honest") else "mc"
    res = run_forecast(df=df, horizon=horizon, conformal_errors=errors)
    nq = res.future_quarters[0]
    pt, lo, hi = res.total_point[0], res.total_low[0], res.total_high[0]

    bottom_line(f"For <b>{nq}</b> we expect organic revenue of about <b>{fmt_m(pt)}</b>, "
                f"most likely between <b>{fmt_m(lo)}</b> and <b>{fmt_m(hi)}</b>.")

    k1, k2, k3 = st.columns(3)
    k1.metric("Next quarter", nq, help="The next quarter we forecast.")
    k2.metric("Most likely revenue (organic)", fmt_m(pt),
              help="Organic revenue — " + HELP["organic"])
    k3.metric("80% range ($M)", f"{lo:,.0f} – {hi:,.0f}", help=HELP["range"])

    hist = df[df["inorganic_revenue"] == 0]
    last_q, last_v = hist["fiscal_quarter"].iloc[-1], float(hist["revenue_total"].iloc[-1])
    fq = list(res.future_quarters)
    # Connect the forecast to the last actual point so it continues, not floats.
    fc_x = [last_q] + fq
    fc_pt = [last_v] + list(res.total_point)
    band_lo = [last_v] + list(res.total_low)
    band_hi = [last_v] + list(res.total_high)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["fiscal_quarter"], y=hist["revenue_total"],
                             mode="lines+markers", name="Actual (history)",
                             line=dict(color=DARK)))
    fig.add_trace(go.Scatter(x=fc_x, y=band_hi, mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fc_x, y=band_lo, mode="lines", fill="tonexty",
                             fillcolor="rgba(250,88,45,0.22)", line=dict(width=0),
                             name="80% range"))
    fig.add_trace(go.Scatter(x=fc_x, y=fc_pt, mode="lines+markers",
                             name="Forecast (organic)", line=dict(color=ORANGE, dash="dash")))
    # Boundary between the last actual and the first forecast quarter.
    fig.add_vline(x=len(hist) - 0.5, line=dict(color="rgba(120,120,120,0.5)", dash="dot", width=1),
                  annotation_text="forecast →", annotation_position="top",
                  annotation_font=dict(size=11, color="#777"))
    # Tie the headline card's quarter to its point on the line.
    fig.add_annotation(x=nq, y=pt, text=f"<b>{fmt_m(pt)}</b>", showarrow=True, arrowhead=2,
                       ax=0, ay=-32, font=dict(color=ORANGE, size=12),
                       arrowcolor=ORANGE)
    all_q = list(hist["fiscal_quarter"]) + fq
    fig.update_xaxes(tickmode="array", tickvals=all_q[::2], tickangle=-45)
    brand_layout(fig, height=440, ytitle="Revenue ($M)", xtitle="Fiscal quarter")
    st.plotly_chart(fig, width="stretch")
    st.caption("Forecast is **organic**; acquisitions are added separately (see the Variance tab).")
    how_to_read("the dark line is actual history; the dashed orange line (continuing from the last "
                "actual point) is our best estimate; the shaded band is the range we're ~80% "
                "confident in. The labeled point is the headline number above.")

    with st.expander("How this works"):
        st.markdown(
            "- We forecast each revenue stream with **ETS** — a standard, transparent time-series "
            "method that tracks the trend and the repeating yearly pattern (PANW's big Q4). No "
            "black-box AI: with only ~20 quarters of data, a simple, explainable model is the honest choice.\n"
            "- The range width is set by **how wrong the model actually was on past quarters** (a "
            "technique called *conformal*), not by the model's own optimism. We tested it on history "
            "and the 80% range contained the truth about **86%** of the time — i.e. it's honest.\n"
            "- We forecast the **organic** business and add acquisitions separately, so a one-time "
            "deal can't masquerade as underlying momentum.")
        fc_tbl = res.to_frame().rename(columns={
            "fiscal_quarter": "Quarter", "revenue_product_point": "Product",
            "revenue_subscription_point": "Subscription", "total_point": "Forecast",
            "total_low": "Low (80%)", "total_high": "High (80%)"})
        st.dataframe(fc_tbl, width="stretch", hide_index=True)

        held = df[df["inorganic_revenue"] > 0]
        if not held.empty and res.future_quarters[0] == held["fiscal_quarter"].iloc[0]:
            a = held["revenue_organic"].iloc[0]
            inside = lo <= a <= hi
            st.info(md(f"**Out-of-sample check — {held['fiscal_quarter'].iloc[0]}:** we forecast "
                       f"organic {fmt_m(pt)} (range {fmt_m(lo)}–{fmt_m(hi)}); the actual organic "
                       f"number was {fmt_m(a)} → {'inside' if inside else 'just outside'} the band "
                       f"({(pt-a)/a*100:+.1f}%). A genuine test: the model never saw this quarter."))

# ============================================================== Variance tab
with tab_var:
    st.subheader("Why results differed from plan")
    quarters = df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist() + \
        df["fiscal_quarter"].tolist()[-6:]
    quarters = list(dict.fromkeys(quarters))
    qv = st.selectbox("Quarter", quarters, index=0, key="var_q")
    rep = get_variance(qv)
    s = rep.summary

    # Plain-English bottom line, computed (verifier-clean) — never hardcoded.
    bottom_line(plain_bottom_line(rep))

    st.metric("Actual revenue", fmt_m(s["actual_total"]),
              help="Total reported revenue for the quarter (organic + acquisitions).")
    g1, g2 = st.columns([2, 1])
    with g1:
        st.markdown("**vs our forecast**")
        f1, f2 = st.columns(2)
        f1.metric("Organic outperformance", fmt_m(s["organic_beat_$"]),
                  help="The core business (" + HELP["organic"].lower() + ") vs our model's forecast.")
        share = s.get("inorganic_share_of_beat_%")
        f2.metric("From acquisition", fmt_m(s["inorganic"]),
                  delta=(f"{share:.0f}% of the beat vs forecast" if share is not None else None),
                  delta_color="off", help=HELP["inorganic"])
    with g2:
        st.markdown("**vs guidance**")
        st.metric("Beat guidance", fmt_m(s["vs_guidance_$"]),
                  delta=f"{fmt_pct(s['vs_guidance_%'], signed=True)} · {s['vs_guidance_flag']}",
                  help=HELP["guidance"])

    # Manual waterfall so organic (green) and acquisition (gray) read differently —
    # the key insight shows in the bars, not just the labels.
    b = rep.bridge
    colmap = {"start": DARK, "end": DARK, "favorable": FAV, "unfavorable": UNFAV, "inorganic": INORG}
    xs, bases, heights, colors, texts = [], [], [], [], []
    running = 0.0
    for r in b.itertuples(index=False):
        amt, kind = float(r.amount), r.kind
        if kind in ("start", "end"):
            bases.append(0.0); heights.append(amt)
            if kind == "start":
                running = amt
        else:
            bases.append(running if amt >= 0 else running + amt)
            heights.append(abs(amt))
            running += amt
        xs.append(r.step); colors.append(colmap.get(kind, DARK)); texts.append(fmt_m(amt))
    fig = go.Figure(go.Bar(x=xs, y=heights, base=bases, marker_color=colors, width=0.6,
                           text=texts, textposition="outside",
                           hovertemplate="%{x}: %{text}<extra></extra>"))
    fig.add_hline(y=s["guidance_midpoint"],
                  line=dict(color="rgba(110,110,110,0.7)", dash="dot", width=1),
                  annotation_text=f"Guidance {fmt_m(s['guidance_midpoint'])}",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color="#777"))
    brand_layout(fig, height=440, ytitle="Revenue ($M)")
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig, width="stretch")
    how_to_read("each block moves from our forecast (left) to actual revenue (right). "
                "**Green** = organic gain · **gray** = acquisition · **red** = shortfall. "
                "The dotted line is management guidance.")

    with st.expander("Show the detail — full attribution"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**vs management guidance**")
            st.caption("Did we beat the revenue targets we told investors? Guidance already "
                       "included the acquisition, so this beat is organic execution.")
            st.dataframe(variance_view(rep.vs_guidance),
                         width="stretch", hide_index=True)
            st.markdown("**By segment (vs forecast)**")
            st.caption("How each revenue segment did vs. our forecast. Note: actuals include "
                       "acquisition revenue but the forecast is organic, so these beats are inflated.")
            st.dataframe(variance_view(rep.segment_attribution),
                         width="stretch", hide_index=True)
        with c2:
            st.markdown("**Leading indicators (organic vs acquired)**")
            st.caption("How much of our backlog (RPO) and ARR growth came from the core "
                       "business vs. the acquisition. Organic % is the real underlying "
                       "growth (~3–4%); the rest of the headline growth is the acquisition.")
            st.dataframe(driver_view(rep.driver_attribution),
                         width="stretch", hide_index=True)
            st.markdown("**vs our forecast**")
            st.caption("Our forecast was organic. Row 1 is organic-to-organic (the real beat); "
                       "row 2 compares total reported revenue, which includes the acquisition, "
                       "to that organic forecast — the gap between them is the acquisition.")
            st.dataframe(variance_view(rep.vs_forecast),
                         width="stretch", hide_index=True)

# ============================================================== Anomalies tab
with tab_anom:
    st.subheader("What's worth a closer look")
    aq = st.selectbox("Quarter to focus on", df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist()
                      + df["fiscal_quarter"].tolist()[-6:], key="anom_q")
    aq = list(dict.fromkeys([aq]))[0]
    arep = get_anomalies(aq)
    items = arep.anomalies
    unexpl = [a for a in items if a.status == "unexplained"]
    expl = [a for a in items if a.status == "explained"]
    crit = [a for a in unexpl if a.severity == "critical"]

    bottom_line(f"We scanned all {len(arep.quarters_scanned)} quarters. <b>{len(items)}</b> items "
                f"look unusual — <b>{len(expl)}</b> we can already explain (e.g. the CyberArk "
                f"acquisition), and <b>{len(unexpl)}</b> are worth a human look.")

    k1, k2, k3 = st.columns(3)
    k1.metric("Items flagged", len(items),
              help="Anything that broke a data tie-out, jumped outside its normal range, or "
                   "landed outside the trustworthy forecast band.")
    k2.metric("To investigate", len(unexpl),
              delta=f"{len(crit)} high-priority" if crit else "none high-priority",
              delta_color="inverse" if crit else "off",
              help="Unusual AND no known cause — these deserve attention.")
    k3.metric("Already explained", len(expl), delta_color="off",
              help="Unusual but accounted for by a disclosure (e.g. an acquisition).")

    def _render(lst, header, empty):
        st.markdown(f"##### {header}")
        if not lst:
            st.caption(empty)
            return
        for a in lst:
            with st.expander(f"{a.quarter} · {prettify_metric(a.metric)}",
                             expanded=(a.severity == "critical")):
                st.markdown(md(a.why))
                if a.explanation:
                    st.success(md(f"Expected — {a.explanation}"))
                elif a.severity == "critical":
                    st.error("High priority — no known cause; investigate.")
                elif a.severity == "warning":
                    st.warning("Worth a look — outside the normal range.")
                else:
                    st.info("Minor — slightly outside the normal range.")

    _render(unexpl, "To investigate", "Nothing unexplained — every flag is accounted for.")
    _render(expl, "Already explained", "No disclosure-explained items this scan.")

    with st.expander("How this works"):
        st.markdown(
            "- **Data tie-outs:** do the segments still add up to the total? does the second "
            "source still agree? (catches a mistyped number).\n"
            "- **Outside its normal range:** we use a *robust* statistical test — it measures how "
            "far a value sits from its typical level using the **median** (so one extreme value "
            "can't hide itself), and compares year-over-year to ignore normal seasonality.\n"
            "- **Outside the forecast band:** an actual that lands beyond the trustworthy "
            "(calibrated) forecast range.\n"
            "- Then we **label each flag**: *expected* if a disclosure explains it (like the "
            "acquisition), or *investigate* if not. That judgment is the point — a CFO wants the "
            "one alarm with a real cause, not fifty.")
        st.dataframe(arep.to_frame(), width="stretch", hide_index=True)

# ============================================================ Exec Summary tab
with tab_sum:
    st.subheader("The board-ready brief")
    bottom_line("An AI writes the one-page summary from the numbers above — and <b>every figure "
                "is automatically checked</b> against the computed data, so nothing is invented.")
    qs = st.selectbox("Quarter", df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist()
                      + df["fiscal_quarter"].tolist()[-4:], key="sum_q")
    qs = list(dict.fromkeys([qs]))[0]
    brief = get_brief(qs)
    if brief.verified:
        st.success("All figures verified against the computed data.")
    else:
        st.error(md(f"{len(brief.violations)} unverifiable figure(s): "
                    f"{[v.raw for v in brief.violations]}"))
    st.caption(HELP["verified"] + f"  ·  Writer: {brief.source}")

    display = md(brief.text)
    if display.startswith("# "):
        display = "### " + display[2:]
    st.markdown(display)
    st.download_button("Download the brief (Markdown)", brief.text,
                       file_name=f"PANW_exec_brief_{qs}.md", mime="text/markdown")

    with st.expander("How this works"):
        st.markdown(
            "- The AI is handed a **FACTS block** — the only numbers it's allowed to use — and "
            "told to write prose, never to calculate.\n"
            "- A separate checker then reads the draft, pulls out every dollar amount and "
            "percentage, and matches each against the computed values. Any number that doesn't "
            "match is **rejected and the draft is rewritten**. That gate is what makes an AI safe "
            "to point at financial numbers.")

# =================================================================== Chat tab
with tab_chat:
    st.subheader("Ask your financials")
    bottom_line("Ask anything in plain English. Answers come <b>only from the computed numbers</b>, "
                "with the quarter cited and every figure verified.")
    examples = ["What drove the FY2026Q3 revenue beat?",
                "Is anything anomalous this quarter?",
                "What's the revenue forecast for next quarter?",
                "How big was the CyberArk contribution?"]
    cols = st.columns(len(examples))
    for i, ex in enumerate(examples):
        # Write the preset into session_state BEFORE the input is created, so a
        # keyed text_input picks it up (passing value= is ignored once keyed).
        if cols[i].button(ex, key=f"ex{i}"):
            st.session_state["chat_q"] = ex
    question = st.text_input("Your question", key="chat_q",
                             placeholder="e.g. How is the core business doing?")
    if question:
        ans = chat_ask(question)
        if ans.verified:
            st.success("Verified against the computed data.")
        else:
            st.warning("This answer contains figures we couldn't verify — treat with caution.")
        st.markdown(md(ans.text))

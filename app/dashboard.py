"""Stage 6 — Streamlit dashboard (MVP slice: Forecast + Backtest tabs).

Run:  streamlit run app/dashboard.py
Tabs are added as later phases land (Variance, Signals, Summary, Chat).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# On Streamlit Community Cloud the API key is provided via st.secrets, not as an
# env var. Bridge it into the environment BEFORE importing the LLM client (which
# reads ANTHROPIC_API_KEY at construction). Locally this is a no-op (.env wins).
try:
    if not os.environ.get("ANTHROPIC_API_KEY") and "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config
from src import framing
from src.forecast import run_forecast, load_conformal_errors
from src.backtest import run_backtest
from src.variance import build_report
from src.anomaly import build_report as build_anomalies
from src.signals import build as build_signals
from src.summary import generate_brief
from src.chat import ask as chat_ask
from src.llm.client import client as llm

st.set_page_config(page_title="PANW AI FP&A Copilot", layout="wide", page_icon="📊")


def md(text: str) -> str:
    """Escape $ so Streamlit markdown doesn't render dollar amounts as LaTeX math."""
    return str(text).replace("$", "\\$")


@st.cache_data
def get_data():
    df = pd.read_csv(config.FINANCIALS_CSV, parse_dates=["period_end_date"])
    return df.sort_values("period_end_date").reset_index(drop=True)


@st.cache_data
def get_backtest_report():
    return run_backtest()


@st.cache_data
def get_backtest():
    rep = get_backtest_report()
    return rep.steps, rep.metrics, rep.calibration, rep.headline


@st.cache_data
def get_variance(quarter):
    return build_report(quarter)


@st.cache_data
def get_anomalies(quarter):
    # Reuse the cached walk-forward run rather than recomputing it.
    return build_anomalies(quarter, backtest=get_backtest_report())


@st.cache_data(show_spinner="Extracting transcript signals…")
def get_signals():
    return build_signals()


@st.cache_data(show_spinner="Drafting executive brief…")
def get_brief(quarter):
    return generate_brief(quarter)


df = get_data()
errors = load_conformal_errors()

st.title("📊 PANW AI FP&A Copilot")
st.caption("Driver-based, backtested, probabilistic revenue forecasting on Palo Alto "
           "Networks public financials — forecast → validate → (variance → anomaly → "
           "signals → executive summary). Every figure traces to an SEC filing; the LLM "
           "never invents numbers.")

with st.container(border=True):
    st.markdown("#### 👤 Who this is for / what it answers")
    st.markdown(framing.TAGLINE)


def lens(key):
    """Render the user-need framing (who · decision · why) for a tab."""
    st.info(framing.caption(key))


tab_fc, tab_bt, tab_var, tab_anom, tab_sig, tab_sum, tab_chat = st.tabs(
    ["🔮 Forecast", "✅ Backtest & Validation", "📐 Variance & Attribution",
     "🚨 Anomalies", "🗣️ Signals", "📝 Exec Summary", "💬 Chat"])

_llm_badge = ("🟢 Claude (live)" if llm.available
              else "⚪ offline mode — set ANTHROPIC_API_KEY for live Claude")
st.caption(f"LLM layer: {_llm_badge}")

# ---------------------------------------------------------------- Forecast tab
with tab_fc:
    st.subheader("Probabilistic organic-revenue forecast")
    lens("forecast")
    c1, c2, c3 = st.columns(3)
    horizon = c1.slider("Forecast horizon (quarters)", 1, 4, config.FORECAST_HORIZON)
    method = c3.radio("Interval method", ["conformal", "mc"],
                      index=0 if config.INTERVAL_METHOD == "conformal" else 1,
                      horizontal=True,
                      help="Conformal = band width learned from walk-forward "
                           "residuals (well-calibrated, 86% coverage). MC = model's own "
                           "variance (overconfident in backtest, 43%).")
    sigma = c2.slider("Uncertainty scale (Monte Carlo)", 0.5, 2.5,
                      config.ASSUMPTION_SIGMA_SCALE, 0.1,
                      disabled=(method == "conformal"),
                      help="Stress-tests the model's own uncertainty width. Only affects "
                           "the 'mc' interval — switch the method to 'mc' to see it move "
                           "the band.")
    if method == "conformal":
        c2.caption("↔ applies to the **mc** interval — switch to enable")

    config.INTERVAL_METHOD = method  # honor the live toggle
    res = run_forecast(df=df, horizon=horizon, sigma_scale=sigma,
                       conformal_errors=errors)

    hist = df[df["inorganic_revenue"] == 0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["fiscal_quarter"], y=hist["revenue_total"],
                             mode="lines+markers", name="Actual (organic)",
                             line=dict(color="#1f77b4")))
    fq = res.future_quarters
    fig.add_trace(go.Scatter(x=fq, y=res.total_high, mode="lines",
                             line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fq, y=res.total_low, mode="lines", fill="tonexty",
                             fillcolor="rgba(255,127,14,0.2)", line=dict(width=0),
                             name=f"{config.PREDICTION_INTERVAL:.0%} band ({res.interval_method})"))
    fig.add_trace(go.Scatter(x=fq, y=res.total_point, mode="lines+markers",
                             name="Forecast", line=dict(color="#ff7f0e", dash="dash")))
    fig.update_layout(height=460, yaxis_title="Total revenue ($M)",
                      xaxis_title="Fiscal quarter", hovermode="x unified",
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, width="stretch")

    st.markdown(f"**Training cutoff:** {res.training_cutoff} (organic-only) · "
                f"**Models:** ETS (mul. seasonal) per segment, summed · "
                f"**Interval:** {res.interval_method}")
    fc_tbl = res.to_frame()
    st.dataframe(fc_tbl, width="stretch", hide_index=True)

    held = df[df["inorganic_revenue"] > 0]
    if not held.empty and res.future_quarters[0] == held["fiscal_quarter"].iloc[0]:
        a = held["revenue_organic"].iloc[0]
        pt, lo, hi = res.total_point[0], res.total_low[0], res.total_high[0]
        inside = lo <= a <= hi
        st.info(f"**Out-of-sample check — {held['fiscal_quarter'].iloc[0]} "
                f"(held out, acquisition-contaminated):** forecast organic "
                f"**{pt:,.0f}**, 80% band [{lo:,.0f}, {hi:,.0f}], actual organic "
                f"(total − \\${held['inorganic_revenue'].iloc[0]:,.0f}M CyberArk/"
                f"Chronosphere) = **{a:,.0f}** → {'inside' if inside else 'just outside'} "
                f"band, error {(pt-a)/a*100:+.1f}%.")

# --------------------------------------------------------------- Backtest tab
with tab_bt:
    steps, metrics, calib, headline = get_backtest()
    st.subheader("Walk-forward validation (no leakage)")
    lens("backtest")
    st.success(headline)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Model MAPE", f"{metrics['model']['MAPE']:.2f}%")
    m2.metric("Naive (drift) MAPE", f"{metrics['naive']['MAPE']:.2f}%",
              delta=f"{metrics['model']['MAPE']-metrics['naive']['MAPE']:.2f} pp",
              delta_color="inverse")
    m3.metric("Seasonal-naive MAPE", f"{metrics['seasonal_naive']['MAPE']:.2f}%")
    m4.metric("Mgmt guidance MAPE", f"{metrics['guidance']['MAPE']:.2f}%")

    st.markdown("##### Calibration of the 80% interval")
    cc1, cc2 = st.columns(2)
    cc1.metric("Monte Carlo coverage", f"{calib['mc_coverage']:.0%}",
               help=calib["mc_verdict"])
    cc2.metric("Conformal coverage", f"{calib['conformal_coverage']:.0%}",
               delta=calib["conformal_verdict"], delta_color="off")
    st.caption(f"Nominal target: {calib['nominal']:.0%} · n = {calib['n']} "
               f"walk-forward quarters. The model's own Monte Carlo variance is "
               f"overconfident; conformal intervals (width learned from "
               f"out-of-sample residuals) restore calibration.")

    # Actual vs model with conformal band over the backtest window.
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=steps["predict_quarter"], y=steps["conf_high"],
                              line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig2.add_trace(go.Scatter(x=steps["predict_quarter"], y=steps["conf_low"],
                              fill="tonexty", fillcolor="rgba(44,160,44,0.15)",
                              line=dict(width=0), name="Conformal 80% band"))
    fig2.add_trace(go.Scatter(x=steps["predict_quarter"], y=steps["model"],
                              mode="lines+markers", name="Model forecast",
                              line=dict(color="#ff7f0e", dash="dash")))
    fig2.add_trace(go.Scatter(x=steps["predict_quarter"], y=steps["actual"],
                              mode="lines+markers", name="Actual",
                              line=dict(color="#1f77b4")))
    fig2.update_layout(height=420, yaxis_title="Organic revenue ($M)",
                       xaxis_title="Predicted quarter", hovermode="x unified",
                       legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig2, width="stretch")
    st.dataframe(steps, width="stretch", hide_index=True)

# --------------------------------------------------------------- Variance tab
with tab_var:
    st.subheader("Automated variance analysis & attribution")
    lens("variance")
    quarters = df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist() + \
        df["fiscal_quarter"].tolist()[-6:]
    quarters = list(dict.fromkeys(quarters))  # de-dupe, keep order
    q = st.selectbox("Quarter (actuals)", quarters, index=0)
    rep = get_variance(q)
    s = rep.summary

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Actual total", f"${s['actual_total']:,.0f}M")
    k2.metric("vs guidance", f"${s['vs_guidance_$']:+,.0f}M",
              delta=f"{s['vs_guidance_%']:+.1f}% · {s['vs_guidance_flag']}")
    k3.metric("Organic beat vs forecast", f"${s['organic_beat_$']:+,.0f}M")
    k4.metric("Inorganic (M&A)", f"${s['inorganic']:,.0f}M",
              delta=(f"{s['inorganic_share_of_beat_%']:.0f}% of beat vs forecast"
                     if s.get("inorganic_share_of_beat_%") is not None else None),
              delta_color="off")

    # Waterfall bridge: forecast (organic) -> +organic beat -> +inorganic -> actual
    b = rep.bridge
    measure = ["absolute", "relative", "relative", "total"][: len(b)]
    fig3 = go.Figure(go.Waterfall(
        orientation="v", measure=measure,
        x=b["step"], y=b["amount"],
        text=[f"${v:,.0f}M" for v in b["amount"]], textposition="outside",
        connector=dict(line=dict(color="rgba(120,120,120,0.5)")),
        decreasing=dict(marker=dict(color="#d62728")),
        increasing=dict(marker=dict(color="#2ca02c")),
        totals=dict(marker=dict(color="#1f77b4")),
    ))
    fig3.update_layout(height=440, yaxis_title="Revenue ($M)",
                       title=f"Variance bridge — {q}: forecast → actual")
    st.plotly_chart(fig3, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Variance vs management guidance**")
        st.dataframe(rep.vs_guidance, width="stretch", hide_index=True)
        st.markdown("**Segment attribution (vs forecast)**")
        st.dataframe(rep.segment_attribution, width="stretch", hide_index=True)
    with c2:
        st.markdown("**Driver attribution — leading indicators (organic vs inorganic)**")
        st.dataframe(rep.driver_attribution, width="stretch", hide_index=True)
        st.markdown("**Variance vs forecast**")
        st.dataframe(rep.vs_forecast, width="stretch", hide_index=True)

    st.markdown("**Notes (timing vs permanent, caveats)**")
    for n in rep.notes:
        st.markdown(f"- {md(n)}")

# -------------------------------------------------------------- Anomalies tab
with tab_anom:
    st.subheader("Discrepancy & anomaly detection (Stage 3.5)")
    lens("anomaly")
    st.caption("Interpretable, rule-based flags reusing the data + forecast outputs — "
               "accounting tie-outs, trend/seasonality band breaks (robust z), and "
               "actuals outside the calibrated forecast band. Each flag is cross-checked "
               "against known disclosures and labeled **expected (explained)** vs "
               "**unexplained (investigate)** — the judgment a human analyst adds.")
    aq = st.selectbox("Focus quarter (forecast-relative check)",
                      df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist()
                      + df["fiscal_quarter"].tolist()[-6:], key="anom_q")
    aq = list(dict.fromkeys([aq]))[0]
    arep = get_anomalies(aq)
    items = arep.anomalies
    unexpl = [a for a in items if a.status == "unexplained"]
    expl = [a for a in items if a.status == "explained"]
    crit = [a for a in unexpl if a.severity == "critical"]

    a1, a2, a3 = st.columns(3)
    a1.metric("Flags", len(items))
    a2.metric("Unexplained (investigate)", len(unexpl),
              delta=f"{len(crit)} critical" if crit else "none critical",
              delta_color="inverse" if crit else "off")
    a3.metric("Expected (explained)", len(expl), delta_color="off")

    _emoji = {"critical": "🔴", "warning": "🟠", "info": "🔵"}

    def _render(anom_list, header, empty_msg):
        st.markdown(f"##### {header}")
        if not anom_list:
            st.caption(empty_msg)
            return
        for a in anom_list:
            label = (f"{_emoji[a.severity]} **{a.quarter} · {a.metric}** "
                     f"({a.detector}, {a.severity})")
            with st.expander(label, expanded=(a.severity == "critical")):
                st.markdown(md(a.why))
                if a.explanation:
                    st.success(md(f"Expected — {a.explanation}"))
                else:
                    st.warning("Unexplained — worth a human look.")

    _render(unexpl, "🔴 Unexplained — investigate",
            "Nothing unexplained — every flagged item is accounted for.")
    _render(expl, "🟢 Expected — explained by disclosure",
            "No disclosure-explained anomalies this scan.")

    st.markdown("##### All flags")
    st.dataframe(arep.to_frame(), width="stretch", hide_index=True)
    st.caption(" · ".join(md(n) for n in arep.notes))

# ---------------------------------------------------------------- Signals tab
with tab_sig:
    st.subheader("Transcript signal layer (Stage 4)")
    lens("signals")
    sig = get_signals()
    src = sig["source"].iloc[0] if not sig.empty else "n/a"
    st.caption(f"Signal source: **{src}** · sentiment / guidance tone / topic emphasis "
               "extracted from management commentary, joinable to financials by quarter.")
    st.dataframe(sig.drop(columns=["key_quote"]), width="stretch", hide_index=True)

    # Does guidance tone precede the next quarter's revenue surprise?
    tone_num = {"raising": 1, "holding": 0, "lowering": -1}
    sig["_tone"] = sig["guidance_tone"].map(tone_num)
    sig["_next_surprise"] = sig["revenue_surprise_pct"].shift(-1)
    plot = sig.dropna(subset=["_tone", "_next_surprise"])
    if not plot.empty:
        fig = go.Figure(go.Scatter(
            x=plot["_tone"], y=plot["_next_surprise"], mode="markers+text",
            text=plot["fiscal_quarter"], textposition="top center",
            marker=dict(size=10, color="#9467bd")))
        corr = plot["_tone"].corr(plot["_next_surprise"])
        fig.update_layout(height=380, xaxis_title="Guidance tone (-1 lower / 0 hold / +1 raise)",
                          yaxis_title="NEXT-quarter revenue surprise (%)",
                          title=f"Signal vs subsequent surprise (corr = {corr:+.2f})")
        st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------ Exec Summary tab
with tab_sum:
    st.subheader("LLM executive summary (Stage 5)")
    lens("summary")
    q = st.selectbox("Quarter", df[df["inorganic_revenue"] > 0]["fiscal_quarter"].tolist()
                     + df["fiscal_quarter"].tolist()[-4:], key="sum_q")
    q = list(dict.fromkeys([q]))[0]
    brief = get_brief(q)
    badge = "✅ all figures verified against computed data" if brief.verified else \
        f"❌ {len(brief.violations)} unverifiable figure(s): {[v.raw for v in brief.violations]}"
    (st.success if brief.verified else st.error)(
        md(f"Number-verification harness: {badge}  ·  source: {brief.source}"))
    display = md(brief.text)
    if display.startswith("# "):       # demote the brief's H1 (tab already has a header)
        display = "### " + display[2:]
    st.markdown(display)
    st.download_button("⬇️ Download brief (Markdown)", brief.text,  # raw $ in the .md
                       file_name=f"PANW_exec_brief_{q}.md", mime="text/markdown")

# -------------------------------------------------------------------- Chat tab
with tab_chat:
    st.subheader("Chat with your financials")
    lens("chat")
    st.caption("Ask in plain English. Answers come ONLY from the computed pipeline — "
               "financials, forecast, variance, and the anomaly scan — every figure "
               "quarter-cited, source-tagged, and routed through the number-verification "
               "harness. Try the examples, or ask your own.")
    examples = ["What drove the FY2026Q3 revenue beat?",
                "Is anything anomalous this quarter?",
                "What's the revenue forecast for next quarter?",
                "How big was the CyberArk contribution?"]
    cols = st.columns(len(examples))
    preset = next((examples[i] for i, c in enumerate(cols)
                   if c.button(examples[i], key=f"ex{i}")), None)
    question = st.text_input("Ask a question", value=preset or "", key="chat_q")
    if question:
        ans = chat_ask(question)
        (st.success if ans.verified else st.warning)(
            f"{'✅ verified against computed data' if ans.verified else '⚠️ contains unverifiable figures'} "
            f"· source: {ans.source}")
        st.markdown(md(ans.text))

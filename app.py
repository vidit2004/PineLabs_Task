"""Streamlit entry point for the bank comparison."""
from pathlib import Path
from math import ceil, floor

import altair as alt
import pandas as pd
import streamlit as st

from analyst.analysis import Comparison, DailyTrend
from analyst.data import QualityError
from analyst.plan import Clarification
from analyst.planner import QUESTION, TREND_QUESTION, PlannerError, ask

FIXTURES = Path(__file__).resolve().parent / "data" / "fixtures"


def percentage(rate):
    return "Unavailable" if rate is None else f"{float(rate):.1%}"


def points(effect):
    return "Unavailable" if effect is None else f"{float(effect):+.1f} pp"


def show_comparison(result: Comparison, fixture: str):
    st.subheader("Comparison overview")
    baseline, current = result.rates["baseline"], result.rates["current"]
    change = None if baseline is None or current is None else 100 * (current - baseline)
    before, after, difference = st.columns(3)
    before.metric("Baseline success rate", percentage(baseline), border=True)
    after.metric("Current success rate", percentage(current), border=True)
    difference.metric("Observed change", points(change), border=True)

    if result.rows:
        st.subheader("Bank performance")
        totals = {period: sum(row.attempts for row in result.rows if row.period == period)
                  for period in result.rates}
        table = pd.DataFrame([{"Bank": row.bank_name, "Period": row.period.title(),
                               "Successes": row.successes, "Attempts": row.attempts,
                               "Rate": float(row.rate), "Attempt share": row.attempts / totals[row.period]}
                              for row in result.rows])
        base = alt.Chart(table).encode(
            y=alt.Y("Bank:N", title=None, axis=alt.Axis(labelFontSize=13, ticks=False, domain=False)),
            yOffset=alt.YOffset("Period:N", sort=["Baseline", "Current"]),
            x=alt.X("Rate:Q", title="Success rate", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%", values=[0, .2, .4, .6, .8, 1])),
            tooltip=["Bank", "Period", alt.Tooltip("Rate:Q", format=".1%"), "Attempts", "Successes"])
        bars = base.mark_bar(size=30, cornerRadiusEnd=4).encode(
            color=alt.Color("Period:N", title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(domain=["Baseline", "Current"], range=["#103F30", "#087F4C"])))
        labels = base.mark_text(fontSize=14, fontWeight="bold", dx=alt.ExprRef(expr="datum.Rate >= 0.15 ? -32 : 32")).encode(
            text=alt.Text("Rate:Q", format=".1%"),
            color=alt.condition("datum.Rate >= 0.15", alt.value("white"), alt.value("#172D36")))
        chart = (bars + labels).properties(width="container", height=120 + 120 * table["Bank"].nunique())
        chart = chart.configure_axis(labelFontSize=13, titleFontSize=13, labelColor="#334F41",
                                     titleColor="#17352A", gridColor="#DAE8DF").configure_legend(
            labelFontSize=14, labelColor="#334F41", symbolSize=140, padding=6).configure_view(stroke=None)
        st.altair_chart(chart, use_container_width=True)
        for column in ("Rate", "Attempt share"):
            table[column] = table[column].map(percentage)
        st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("Findings")
    if result.limitation:
        st.info(result.limitation)
    else:
        mix, within = st.columns(2)
        mix.metric("Bank mix effect", points(result.mix_pp))
        within.metric("Within-bank effect", points(result.performance_pp))
        st.caption("Mix uses baseline bank rates. Within-bank performance uses current attempt shares.")
        if result.mix_pp or result.performance_pp:
            hypotheses, actions = st.columns(2)
            hypotheses.markdown("#### Hypotheses")
            if result.mix_pp:
                hypotheses.write("A routing change could shift the share of attempts each bank receives.")
            if result.performance_pp:
                hypotheses.write("A change in bank availability could affect its success rate.")
            hypotheses.caption("Testing these explanations requires routing logs and failure codes.")
            actions.markdown("#### Recommended actions")
            if result.mix_pp:
                actions.write("Compare routing change logs around " + result.parameters["current_start"]
                         + " with the observed change in attempt shares.")
            if result.performance_pp:
                previous = {row.bank_id: row.rate for row in result.rows if row.period == "baseline"}
                changed = [row.bank_name for row in result.rows
                           if row.period == "current" and row.rate != previous[row.bank_id]]
                actions.write("Inspect daily failure codes for " + ", ".join(changed)
                         + " across both windows.")


def show_trend(result: DailyTrend):
    st.subheader("Daily payment success")
    table = pd.DataFrame([{"Date (IST)": row.day.isoformat(), "Successful attempts": row.successes,
                           "Eligible attempts": row.attempts, "Rate": float(row.rate) if row.rate is not None else None}
                          for row in result.rows])
    # Keep consecutive observations together without drawing across missing days.
    chart_data = table.assign(segment=table["Rate"].isna().cumsum())
    observed = table["Rate"].dropna() * 100
    lower, upper, step = 0, 100, 20
    if not observed.empty:
        low, high = observed.min(), observed.max()
        span = min(100, max(5, (high - low) * 1.2))
        # Shift the padded window inward at 0% and 100% to keep its full span.
        start = max(0, min(100 - span, (low + high - span) / 2))
        step = next(size for size in (1, 2, 5, 10, 20) if size * 6 >= span)
        lower = max(0, floor(start / step) * step)
        upper = min(100, ceil((start + span) / step) * step)
    ticks = [value / 100 for value in range(lower, upper + 1, step)]
    chart = alt.Chart(chart_data).mark_line(point=True, color="#087849").encode(
        x=alt.X("Date (IST):O", title="Date (IST)", scale=alt.Scale(domain=table["Date (IST)"].tolist()),
                axis=alt.Axis(labelExpr="slice(datum.label, 5)", labelOverlap=True)),
        y=alt.Y("Rate:Q", title="Payment success rate", axis=alt.Axis(format="%", values=ticks),
                scale=alt.Scale(domain=[lower / 100, upper / 100], nice=False, zero=False)),
        detail="segment:N",
        tooltip=["Date (IST):O", alt.Tooltip("Rate:Q", format=".1%"),
                 "Successful attempts:Q", "Eligible attempts:Q"])
    st.altair_chart(chart.properties(height=300), use_container_width=True)
    st.caption("Y-axis scaled to observed rates")
    if table["Rate"].isna().any():
        st.info("Dates with zero eligible attempts have no success rate and appear as gaps.")
    table["Rate"] = [percentage(row.rate) for row in result.rows]
    st.dataframe(table, hide_index=True, use_container_width=True)


def show_evidence(result: Comparison | DailyTrend, fixture: str):
    with st.expander("Query and dataset evidence"):
        st.write("Quality checks passed for this analysis.")
        st.write(f"Synthetic datasets: {fixture}/transactions.csv and {fixture}/banks.csv")
        st.write("Success rate divides successful attempts by eligible terminal attempts with a valid bank.")
        for period in (("window",) if isinstance(result, DailyTrend) else ("baseline", "current")):
            start = result.parameters[f"{period}_start"]
            end = result.parameters[f"{period}_end"]
            label = "Trend" if period == "window" else period.title()
            st.write(f"{label} window (IST): {start} through {end} (exclusive end)")
        st.markdown("**Executed SQL**")
        st.code(result.sql, language="sql")
        st.markdown("**Bound parameters**")
        st.json(result.parameters)


def restore_question(example):
    st.session_state.question = example


def main():
    st.set_page_config(page_title="Bizilytix.ai", layout="wide")
    st.html("""<style>
        .stMain { background: #F3F9F5; }
        .stMainBlockContainer { --gutter: clamp(1rem, 3vw, 3rem);
            max-width: none; padding: 3.75rem var(--gutter) 4rem; }
        .biz-banner { background: #103F30; margin-inline: calc(-1 * var(--gutter));
            padding: 1rem var(--gutter); }
        .biz-banner h1 { color: white; font-size: 1.7rem; line-height: 1.25; margin: 0 0 .2rem;
            padding: 0; letter-spacing: -.04em; }
        .biz-banner p { color: #C7EFD5; font-size: .88rem; margin: 0; }
        .st-key-question_panel, [data-testid="stMetric"], [data-testid="stExpander"] details {
            background: white; border: 1px solid #B9D3C3; border-radius: .65rem; }
        [data-testid="stMetric"] { font-variant-numeric: tabular-nums;
            color: #103F30; padding: .8rem 1rem; }
        .stMain h3, .stMain h4 { color: #14563B; }
        [data-testid="stExpander"] details summary { color: #103F30; background: #EDF8F1; }
        [data-testid="stExpander"] details summary:focus { color: #075B38; box-shadow: none; }
        .st-key-question_panel button[kind="primary"] { background: #087849; color: white; border-color: #087849; }
        .st-key-question_panel button[kind="primary"]:hover { background: #065F3A; }
        .st-key-question_panel button[kind="secondary"] { color: #115539; border-color: #80AB91; background: white; }
        .st-key-question_panel button[kind="secondary"]:hover { background: #E5F3EA; }
        .st-key-question_panel button:focus-visible,
        [data-testid="stExpander"] details summary:focus-visible,
        [data-testid="stSidebar"] label:has(input:focus-visible) {
            outline: 3px solid #087849; outline-offset: 2px; }
        [data-testid="stSidebar"] h2 { color: #103F30; padding-bottom: .5rem; }
        [data-testid="stSidebar"] [role="radiogroup"] { gap: .25rem; }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            padding: .35rem .65rem; margin: 0; border-radius: .4rem; }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: #D2EADB; color: #103F30; }
        [data-testid="stMetricValue"] { letter-spacing: -.04em; }
        </style>""")
    with st.sidebar:
        st.header("Analysis settings")
        mode = st.radio("Planner", ["Offline preset", "Live Gemini"],
                        help="Offline uses the sample questions. Gemini plans custom comparisons and daily trends.")
        st.divider()
        fixture = st.radio("Synthetic fixture", ["Clean", "Broken"],
                           help="Broken contains one missing payment status.").lower()
    st.html('<header class="biz-banner"><h1>Bizilytix.ai</h1><p>AI Business Analyst</p></header>')
    with st.container(border=True, key="question_panel"):
        question = st.text_area("Analysis question", value=QUESTION, key="question", height=85)
        with st.container(horizontal=True):
            submitted = st.button("Analyze", type="primary", disabled=not question.strip())
            st.button("Bank comparison example", on_click=restore_question, args=(QUESTION,))
            st.button("Daily trend example", on_click=restore_question, args=(TREND_QUESTION,))
    if submitted:
        try:
            with st.spinner("Running analysis…"):
                result = ask(question, "offline" if mode == "Offline preset" else "live", FIXTURES / fixture)
        except QualityError as exc:
            st.error(str(exc))
            st.caption("To recover, select Clean in the sidebar and click Analyze again.")
        except PlannerError as exc:
            st.error(f"{exc} Retry or select Offline preset and use the sample question.")
        else:
            if isinstance(result, Clarification):
                st.info(result.question)
            else:
                if isinstance(result, DailyTrend):
                    show_trend(result)
                else:
                    show_comparison(result, fixture)
                show_evidence(result, fixture)


main()

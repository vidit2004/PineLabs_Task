"""Streamlit entry point for the bank comparison."""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analyst.analysis import Comparison
from analyst.data import QualityError
from analyst.plan import Clarification
from analyst.planner import QUESTION, PlannerError, ask

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
                    axis=alt.Axis(format="%", tickCount=6)),
            tooltip=["Bank", "Period", alt.Tooltip("Rate:Q", format=".1%"), "Attempts", "Successes"])
        bars = base.mark_bar(size=23, cornerRadiusEnd=3).encode(
            color=alt.Color("Period:N", title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(domain=["Baseline", "Current"], range=["#516981", "#09695F"])))
        labels = base.mark_text(fontWeight="bold", dx=alt.ExprRef(expr="datum.Rate >= 0.15 ? -27 : 27")).encode(
            text=alt.Text("Rate:Q", format=".1%"),
            color=alt.condition("datum.Rate >= 0.15", alt.value("white"), alt.value("#172D36")))
        chart = (bars + labels).properties(height=80 * table["Bank"].nunique()).configure_view(stroke=None)
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

    with st.expander("Query and dataset evidence"):
        st.write("Quality checks passed for this comparison.")
        st.write(f"Synthetic datasets: {fixture}/transactions.csv and {fixture}/banks.csv")
        st.write("Success rate divides successful attempts by eligible terminal attempts with a valid bank.")
        for period in ("baseline", "current"):
            start = result.parameters[f"{period}_start"]
            end = result.parameters[f"{period}_end"]
            st.write(f"{period.title()} window (IST): {start} through {end} (exclusive end)")
        st.markdown("**Executed SQL**")
        st.code(result.sql, language="sql")
        st.markdown("**Bound parameters**")
        st.json(result.parameters)


def restore_question():
    st.session_state.question = QUESTION


def main():
    st.set_page_config(page_title="Payment success by bank", layout="wide")
    st.html("""<style>
        .stMainBlockContainer { max-width: 70rem; padding-top: 3rem; }
        [data-testid="stMetric"] { font-variant-numeric: tabular-nums; }
        [data-testid="stMetricValue"] { letter-spacing: -.04em; }
        @media (max-width: 800px) { .stMainBlockContainer { padding-top: 2.5rem; } }
        </style>""")
    with st.sidebar:
        st.header("Analysis settings")
        mode = st.radio("Planner", ["Offline preset", "Live Gemini"],
                        help="Offline uses the sample question. Gemini plans custom comparisons.")
        st.divider()
        fixture = st.radio("Synthetic fixture", ["Clean", "Broken"],
                           help="Broken contains one missing payment status.").lower()
    st.title("Payment success by bank")
    with st.container(border=True):
        question = st.text_area("Comparison question", value=QUESTION, key="question", height=85)
        with st.container(horizontal=True):
            submitted = st.button("Analyze", type="primary", disabled=not question.strip())
            st.button("Use sample question", on_click=restore_question)
    if submitted:
        try:
            with st.spinner("Running comparison…"):
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
                show_comparison(result, fixture)


main()

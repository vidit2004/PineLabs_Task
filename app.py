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
    st.subheader("Observed success rates")
    baseline, current = result.rates["baseline"], result.rates["current"]
    change = None if baseline is None or current is None else 100 * (current - baseline)
    before, after, difference = st.columns(3)
    before.metric("Baseline", percentage(baseline))
    after.metric("Current", percentage(current))
    difference.metric("Observed change", points(change))

    if result.rows:
        st.subheader("Success by bank")
        totals = {period: sum(row.attempts for row in result.rows if row.period == period)
                  for period in result.rates}
        table = pd.DataFrame([{"Bank": row.bank_name, "Period": row.period.title(),
                               "Successes": row.successes, "Attempts": row.attempts,
                               "Rate": float(row.rate), "Attempt share": row.attempts / totals[row.period]}
                              for row in result.rows])
        chart = alt.Chart(table).mark_bar().encode(
            x=alt.X("Bank:N", title=None),
            xOffset=alt.XOffset("Period:N", sort=["Baseline", "Current"]),
            y=alt.Y("Rate:Q", title="Success rate", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%")),
            color=alt.Color("Period:N", scale=alt.Scale(domain=["Baseline", "Current"],
                                                        range=["#586c88", "#007c72"])),
            tooltip=["Bank", "Period", alt.Tooltip("Rate:Q", format=".1%"), "Attempts", "Successes"])
        st.altair_chart(chart, use_container_width=True)
        for column in ("Rate", "Attempt share"):
            table[column] = table[column].map(percentage)
        st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("Descriptive attribution")
    if result.limitation:
        st.info(result.limitation)
    else:
        mix, within = st.columns(2)
        mix.metric("Bank mix effect", points(result.mix_pp))
        within.metric("Within-bank effect", points(result.performance_pp))
        st.caption("Mix uses baseline bank rates. Within-bank performance uses current attempt shares.")
        if result.mix_pp or result.performance_pp:
            st.markdown("**Possible causes**")
            if result.mix_pp:
                st.write("A routing change could shift the share of attempts each bank receives.")
            if result.performance_pp:
                st.write("A change in bank availability could affect its success rate.")
            st.caption("The synthetic datasets contain neither routing history nor failure codes.")
            st.markdown("**Recommended next steps**")
            if result.mix_pp:
                st.write("Compare routing change logs around " + result.parameters["current_start"]
                         + " with the observed change in attempt shares.")
            if result.performance_pp:
                previous = {row.bank_id: row.rate for row in result.rows if row.period == "baseline"}
                changed = [row.bank_name for row in result.rows
                           if row.period == "current" and row.rate != previous[row.bank_id]]
                st.write("Inspect daily failure codes for " + ", ".join(changed)
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
    st.set_page_config(page_title="Payment success by bank", layout="centered")
    st.title("Payment success by bank")
    modes, fixtures = st.columns(2)
    mode = modes.radio("Planner", ["Offline preset", "Live Gemini"], horizontal=True)
    fixture = fixtures.radio("Synthetic fixture", ["Clean", "Broken"], horizontal=True).lower()
    question = st.text_area("Comparison question", value=QUESTION, key="question")
    run, reset = st.columns([1, 2])
    submitted = run.button("Run comparison", type="primary")
    reset.button("Use sample question", on_click=restore_question)
    if submitted:
        try:
            with st.spinner("Running comparison…"):
                result = ask(question, "offline" if mode == "Offline preset" else "live", FIXTURES / fixture)
        except QualityError as exc:
            st.error(str(exc))
        except PlannerError as exc:
            st.error(f"{exc} Retry or select Offline preset and use the sample question.")
        else:
            if isinstance(result, Clarification):
                st.info(result.question)
            else:
                show_comparison(result, fixture)


main()

import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, add_x_labels

st.title("Ball striking")
st.caption("Fairways and greens over time. Grint-era scrambling is approximated from scores and putts.")

round_ids, _ = sidebar_filters()
summary = (
    stats.round_summary()
    .sort("date")
    .filter(pl.col("score").is_not_null() & pl.col("round_id").is_in(round_ids or []))
)
summary = add_x_labels(summary)

fir_df = summary.filter(pl.col("fir_pct").is_not_null())
if fir_df.height:
    st.subheader("Fairways hit %")
    st.altair_chart(
        alt.Chart(fir_df).mark_line(point=True).encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("fir_pct:Q", title="FIR %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date", "course_name", "fir_pct"],
        )
    )
else:
    st.caption("No fairway data yet.")

gir_df = summary.filter(pl.col("gir_pct").is_not_null())
if gir_df.height:
    st.subheader("Greens in regulation %")
    st.altair_chart(
        alt.Chart(gir_df).mark_line(point=True).encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("gir_pct:Q", title="GIR %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date", "course_name", "gir_pct"],
        )
    )
else:
    st.caption("No green-in-regulation data yet.")

scr_df = summary.filter(pl.col("scramble_pct").is_not_null())
if scr_df.height:
    st.subheader("Scrambling % (missed-green saves)")
    st.altair_chart(
        alt.Chart(scr_df).mark_line(point=True).encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("scramble_pct:Q", title="Scrambling %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date", "course_name", "scramble_pct"],
        )
    )
else:
    st.caption("Scrambling needs shot-level data (Garmin rounds).")

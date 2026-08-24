import altair as alt
import polars as pl
import streamlit as st

import stats

st.title("Putting")

dist = stats.putt_distribution()
c1, c2 = st.columns(2)

with c1:
    st.subheader("Putt distribution")
    st.altair_chart(
        alt.Chart(dist).mark_arc(innerRadius=60).encode(
            theta=alt.Theta("n:Q"),
            color=alt.Color("label:N", sort=None, title=None),
            tooltip=["label", "n", "pct"],
        )
    )
    for row in dist.iter_rows(named=True):
        st.caption(f"{row['label']}: {row['pct']}% of holes")

with c2:
    st.subheader("Average putts by GIR")
    by_gir = stats.putts_by_gir()
    if by_gir.height:
        by_gir = by_gir.with_columns(
            pl.when(pl.col("gir")).then(pl.lit("Green in regulation")).otherwise(pl.lit("Missed green")).alias("label")
        )
        baseline = by_gir.filter(pl.col("gir"))["avg_putts"]
        st.altair_chart(
            alt.Chart(by_gir).mark_bar().encode(
                x=alt.X("label:N", sort=["Green in regulation", "Missed green"], title=None),
                y=alt.Y("avg_putts:Q", title="Avg putts", scale=alt.Scale(zero=False)),
                color=alt.value("#264653"),
                tooltip=["label", "avg_putts", "holes"],
            )
        )
    else:
        st.caption("Needs rounds with both green-hit info and putt counts.")

st.subheader("Putts per round (last 20)")
summary = (
    stats.round_summary()
    .filter(pl.col("putts_total").is_not_null())
    .sort("date")
    .tail(20)
)
st.altair_chart(
    alt.Chart(summary).mark_line(point=True).encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("putts_total:Q", title="Putts"),
        tooltip=["date", "course_name", "putts_total", "score"],
    )
)

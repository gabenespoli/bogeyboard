import altair as alt
import polars as pl
import streamlit as st

import stats

st.title("Overview")
st.caption("All rounds, both sources — best-8-of-last-20 differentials highlighted")

summary = stats.round_summary().sort("date")
idx = stats.handicap_index(summary)
eligible = summary.filter(pl.col("differential").is_not_null())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Handicap index", idx if idx is not None else "—")
c2.metric(
    "Avg score (last 20)",
    round(summary.sort('date')['score'].tail(20).mean(), 1),
)
with c3:
    fir = eligible.filter(pl.col("fir_pct").is_not_null())
    val = round(fir["fir_pct"].tail(20).mean(), 1) if fir.height else None
    st.metric("Fairways hit %", f"{val}%" if val is not None else "—")
with c4:
    gir = eligible.filter(pl.col("gir_pct").is_not_null())
    val = round(gir["gir_pct"].tail(20).mean(), 1) if gir.height else None
    st.metric("Greens in regulation %", f"{val}%" if val is not None else "—")

chart_df = summary.filter(pl.col("score").is_not_null()).select(
    "date", "course_name", "score", "differential", "counts"
)
chart = (
    alt.Chart(chart_df)
    .mark_bar()
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("score:Q", title="Score"),
        color=alt.condition(
            alt.datum.counts == True,
            alt.value("#7aa832"),
            alt.value("#264653"),
        ),
        tooltip=["date", "course_name", "score", "differential"],
    )
)
st.altair_chart(chart)

recent = eligible.sort("date", descending=True).head(20).sort("differential")
st.subheader("Last 20 scorable rounds")
st.dataframe(
    recent.select(
        "date",
        "course_name",
        "score",
        "rating",
        "slope",
        "differential",
        "counts",
    ),
    hide_index=True,
    width="stretch",
)

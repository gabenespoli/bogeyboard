import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import add_x_labels

st.title("Handicap")
st.caption("WHS — last 20 rounds, best k highlighted per table, truncation to 1 decimal")

stats.require_data()

full = stats.round_summary()

# Always last 20 scorable rounds, mirroring WHS calculation
last20 = full.filter(pl.col("differential").is_not_null()).sort("date", descending=True).head(20)
if last20.height == 0:
    st.info("Not enough scorable rounds yet.")
    st.stop()

last20_sorted = last20.sort("date")
hist = stats.handicap_history().filter(pl.col("round_id").is_in(last20["round_id"])).sort("date")

# Handicap Index progression chart
if hist.height:
    hist_labeled = add_x_labels(hist)
    hi_chart = (
        alt.Chart(hist_labeled)
        .mark_line(point=True, color="#264653")
        .encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("hi_after:Q", title="Handicap Index", scale=alt.Scale(zero=False)),
            tooltip=["date", "course_name", "holes_played", "hi_before", "hi_after", "differential"],
        )
        .properties(height=250)
    )
    st.altair_chart(hi_chart, width="stretch")

# Differential bar chart — score with best k highlighted
chart_df = add_x_labels(
    last20_sorted.select("date", "course_name", "score", "differential", "counts", "holes_played")
)
chart = (
    alt.Chart(chart_df)
    .mark_bar()
    .encode(
        x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("score:Q", title="Score"),
        color=alt.condition(
            alt.datum.counts == True,
            alt.value("#7aa832"),
            alt.value("#264653"),
        ),
        tooltip=["date", "course_name", "holes_played", "score", "differential"],
    )
)
st.altair_chart(chart, width="stretch")

# Scorable rounds table — sorted by differential
recent = (
    last20.filter(pl.col("differential").is_not_null()).sort("differential")
)
st.subheader(f"Scorable rounds — last 20 ({recent.height})")
st.dataframe(
    recent.select(
        "date",
        "course_name",
        "holes_played",
        "score",
        "rating",
        "slope",
        "differential",
        "differential_9_raw",
        "expected_9",
        "hi_before",
        "hi_after",
        "counts",
    ),
    hide_index=True,
    width="stretch",
)

hi = stats.handicap_index(full)
st.caption(f"Current Handicap Index (last 20, best k): {hi:.1f}" if hi is not None else "Current Handicap Index: —")

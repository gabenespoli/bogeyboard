import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, add_x_labels

st.title("Scrambling")
st.caption("Grint-era scrambling is approximated from scores and putts. Scrambling = saves when missing the green.")

stats.require_data()

round_ids, _ = sidebar_filters()
summary = add_x_labels(
    stats.round_summary()
    .sort("date")
    .filter(pl.col("score").is_not_null() & pl.col("round_id").is_in(round_ids or []))
)
x_order = summary["x_label"].to_list()
x_enc = dict(
    x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45), sort=x_order),
)

LINE_COLOR = "#1c1c1c"

scr_df = summary.filter(pl.col("scramble_pct").is_not_null())
if scr_df.height:
    st.subheader("Scrambling % (missed-green saves)")
    st.altair_chart(
        alt.Chart(scr_df).mark_line(point=True, color=LINE_COLOR).encode(
            **x_enc,
            y=alt.Y("scramble_pct:Q", title="Scrambling %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date", "course_name", "scramble_pct"],
        ),
        width="stretch",
    )
else:
    st.caption("No scrambling data in this range.")

import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, add_x_labels

st.title("Overview")
st.caption("Best-8-of-last-20 differentials highlighted; handicap index always uses full history")

stats.require_data()

full = stats.round_summary()
round_ids, summary = sidebar_filters(full)
summary = summary.sort("date")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Handicap index", stats.handicap_index(full) or "—")
c2.metric(
    "Avg score (last 20)",
    round(summary.sort("date")["score"].tail(20).mean(), 1) if summary.height else "—",
)

eligible = summary.filter(pl.col("fir_pct").is_not_null()).sort("date")
with c3:
    val = round(eligible["fir_pct"].tail(20).mean(), 1) if eligible.height else None
    c3.metric("Fairways hit %", f"{val}%" if val is not None else "—")
eligible_gir = summary.filter(pl.col("gir_pct").is_not_null()).sort("date")
with c4:
    val = round(eligible_gir["gir_pct"].tail(20).mean(), 1) if eligible_gir.height else None
    c4.metric("Greens in regulation %", f"{val}%" if val is not None else "—")

chart_df = add_x_labels(
    summary.select("date", "course_name", "score", "differential", "counts")
)
if chart_df.height:
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
            tooltip=["date", "course_name", "score", "differential"],
        )
    )
    st.altair_chart(chart)
else:
    st.info("No rounds match the current filters.")

recent = (
    full.filter(pl.col("round_id").is_in(round_ids))
    .filter(pl.col("differential").is_not_null())
    .sort("date", descending=True)
)
st.subheader(f"Scorable rounds ({recent.height})")
if recent.height:
    recent = recent.sort("differential")
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

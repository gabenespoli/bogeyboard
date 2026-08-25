import altair as alt
import plotly.express as px
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, filter_holes, add_x_labels

st.title("Putting")

stats.require_data()

round_ids, _ = sidebar_filters()

dist = stats.putt_distribution(filter_holes(stats.load_holes(), round_ids))
c1, c2 = st.columns(2)

with c1:
    st.subheader("Putt distribution")
    if dist.height:
        fig = px.pie(
            dist,
            names="label",
            values="n",
            hole=0.45,
            category_orders={"label": dist["label"].to_list()},
        )
        fig.update_traces(textinfo="percent", textposition="inside", insidetextorientation="horizontal")
        fig.update_layout(
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            height=320,
            legend_title=None,
        )
        st.plotly_chart(fig, key="putt_donut")
    else:
        st.caption("No holes with putt data in the current filter.")

with c2:
    st.subheader("Average putts by GIR")
    by_gir = stats.putts_by_gir(filter_holes(stats.enriched_holes(), round_ids))
    if by_gir.height:
        by_gir = by_gir.with_columns(
            pl.when(pl.col("gir")).then(pl.lit("Green in regulation")).otherwise(pl.lit("Missed green")).alias("label")
        )
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

st.subheader("Putts per round")
summary = (
    stats.round_summary()
    .filter(pl.col("putts_total").is_not_null() & pl.col("round_id").is_in(round_ids or []))
    .sort("date")
    .with_columns(
        pl.when(pl.col("holes_played") == 18)
        .then(pl.lit("18 holes"))
        .otherwise(pl.lit("9 holes"))
        .alias("round_len"),
        (pl.col("putts_total") * 2).alias("putts_projected"),
    )
)
if not summary.height:
    st.info("No rounds match the current filters.")
else:
    summary = add_x_labels(summary)
    nine = summary.filter(pl.col("round_len") == "9 holes")

    solid = (
        alt.Chart(summary)
        .mark_bar()
        .encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45), sort=None),
            y=alt.Y("putts_total:Q", title="Putts"),
            color=alt.Color(
                "round_len:N",
                scale=alt.Scale(domain=["18 holes", "9 holes"], range=["#264653", "#F38336"]),
                title=None,
            ),
            tooltip=["date", "course_name", "putts_total", "holes_played"],
        )
    )
    projection = (
        alt.Chart(nine)
        .mark_bar(opacity=0.3)
        .encode(
            x=alt.X("x_label:N", title="Date", axis=alt.Axis(labelAngle=-45), sort=None),
            y=alt.Y("putts_total:Q", title="Putts"),
            y2=alt.Y2("putts_projected:Q"),
            color=alt.value("#F38336"),
        )
    )
    st.altair_chart(solid + projection)
    st.caption("Translucent segments on 9-hole bars show the total doubled (×2) for comparison with 18-hole rounds.")

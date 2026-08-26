import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, filter_holes

st.title("Scoring")

stats.require_data()

round_ids, _ = sidebar_filters()
holes = filter_holes(stats.load_holes(), round_ids).filter(pl.col("score").is_not_null())

by_number = (
    holes.group_by("hole_number")
    .agg(
        pl.col("score").mean().round(2).alias("avg_score"),
        (pl.col("score") - pl.col("par")).mean().round(2).alias("avg_vs_par"),
    )
    .sort("hole_number")
)
c1, c2 = st.columns(2)
with c1:
    st.subheader("Average score by hole")
    st.altair_chart(
        alt.Chart(by_number).mark_bar().encode(
            x=alt.X("hole_number:O", title="Hole"),
            y=alt.Y("avg_score:Q", title="Avg strokes"),
            color=alt.condition(alt.datum.avg_vs_par > 0, alt.value("#b56576"), alt.value("#264653")),
            tooltip=["hole_number", "avg_score", "avg_vs_par"],
        )
    )

with_par = holes.filter(pl.col("par").is_not_null())
by_par = (
    with_par.group_by("par")
    .agg(
        pl.col("score").mean().round(2).alias("avg_score"),
        (pl.col("score") - pl.col("par")).mean().round(2).alias("avg_vs_par"),
        pl.len().alias("holes"),
    )
    .sort("par")
)
with c2:
    st.subheader("Average vs par by hole par")
    st.altair_chart(
        alt.Chart(by_par).mark_bar().encode(
            x=alt.X("par:O", title="Par"),
            y=alt.Y("avg_vs_par:Q", title="Avg strokes vs par"),
            tooltip=["par", "avg_score", "avg_vs_par", "holes"],
        )
    )

with_yards = holes.filter(pl.col("yardage").is_not_null() & (pl.col("yardage") > 0))
if with_yards.height:
    binned = with_yards.with_columns(
        (pl.col("yardage").floordiv(25) * 25).alias("bucket")
    )
    by_yards = (
        binned.group_by("bucket")
        .agg(
            pl.col("score").mean().round(2).alias("avg_score"),
            (pl.col("score") - pl.col("par")).mean().round(2).alias("avg_vs_par"),
            pl.len().alias("holes"),
        )
        .sort("bucket")
    )
    st.subheader("Average vs par by hole yardage")
    st.altair_chart(
        alt.Chart(by_yards).mark_bar().encode(
            x=alt.X("bucket:O", title="Yardage bucket"),
            y=alt.Y("avg_vs_par:Q", title="Avg strokes vs par"),
            tooltip=["bucket", "avg_score", "avg_vs_par", "holes"],
        )
    )
else:
    st.caption(
        "Yardage chart needs hole lengths. Grint rounds get yardage from the API; "
        "Garmin rounds infer it from shot GPS. Run a sync to populate."
    )

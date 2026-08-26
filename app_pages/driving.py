import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, add_x_labels

st.title("Driving")
st.caption("Tee-shot misses per round; lines show fairway % on the right axis.")

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

DRIVING_COLORS = {
    "hit": "#7aa832",
    "miss_left": "#b00004",
    "miss_right": "#f38336",
    "miss_other": "#9e9e9e",
}
LINE_COLOR = "#1c1c1c"
OUTCOME_ORDER = ["hit", "miss_right", "miss_other", "miss_left"]


def stacked_chart(
    outcomes: pl.DataFrame,
    order: list[str],
    colors: dict[str, str],
) -> alt.Chart:
    labeled = outcomes.join(summary.select("round_id", "x_label"), on="round_id", how="inner")
    labeled = labeled.with_columns(
        pl.col("n").sum().over("round_id").alias("_total")
    ).with_columns(
        (pl.col("n") / pl.col("_total") * 100).alias("share")
    ).with_columns(
        pl.col("outcome").replace_strict({name: i for i, name in enumerate(order)}, return_dtype=pl.Int64).alias("_rank")
    )
    categories = [c for c in order if c in labeled["outcome"].unique().to_list()]
    legend_order = list(reversed(categories))
    return (
        alt.Chart(labeled)
        .mark_bar()
        .encode(
            **x_enc,
            y=alt.Y(
                "share:Q",
                title="Share of shots",
                axis=alt.Axis(format=".0%"),
                stack="zero",
            ),
            order=alt.Order("_rank:Q"),
            color=alt.Color(
                "outcome:N",
                title=None,
                scale=alt.Scale(domain=legend_order, range=[colors[c] for c in legend_order]),
            ),
            tooltip=["outcome:N", "n:Q", alt.Tooltip("share:Q", format=".1f")],
        )
    )


outcomes = stats.tee_shot_outcomes(round_ids or None)
if outcomes.height:
    st.altair_chart(stacked_chart(outcomes, OUTCOME_ORDER, DRIVING_COLORS), width="stretch")
else:
    st.caption("No directional tee-shot data in this range.")
fir_only = summary.filter(pl.col("fir_pct").is_not_null())
if fir_only.height and not outcomes.height:
    st.altair_chart(
        alt.Chart(fir_only).mark_line(point=True, color=LINE_COLOR).encode(
            **x_enc,
            y=alt.Y("fir_pct:Q", title="FIR %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date", "course_name", "fir_pct"],
        ),
        width="stretch",
    )

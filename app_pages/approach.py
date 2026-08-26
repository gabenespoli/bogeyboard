import altair as alt
import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters, add_x_labels

st.title("Approach")
st.caption("Greens per round; lines show percentage. Hit = approach finished on the green (or holed out). Reg = green reached in par − 2 strokes.")

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

APPROACH_COLORS = {
    "hit_reg": "#5c8a1e",
    "hit_noreg": "#a7cf3f",
    "miss_left": "#b00004",
    "miss_right": "#f38336",
    "miss_other": "#9e9e9e",
}
APPROACH_ORDER = ["hit_reg", "hit_noreg", "miss_right", "miss_other", "miss_left"]


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


approach_outcomes = stats.approach_shot_outcomes(round_ids or None)
if approach_outcomes.height:
    st.altair_chart(stacked_chart(approach_outcomes, APPROACH_ORDER, APPROACH_COLORS), width="stretch")
    st.caption("Hit = approach finished on the green (or holed out). Reg = green reached in par − 2 strokes.")
else:
    st.caption("No approach-shot data in this range.")

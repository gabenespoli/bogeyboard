import altair as alt
import polars as pl
import streamlit as st

import stats
import settings as user_settings
from filters import add_x_labels, club_filter_sidebar, sidebar_filters

st.title("Driving")
st.caption("Tee-shot misses per round; lines show fairway % on the right axis.")

stats.require_data()

round_ids, _ = sidebar_filters()
effective_clubs = club_filter_sidebar(round_ids)
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

st.divider()
st.subheader("Driving accuracy (FIR%) by hole yardage")
fir_yard = stats.driving_fir_by_yardage(round_ids or None)
if fir_yard.height:
    st.altair_chart(
        alt.Chart(fir_yard).mark_bar(color="#7aa832").encode(
            x=alt.X("bucket:O", title="Yardage bucket (25y)"),
            y=alt.Y("fir_pct:Q", title="FIR %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["bucket:O", "fir_pct:Q", "holes:Q"],
        ),
        width="stretch",
    )
    st.caption("Par 4/5 only — bucket is hole yardage (tee to green).")
else:
    st.caption("Not enough driving data with yardage in this range.")

st.subheader("Driving misses by yardage")
outcomes_yard = stats.driving_outcomes_by_yardage(round_ids or None)
if outcomes_yard.height:
    # compute share per bucket like stacked_chart but x=bucket
    total = outcomes_yard.group_by("bucket").agg(pl.col("n").sum().alias("_total"))
    labeled = outcomes_yard.join(total, on="bucket").with_columns((pl.col("n") / pl.col("_total") * 100).alias("share")).with_columns(
        pl.col("outcome").replace_strict({name: i for i, name in enumerate(OUTCOME_ORDER)}, return_dtype=pl.Int64).alias("_rank")
    )
    cats = [c for c in OUTCOME_ORDER if c in labeled["outcome"].unique().to_list()]
    legend_order = list(reversed(cats))
    st.altair_chart(
        alt.Chart(labeled)
        .mark_bar()
        .encode(
            x=alt.X("bucket:O", title="Yardage bucket (25y)", sort=alt.SortField(field="bucket", order="ascending")),
            y=alt.Y("share:Q", title="Share of tee shots", stack="zero"),
            order=alt.Order("_rank:Q"),
            color=alt.Color("outcome:N", title=None, scale=alt.Scale(domain=legend_order, range=[DRIVING_COLORS[c] for c in legend_order])),
            tooltip=["bucket:O", "outcome:N", "n:Q", alt.Tooltip("share:Q", format=".1f")],
        ),
        width="stretch",
    )
else:
    st.caption("Not enough directional tee-shot data with yardage.")

st.divider()
st.subheader("Driving by club")
club_outcomes = stats.driving_by_club(round_ids or None, club_names=effective_clubs)
if club_outcomes.height:
    total = club_outcomes.group_by("club").agg(pl.col("n").sum().alias("_total"))
    labeled = club_outcomes.join(total, on="club").with_columns((pl.col("n") / pl.col("_total") * 100).alias("share")).with_columns(
        pl.col("outcome").replace_strict({name: i for i, name in enumerate(OUTCOME_ORDER)}, return_dtype=pl.Int64).alias("_rank")
    )
    cats = [c for c in OUTCOME_ORDER if c in labeled["outcome"].unique().to_list()]
    legend_order = list(reversed(cats))
    # order clubs by mean distance after std filters (shortest left, longest right)
    saved = user_settings.load_settings()
    eff_low_dr = saved.get("trim_std", "Off") if saved.get("apply_std_filter", True) else "Off"
    eff_high_dr = saved.get("trim_std_high", "Off") if saved.get("apply_std_filter", True) else "Off"
    try:
        club_dist_dr = stats.club_distances(round_ids, club_names=effective_clubs, trim_std=eff_low_dr, trim_std_high=eff_high_dr)
        club_order = club_dist_dr.sort("avg_yds")["club"].to_list()
        club_order = [c for c in club_order if c in labeled["club"].unique().to_list()]
        if not club_order:
            club_order = [c for c in stats.available_clubs(round_ids) if c in labeled["club"].unique().to_list()]
    except Exception:
        dropdown_order = stats.available_clubs(round_ids)
        club_order = [c for c in dropdown_order if c in labeled["club"].unique().to_list()]
    st.altair_chart(
        alt.Chart(labeled)
        .mark_bar()
        .encode(
            x=alt.X("club:N", title="Club", sort=club_order),
            y=alt.Y("share:Q", title="Share of tee shots", stack="zero"),
            order=alt.Order("_rank:Q"),
            color=alt.Color("outcome:N", title=None, scale=alt.Scale(domain=legend_order, range=[DRIVING_COLORS[c] for c in legend_order])),
            tooltip=["club:N", "outcome:N", "n:Q", alt.Tooltip("share:Q", format=".1f")],
        ),
        width="stretch",
    )
    st.caption("Garmin CT10 club data only — stacked share per club (par 4/5 tee shots).")
else:
    st.caption("No club-tagged driving data in this range.")

st.subheader("Driving by shot distance")
shot_dist = stats.driving_by_shot_distance(round_ids or None)
if shot_dist.height:
    total = shot_dist.group_by("bucket").agg(pl.col("n").sum().alias("_total"))
    labeled = shot_dist.join(total, on="bucket").with_columns((pl.col("n") / pl.col("_total") * 100).alias("share")).with_columns(
        pl.col("outcome").replace_strict({name: i for i, name in enumerate(OUTCOME_ORDER)}, return_dtype=pl.Int64).alias("_rank")
    )
    cats = [c for c in OUTCOME_ORDER if c in labeled["outcome"].unique().to_list()]
    legend_order = list(reversed(cats))
    st.altair_chart(
        alt.Chart(labeled)
        .mark_bar()
        .encode(
            x=alt.X("bucket:O", title="Shot distance bucket (25y)", sort=alt.SortField(field="bucket", order="ascending")),
            y=alt.Y("share:Q", title="Share of tee shots", stack="zero"),
            order=alt.Order("_rank:Q"),
            color=alt.Color("outcome:N", title=None, scale=alt.Scale(domain=legend_order, range=[DRIVING_COLORS[c] for c in legend_order])),
            tooltip=["bucket:O", "outcome:N", "n:Q", alt.Tooltip("share:Q", format=".1f")],
        ),
        width="stretch",
    )
    st.caption("Bucket is measured tee-shot distance (yards, Garmin), not hole length.")
else:
    st.caption("Not enough tee-shot distance data in this range.")

import altair as alt
import polars as pl
import streamlit as st

import stats
import settings as user_settings
from filters import sidebar_filters

st.title("Clubs")
st.caption("Shot data from Garmin tracking, putts excluded. All charts respect the sidebar filters.")

stats.require_data()

round_ids, _ = sidebar_filters()

available = stats.available_clubs(round_ids)
saved_clubs = [
    c for c in user_settings.load_settings().get("clubs_selected", [])
    if c in available
]
picked = st.multiselect(
    "Clubs",
    options=available,
    default=saved_clubs,
    key="club_filter",
    placeholder="All clubs",
)
user_settings.update_setting("clubs_selected", picked)

effective = picked if picked else available

c_low, c_high, c_bool = st.columns(3)
trim_opts = ["Off", 2, 1, 0.5, 0.25]
saved = user_settings.load_settings()
with c_bool:
    apply_std_filter = st.checkbox(
        "Apply std-dev filtering",
        value=saved.get("apply_std_filter", True),
        key="apply_std_filter",
    )
with c_low:
    trim_std = st.selectbox(
        "Trim below average (−σ)",
        options=trim_opts,
        index=trim_opts.index(saved.get("trim_std", "Off"))
        if saved.get("trim_std", "Off") in trim_opts
        else 0,
        key="trim_std",
        disabled=not apply_std_filter,
    )
with c_high:
    trim_std_high = st.selectbox(
        "Trim above average (+σ)",
        options=trim_opts,
        index=trim_opts.index(saved.get("trim_std_high", "Off"))
        if saved.get("trim_std_high", "Off") in trim_opts
        else 0,
        key="trim_std_high",
        disabled=not apply_std_filter,
    )
user_settings.update_setting("apply_std_filter", apply_std_filter)
user_settings.update_setting("trim_std", trim_std)
user_settings.update_setting("trim_std_high", trim_std_high)

eff_low = trim_std if apply_std_filter else "Off"
eff_high = trim_std_high if apply_std_filter else "Off"

shots = stats.shot_distances(effective, round_ids, trim_std=eff_low, trim_std_high=eff_high)

st.subheader("Distance distribution")
if shots.height == 0:
    st.caption("No measurable shots for the selected clubs in this range.")
else:
    parts = []
    if eff_low != "Off":
        parts.append(f"−{eff_low}σ below")
    if eff_high != "Off":
        parts.append(f"+{eff_high}σ above")
    if parts:
        st.caption(f"Outlier trimming active — keeping shots within {' and '.join(parts)} the club average ({shots.height} shots).")
    curves, means = stats.shot_density(
        effective, round_ids, trim_std=eff_low, trim_std_high=eff_high
    )

    areas = (
        alt.Chart(curves, height=350)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("distance:Q", title="Distance (yards)"),
            y=alt.Y("density:Q", title="Density"),
            color=alt.Color("club:N", title=None),
            tooltip=["club:N", alt.Tooltip("distance:Q", format=".0f")],
        )
    )
    rules = (
        alt.Chart(means)
        .mark_rule()
        .encode(
            x=alt.X("mean_yds:Q"),
            color=alt.Color("club:N", legend=None),
            tooltip=[
                "club:N",
                alt.Tooltip("mean_yds:Q", title="Mean distance (yds)", format=".1f"),
            ],
        )
    )
    labels = (
        alt.Chart(means)
        .mark_text(align="center", angle=90, fontSize=11, dy=8)
        .encode(
            x=alt.X("mean_yds:Q"),
            y=alt.Y("label_y:Q"),
            text=alt.Text("club:N"),
            color=alt.Color("club:N", legend=None),
        )
    )
    st.altair_chart((areas + rules + labels))

st.subheader("Average distances")

clubs = stats.club_distances(
    round_ids,
    club_names=effective,
    trim_std=eff_low,
    trim_std_high=eff_high,
)
if clubs.height == 0:
    st.caption("No club-tagged shots yet — rerun the Garmin fetch after playing with CT10 sensors paired.")
else:
    # st.altair_chart(
    #     alt.Chart(clubs).mark_bar().encode(
    #         x=alt.X("avg_yds:Q", title="Avg distance (yards)"),
    #         y=alt.Y("club:N", sort="-x", title=None),
    #         color=alt.value("#264653"),
    #         tooltip=["club", "avg_yds", "shots"],
    #     )
    # )
    st.dataframe(clubs, hide_index=True)

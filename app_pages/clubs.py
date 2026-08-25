import altair as alt
import streamlit as st

import stats
from filters import sidebar_filters

st.title("Clubs")
st.caption("Shot data from Garmin tracking, putts excluded. All charts respect the sidebar filters.")

round_ids, _ = sidebar_filters()

st.subheader("Distance distribution")

available = stats.available_clubs(round_ids)
picked = st.multiselect(
    "Clubs",
    options=available,
    key="histogram_clubs",
    placeholder="Pick one or more clubs",
)
if not picked:
    st.caption("Select at least one club to see its shot-distance distribution.")
else:
    c_low, c_high = st.columns(2)
    with c_low:
        trim_std = st.selectbox(
            "Trim below average (−σ)",
            options=["Off", 2, 1, 0.5, 0.25],
            key="trim_std",
        )
    with c_high:
        trim_std_high = st.selectbox(
            "Trim above average (+σ)",
            options=["Off", 2, 1, 0.5, 0.25],
            key="trim_std_high",
        )
    shots = stats.shot_distances(picked, round_ids, trim_std=trim_std, trim_std_high=trim_std_high)
    if shots.height == 0:
        st.caption("No measurable shots for the selected clubs in this range.")
    else:
        parts = []
        if trim_std != "Off":
            parts.append(f"−{trim_std}σ below")
        if trim_std_high != "Off":
            parts.append(f"+{trim_std_high}σ above")
        if parts:
            st.caption(f"Outlier trimming active — keeping shots within {' and '.join(parts)} the club average ({shots.height} shots).")
        curves, means = stats.shot_density(
            picked, round_ids, trim_std=trim_std, trim_std_high=trim_std_high
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

clubs = stats.club_distances(round_ids)
if clubs.height == 0:
    st.caption("No club-tagged shots yet — rerun the Garmin fetch after playing with CT10 sensors paired.")
else:
    st.altair_chart(
        alt.Chart(clubs).mark_bar().encode(
            x=alt.X("avg_yds:Q", title="Avg distance (yards)"),
            y=alt.Y("club:N", sort="-x", title=None),
            color=alt.value("#264653"),
            tooltip=["club", "avg_yds", "best_yds", "shots"],
        )
    )
    st.dataframe(clubs, hide_index=True)

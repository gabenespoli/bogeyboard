import altair as alt
import streamlit as st

import stats

st.title("Clubs")
st.caption("Average carry distances from Garmin shot tracking, putts excluded.")

clubs = stats.club_distances()
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
    st.subheader("Details")
    st.dataframe(clubs, hide_index=True)

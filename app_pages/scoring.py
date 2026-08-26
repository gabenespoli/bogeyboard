import streamlit as st

import stats

st.title("Scoring")

stats.require_data()

st.info("Scoring charts have moved to the Overview page.")
st.caption("Average score by hole, by par, and by yardage are now shown on Overview alongside the 4 summary cards.")

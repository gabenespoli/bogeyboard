import streamlit as st

import paths

paths.ensure_layout()

st.set_page_config(page_title="Bogeyboard", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("app_pages/handicap.py", title="Handicap", icon=":material/military_tech:"),
        st.Page("app_pages/scoring.py", title="Scoring", icon=":material/sports_golf:"),
        st.Page("app_pages/ball_striking.py", title="Ball striking", icon=":material/track_changes:"),
        st.Page("app_pages/putting.py", title="Putting", icon=":material/flag:"),
        st.Page("app_pages/clubs.py", title="Clubs", icon=":material/golf_course:"),
        st.Page("app_pages/data.py", title="Data", icon=":material/table_chart:"),
        st.Page("app_pages/accounts.py", title="Accounts", icon=":material/person:"),
    ]
)

page.run()

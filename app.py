import streamlit as st

import paths

paths.ensure_layout()

st.set_page_config(page_title="Bogeyboard", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("app_pages/driving.py", title="Driving", icon=":material/track_changes:"),
        st.Page("app_pages/approach.py", title="Approach", icon=":material/flag:"),
        st.Page("app_pages/scrambling.py", title="Scrambling", icon=":material/crisis_alert:"),
        st.Page("app_pages/putting.py", title="Putting", icon=":material/flag:"),
        st.Page("app_pages/clubs.py", title="Clubs", icon=":material/golf_course:"),
        st.Page("app_pages/handicap.py", title="Handicap", icon=":material/military_tech:"),
        st.Page("app_pages/data.py", title="Data & Syncing", icon=":material/table_chart:"),
    ]
)

page.run()

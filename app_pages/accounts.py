import streamlit as st

st.title("Accounts")

st.info("Accounts & syncing has moved to the **Data & Syncing** page (Accounts tab).")
if st.button("Go to Data & Syncing"):
    st.switch_page("app_pages/data.py")

import polars as pl
import streamlit as st

import stats
from filters import sidebar_filters

st.title("Overview")

stats.require_data()

full = stats.round_summary()
round_ids, summary = sidebar_filters(full)
summary = summary.sort("date")

hi = stats.handicap_index(full)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Handicap index", f"{hi:.1f}" if hi is not None else "—")
c2.metric(
    "Avg score (last 20)",
    round(summary.sort("date")["score"].tail(20).mean(), 1) if summary.height else "—",
)

eligible = summary.filter(pl.col("fir_pct").is_not_null()).sort("date")
with c3:
    val = round(eligible["fir_pct"].tail(20).mean(), 1) if eligible.height else None
    c3.metric("Fairways hit %", f"{val}%" if val is not None else "—")
eligible_gir = summary.filter(pl.col("gir_pct").is_not_null()).sort("date")
with c4:
    val = round(eligible_gir["gir_pct"].tail(20).mean(), 1) if eligible_gir.height else None
    c4.metric("Greens in regulation %", f"{val}%" if val is not None else "—")

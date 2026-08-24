from pathlib import Path

import polars as pl
import streamlit as st

st.set_page_config(page_title="Bogeyboard", layout="wide")

DATA_DIR = Path(__file__).resolve().parent / "data"


@st.cache_data(ttl=600, max_entries=3)
def load(name: str) -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / f"{name}.parquet")


rounds = load("rounds")
holes = load("holes")
shots = load("shots")

round_ids = rounds.sort("date", descending=True)["round_id"].to_list()
labels = {
    rid: str(rounds.filter(pl.col("round_id") == rid).select("date", "course_name").row(0))
    for rid in round_ids
}


def pick_rounds(key: str) -> list[int]:
    return st.multiselect(
        "Rounds",
        options=round_ids,
        format_func=labels.get,
        key=key,
        placeholder="All rounds",
    )


st.title("Bogeyboard")

tab_rounds, tab_holes, tab_shots = st.tabs(["Rounds", "Holes", "Shots"])

with tab_rounds:
    st.dataframe(rounds, hide_index=True)

with tab_holes:
    picked = pick_rounds("hole_filter")
    df = holes if not picked else holes.filter(pl.col("round_id").is_in(picked))
    st.dataframe(df, hide_index=True)

with tab_shots:
    picked = pick_rounds("shot_filter")
    df = shots if not picked else shots.filter(pl.col("round_id").is_in(picked))
    st.dataframe(df, hide_index=True)

st.caption(f"{rounds.height} rounds · {holes.height} holes · {shots.height} shots")

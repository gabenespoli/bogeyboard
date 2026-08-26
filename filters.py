import polars as pl
import streamlit as st

import settings as user_settings
import stats


def sidebar_filters(summary: pl.DataFrame | None = None) -> tuple[list[int], pl.DataFrame]:
    """Render the shared sidebar filter widgets and return (round_ids, filtered summary)."""
    if summary is None:
        summary = stats.round_summary()

    courses = sorted(summary["course_name"].unique().to_list())
    years = sorted({d[:4] for d in summary["date"].to_list() if d}, reverse=True)

    with st.sidebar:
        st.header("Filters")
        picked_courses = st.multiselect(
            "Courses",
            options=courses,
            key="filter_courses",
            placeholder="All courses",
        )
        year = st.selectbox(
            "Year",
            options=["All years", *years],
            key="filter_year",
        )
        window = st.segmented_control(
            "Round window",
            options=["All", "Last 10", "Last 20", "Last 40"],
            selection_mode="single",
            default="Last 20",
            key="filter_window",
        )
        hcp_only = st.checkbox(
            "Only rounds counting toward handicap",
            key="filter_hcp",
        )

    df = summary.filter(pl.col("score").is_not_null())
    if picked_courses:
        df = df.filter(pl.col("course_name").is_in(picked_courses))
    if year != "All years":
        df = df.filter(pl.col("date").str.starts_with(year))
    if hcp_only:
        df = df.filter(pl.col("counts"))
    limit = {"Last 10": 10, "Last 20": 20, "Last 40": 40}.get(window)
    if limit:
        df = df.sort("date", descending=True).head(limit)

    return df["round_id"].to_list(), df


def filter_holes(holes: pl.DataFrame, round_ids: list[int]) -> pl.DataFrame:
    return holes if not round_ids else holes.filter(pl.col("round_id").is_in(round_ids))


def club_filter_sidebar(round_ids: list[int] | None) -> list[str]:
    """Render clubs multiselect at bottom of sidebar and return effective club list.

    Uses available_clubs for the current round filter, persists selection in settings.
    Returns `available` when nothing picked (means All clubs).
    """
    available = stats.available_clubs(round_ids)
    saved = [c for c in user_settings.load_settings().get("clubs_selected", []) if c in available]
    with st.sidebar:
        st.divider()
        st.subheader("Clubs")
        picked = st.multiselect(
            "Clubs",
            options=available,
            default=saved,
            key="club_filter",
            placeholder="All clubs",
        )
    user_settings.update_setting("clubs_selected", picked)
    return picked if picked else available


def filter_round_ids(df: pl.DataFrame, round_ids: list[int], col: str = "round_id") -> pl.DataFrame:
    return df if not round_ids else df.filter(pl.col(col).is_in(round_ids))


def add_x_labels(df: pl.DataFrame, date_col: str = "date") -> pl.DataFrame:
    """One unique x category per round: dates shared by multiple rounds get (2), (3)..."""
    dupe_dates = (
        df.group_by(date_col)
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)[date_col]
        .to_list()
    )
    if not dupe_dates:
        return df.with_columns(pl.col(date_col).alias("x_label"))
    return (
        df.with_columns(pl.col(date_col).cum_count().over(date_col).alias("_occurrence"))
        .with_columns(
            pl.when(pl.col(date_col).is_in(dupe_dates))
            .then(
                pl.concat_str(
                    pl.col(date_col),
                    pl.lit(" ("),
                    pl.col("_occurrence").cast(pl.String),
                    pl.lit(")"),
                )
            )
            .otherwise(pl.col(date_col))
            .alias("x_label")
        )
        .drop("_occurrence")
    )

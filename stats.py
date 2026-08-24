"""Derived golf stats from the Parquet tables, shared by all dashboard pages."""

import polars as pl
import streamlit as st

DATA_DIR = __import__("pathlib").Path(__file__).resolve().parent / "data"

GRINT_FAIRWAY_HIT_CODE = "3"


@st.cache_data(ttl=600)
def load_rounds() -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / "rounds.parquet")


@st.cache_data(ttl=600)
def load_holes() -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / "holes.parquet")


@st.cache_data(ttl=600)
def load_shots() -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / "shots.parquet")


def enriched_holes() -> pl.DataFrame:
    """Holes table with fir/gir flags unified across sources (null = unknown)."""
    rounds_src = load_rounds().select("round_id", "source")
    h = load_holes().join(rounds_src, on="round_id", how="inner")

    h = h.with_columns(
        pl.when(
            (pl.col("source") == "grint")
            & pl.col("par").is_in([4, 5])
            & pl.col("fairway").is_not_null()
        )
        .then(pl.col("fairway") == GRINT_FAIRWAY_HIT_CODE)
        .otherwise(None)
        .alias("fir_grint")
    ).with_columns(
        pl.when(
            (pl.col("source") == "grint")
            & pl.col("par").is_not_null()
            & pl.col("score").is_not_null()
            & pl.col("putts").is_not_null()
        )
        .then((pl.col("score") - pl.col("putts")) <= (pl.col("par") - 2))
        .otherwise(None)
        .alias("gir_grint")
    )

    garmin_ids = rounds_src.filter(pl.col("source") == "garmin")
    if garmin_ids.height and load_shots().height:
        gs = load_shots().join(garmin_ids, on="round_id")
        tee_fir = (
            gs.filter(pl.col("shot_number") == 1)
            .select(
                "round_id",
                "hole_number",
                (pl.col("lie") == "Fairway").alias("_fir"),
            )
        )
        first_green = (
            gs.filter(pl.col("lie") == "Green")
            .group_by("round_id", "hole_number")
            .agg(pl.col("shot_number").min().alias("first_green"))
        )
        h = (
            h.join(tee_fir, on=["round_id", "hole_number"], how="left")
            .join(first_green, on=["round_id", "hole_number"], how="left")
            .with_columns(
                pl.when(
                    (pl.col("source") == "garmin")
                    & pl.col("par").is_in([4, 5])
                    & pl.col("_fir").is_not_null()
                )
                .then(pl.col("_fir"))
                .otherwise(None)
                .alias("fir_garmin")
            )
            .with_columns(
                pl.when(
                    (pl.col("source") == "garmin")
                    & pl.col("par").is_not_null()
                    & pl.col("first_green").is_not_null()
                )
                .then(pl.col("first_green") <= (pl.col("par") - 2))
                .otherwise(None)
                .alias("gir_garmin")
            )
            .drop("_fir", "first_green")
        )
    else:
        h = h.with_columns(
            pl.lit(None, dtype=pl.Boolean).alias("fir_garmin"),
            pl.lit(None, dtype=pl.Boolean).alias("gir_garmin"),
        )

    return h.with_columns(
        pl.coalesce("fir_garmin", "fir_grint").alias("fir"),
        pl.coalesce("gir_garmin", "gir_grint").alias("gir"),
    ).drop("fir_grint", "gir_grint", "fir_garmin", "gir_garmin")


def round_summary() -> pl.DataFrame:
    """One row per round with differential, FIR/GIR/scrambling %, putts."""
    holes = enriched_holes()
    agg = holes.group_by("round_id").agg(
        pl.col("fir").mean().mul(100).round(1).alias("fir_pct"),
        pl.col("gir").mean().mul(100).round(1).alias("gir_pct"),
        pl.col("putts").sum().alias("putts_total"),
        ((pl.col("gir") == False) & (pl.col("score") <= pl.col("par")))
        .sum()
        .alias("_saves"),
        (pl.col("gir") == False).sum().alias("_missed_greens"),
    )
    df = load_rounds().join(agg, on="round_id", how="left")
    df = df.with_columns(
        pl.when(
            pl.col("rating").is_not_null()
            & pl.col("slope").is_not_null()
            & (pl.col("holes_played") == 18)
        )
        .then(((pl.col("score") - pl.col("rating")) * 113 / pl.col("slope")).round(1))
        .otherwise(None)
        .alias("differential")
    )
    df = df.with_columns(
        pl.when(pl.col("_missed_greens") > 0)
        .then(pl.col("_saves") / pl.col("_missed_greens") * 100)
        .otherwise(None)
        .round(1)
        .alias("scramble_pct")
    ).drop("_saves", "_missed_greens")

    flagged = _handicap_flagged(df)
    return df.join(
        flagged.select("round_id", pl.col("counts").fill_null(False)),
        on="round_id",
        how="left",
    )


def _handicap_flagged(rounds: pl.DataFrame) -> pl.DataFrame:
    eligible = (
        rounds.filter(pl.col("differential").is_not_null())
        .sort("date", descending=True)
        .head(20)
    )
    if eligible.height == 0:
        return rounds.with_columns(pl.lit(None).alias("counts"))
    best = eligible.sort("differential").head(8)
    return rounds.with_columns(
        pl.col("round_id").is_in(best["round_id"]).alias("counts")
    )


def handicap_index(summary: pl.DataFrame) -> float | None:
    eligible = (
        summary.filter(pl.col("differential").is_not_null())
        .sort("date", descending=True)
        .head(20)
    )
    if eligible.height < 3:
        return None
    best = eligible.sort("differential").head(min(8, eligible.height))
    return round(best["differential"].mean(), 1)


def putt_distribution() -> pl.DataFrame:
    holes = load_holes().filter(pl.col("putts").is_not_null()).with_columns(
        pl.when(pl.col("putts") >= 4).then(4).otherwise(pl.col("putts")).alias("bin")
    )
    total = holes.height
    dist = (
        holes.group_by("bin")
        .agg(pl.len().alias("n"))
        .with_columns((pl.col("n") / total * 100).round(1).alias("pct"))
        .sort("bin")
    )
    labels = {0: "0 (holed out)", 1: "1 putt", 2: "2 putts", 3: "3 putts", 4: "4+ putts"}
    return dist.with_columns(
        pl.col("bin").replace_strict(labels, return_dtype=pl.String).alias("label")
    )


def putts_by_gir() -> pl.DataFrame:
    holes = enriched_holes().filter(pl.col("gir").is_not_null() & pl.col("putts").is_not_null())
    return holes.group_by(pl.col("gir")).agg(
        pl.col("putts").mean().round(2).alias("avg_putts"),
        pl.len().alias("holes"),
    )


def avg_score_by(expr: pl.Expr, order: list) -> pl.DataFrame:
    holes = load_holes().filter(pl.col("score").is_not_null() & expr.is_not_null())
    return (
        holes.group_by(expr.alias("bucket"))
        .agg(
            pl.col("score").mean().round(2).alias("avg_score"),
            (pl.col("score") - pl.col("par")).mean().round(2).alias("avg_vs_par"),
            pl.len().alias("holes"),
        )
        .sort("bucket")
    )


def club_distances() -> pl.DataFrame:
    shots = load_shots().filter(
        pl.col("club").is_not_null()
        & pl.col("distance_m").is_not_null()
        & (pl.col("shot_type") != "PUTT")
    )
    return (
        shots.group_by("club")
        .agg(
            (pl.col("distance_m").mean() / 0.9144).round(1).alias("avg_yds"),
            (pl.col("distance_m").max() / 0.9144).round(1).alias("best_yds"),
            pl.len().alias("shots"),
        )
        .sort("avg_yds", descending=True)
    )

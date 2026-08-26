"""Derived golf stats from the Parquet tables, shared by all dashboard pages."""

import math

import polars as pl
import streamlit as st

import paths

DATA_DIR = paths.DATA_DIR

GRINT_FAIRWAY_HIT_CODE = "3"
HOLE19_FAIRWAY_HIT_CODES = {"center", "target"}
HOLE19_TEE_CODES = {
    "center": "hit",
    "target": "hit",
    "left": "miss_left",
    "right": "miss_right",
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two lat/lon points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@st.cache_data(ttl=600)
def _inferred_yardage_cache() -> pl.DataFrame:
    """Per (course, hole, tee) yardage inferred from Garmin shot GPS.
    Primary: tee -> first green shot distance. Fallback: sum of non-putt shots.
    """
    rounds = load_rounds()
    holes = load_holes()
    shots = load_shots()
    if shots.height == 0:
        return pl.DataFrame(
            schema={
                "course_name": pl.String,
                "tee_box": pl.String,
                "hole_number": pl.UInt8,
                "par": pl.UInt8,
                "inferred_yardage": pl.UInt16,
            }
        )

    garmin_rounds = rounds.filter(pl.col("source") == "garmin").select(
        "round_id", "course_name", "tee_box"
    )
    garmin_holes = holes.filter(pl.col("source") == "garmin").select(
        "round_id", "hole_number", "par"
    )
    gh = garmin_holes.join(garmin_rounds, on="round_id", how="inner")

    # Method 1: tee to first green (most accurate = actual hole length)
    tee_shots = shots.filter(pl.col("shot_number") == 1).select(
        "round_id", "hole_number", "start_lat", "start_lon"
    )
    green_shots = (
        shots.filter(pl.col("lie") == "Green")
        .sort("shot_number")
        .group_by("round_id", "hole_number")
        .first()
        .select("round_id", "hole_number", "lat", "lon")
    )
    tee_to_green = tee_shots.join(green_shots, on=["round_id", "hole_number"], how="inner")
    tee_to_green = tee_to_green.filter(
        pl.col("start_lat").is_not_null() & pl.col("lat").is_not_null()
    )
    tee_to_green = tee_to_green.with_columns(
        pl.struct("start_lat", "start_lon", "lat", "lon")
        .map_elements(
            lambda x: round(_haversine(x["start_lat"], x["start_lon"], x["lat"], x["lon"]) / 0.9144)
        )
        .alias("tee_to_green_yds")
    )

    # Method 2: sum of non-putt shot distances (fallback)
    sum_shots = (
        shots.filter(pl.col("shot_type") != "PUTT")
        .group_by("round_id", "hole_number")
        .agg((pl.col("distance_m").sum() / 0.9144).round(0).alias("sum_method_yds"))
    )

    # Combine: prefer tee-to-green, fallback to sum
    inferred = gh.join(tee_to_green.select("round_id", "hole_number", "tee_to_green_yds"), on=["round_id", "hole_number"], how="left")
    inferred = inferred.join(sum_shots, on=["round_id", "hole_number"], how="left")
    inferred = inferred.with_columns(
        pl.coalesce("tee_to_green_yds", "sum_method_yds").cast(pl.UInt16).alias("inferred_yardage")
    )

    # Aggregate per (course, tee, hole, par) using median for consistency
    return (
        inferred.group_by("course_name", "tee_box", "hole_number", "par")
        .agg(pl.col("inferred_yardage").median().cast(pl.UInt16).alias("inferred_yardage"))
        .sort("course_name", "tee_box", "hole_number")
    )


@st.cache_data(ttl=600)
def load_rounds() -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / "rounds.parquet")


@st.cache_data(ttl=600)
def load_holes() -> pl.DataFrame:
    return pl.read_parquet(DATA_DIR / "holes.parquet")


@st.cache_data(ttl=600)
def load_shots() -> pl.DataFrame:
    path = DATA_DIR / "shots.parquet"
    if not path.exists():
        # Garmin-only table; Grint/Hole19-only users never have one.
        from fetch_garmin import SHOTS_SCHEMA

        return pl.DataFrame(schema=SHOTS_SCHEMA)
    return pl.read_parquet(path)


def require_data() -> None:
    """First-run gate: show a setup prompt instead of crashing on missing data files."""
    missing = [n for n in ("rounds.parquet", "holes.parquet") if not (DATA_DIR / n).exists()]
    if not missing:
        return
    st.info(
        "No golf data yet. Sign in to Garmin, TheGrint or Hole19 and run your first sync — "
        "it only takes a minute."
    )
    if st.button("Open the Accounts page", type="primary"):
        st.switch_page("app_pages/accounts.py")
    st.stop()


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
            (pl.col("source") == "hole19")
            & pl.col("par").is_in([4, 5])
            & pl.col("fairway").is_not_null()
        )
        .then(pl.col("fairway").is_in(HOLE19_FAIRWAY_HIT_CODES))
        .otherwise(None)
        .alias("fir_hole19")
    ).with_columns(
        pl.when(
            pl.col("source").is_in(["grint", "hole19"])
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
                pl.col("lie").is_in(["Fairway", "Green"]).alias("_fir"),
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

    # Join inferred yardage for Garmin holes missing yardage
    inferred = _inferred_yardage_cache()
    if inferred.height:
        rounds_with_course = load_rounds().select("round_id", "course_name", "tee_box")
        h = h.join(rounds_with_course, on="round_id", how="left")
        h = h.join(inferred, on=["course_name", "tee_box", "hole_number", "par"], how="left")
        h = h.with_columns(
            pl.coalesce("yardage", "inferred_yardage").alias("yardage")
        ).drop("inferred_yardage")

    return h.with_columns(
        pl.coalesce("fir_garmin", "fir_grint", "fir_hole19").alias("fir"),
        pl.coalesce("gir_garmin", "gir_grint").alias("gir"),
    ).drop("fir_grint", "fir_hole19", "gir_grint", "fir_garmin", "gir_garmin")


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


def putt_distribution(holes: pl.DataFrame | None = None) -> pl.DataFrame:
    if holes is None:
        holes = load_holes()
    holes = holes.filter(pl.col("putts").is_not_null()).with_columns(
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


def putts_by_gir(holes: pl.DataFrame | None = None) -> pl.DataFrame:
    if holes is None:
        holes = enriched_holes()
    holes = holes.filter(pl.col("gir").is_not_null() & pl.col("putts").is_not_null())
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


def shot_distances(
    club_names: list[str],
    round_ids: list[int] | None = None,
    trim_std: float | str | None = None,
    trim_std_high: float | str | None = None,
) -> pl.DataFrame:
    shots = load_shots().filter(
        pl.col("club").is_not_null()
        & pl.col("distance_m").is_not_null()
        & (pl.col("shot_type") != "PUTT")
        & pl.col("club").is_in(club_names)
    )
    if round_ids is not None:
        shots = (
            shots.filter(pl.col("round_id").is_in(round_ids))
            if round_ids
            else shots.clear()
        )
    shots = shots.select(
        "round_id",
        "club",
        (pl.col("distance_m") / 0.9144).alias("distance_yds"),
    )
    trims = {
        "low": trim_std if isinstance(trim_std, (int, float)) and trim_std else None,
        "high": trim_std_high
        if isinstance(trim_std_high, (int, float)) and trim_std_high
        else None,
    }
    if (trims["low"] is not None or trims["high"] is not None) and shots.height:
        shots = (
            shots.with_columns(
                pl.col("distance_yds").mean().over("club").alias("_mean"),
                pl.col("distance_yds").std().over("club").alias("_std"),
            )
            .with_columns(
                (pl.col("distance_yds") - pl.col("_mean")).alias("_dev")
            )
            .filter(
                (trims["low"] is None)
                | (-pl.col("_dev") <= trims["low"] * pl.col("_std"))
            )
            .filter(
                (trims["high"] is None)
                | (pl.col("_dev") <= trims["high"] * pl.col("_std"))
            )
            .drop("_mean", "_std", "_dev")
        )
    return shots


def shot_density(
    club_names: list[str],
    round_ids: list[int] | None = None,
    trim_std: float | str | None = None,
    trim_std_high: float | str | None = None,
    points: int = 120,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Gaussian KDE curves per club plus per-club means, ready for plotting."""
    shots = shot_distances(club_names, round_ids, trim_std=trim_std, trim_std_high=trim_std_high)
    means = shots.group_by("club").agg(
        pl.col("distance_yds").mean().round(1).alias("mean_yds")
    )
    if shots.height == 0:
        empty = pl.DataFrame(
            {"distance": [], "density": [], "club": []},
            schema={"distance": pl.Float64, "density": pl.Float64, "club": pl.String},
        )
        return empty, means

    frames = []
    for key, g in shots.group_by("club"):
        club = key[0] if isinstance(key, (tuple, list)) else key
        v = g["distance_yds"]
        n = v.len()
        sd = v.std() or 0.0
        iqr = v.quantile(0.75) - v.quantile(0.25)
        bandwidth = 0.9 * min(sd, iqr / 1.34) * n ** -0.2 if sd > 0 else 1.0
        lo, hi = v.min() - bandwidth * 2, v.max() + bandwidth * 2
        step = (hi - lo) / points
        grid = pl.DataFrame({"distance": [lo + step * i for i in range(points)]})
        curves_club = (
            grid.join(g.select("distance_yds"), how="cross")
            .with_columns(
                (
                    (pl.col("distance") - pl.col("distance_yds")) / bandwidth
                )
                .pow(2)
                .alias("_z2")
            )
            .group_by("distance")
            .agg((-0.5 * pl.col("_z2")).exp().sum().alias("density"))
            .with_columns(
                (pl.col("density") / (n * bandwidth)).alias("density"),
                pl.lit(club).alias("club"),
            )
            .select("distance", "density", "club")
            .sort("distance")
        )
        frames.append(curves_club)

    curves = pl.concat(frames)
    top = curves["density"].max()
    means = means.with_columns(pl.lit(top * 0.97).alias("label_y"))
    return curves, means


GRINT_TEE_CODES = {
    "3": "hit",
    "1": "miss_left",
    "7": "miss_left",
    "2": "miss_right",
    "8": "miss_right",
}


def _filter_rounds(df: pl.DataFrame, round_ids: list[int] | None) -> pl.DataFrame:
    if round_ids is None:
        return df
    return df.filter(pl.col("round_id").is_in(round_ids)) if round_ids else df.clear()


def tee_shot_outcomes(round_ids: list[int] | None = None) -> pl.DataFrame:
    """Per-round tee-shot outcome counts on par 4/5s: hit / miss_left / miss_right / miss_other."""
    holes = _filter_rounds(enriched_holes(), round_ids)

    rows = []
    app_holes = holes.filter(
        pl.col("source").is_in(["grint", "hole19"])
        & pl.col("par").is_in([4, 5])
        & pl.col("fairway").is_not_null()
    ).select("round_id", "source", "fairway")
    for r in app_holes.iter_rows(named=True):
        codes = HOLE19_TEE_CODES if r["source"] == "hole19" else GRINT_TEE_CODES
        rows.append((r["round_id"], codes.get(str(r["fairway"]), "miss_other")))

    garmin_rounds = load_rounds()
    garmin_rounds = (
        pl.DataFrame({"round_id": [], "source": []}, schema={"round_id": pl.UInt64, "source": pl.String})
        if garmin_rounds.height == 0
        else garmin_rounds.filter(pl.col("source") == "garmin")
    )
    garmin_holes = holes.filter(
        (pl.col("source") == "garmin") & pl.col("par").is_in([4, 5])
    ).select("round_id", "hole_number", "pin_lat", "pin_lon")
    tee_shots = load_shots().join(garmin_holes, on=["round_id", "hole_number"], how="inner")
    tee_shots = _filter_rounds(tee_shots, round_ids).filter(pl.col("shot_number") == 1)

    import math

    for r in tee_shots.iter_rows(named=True):
        if r["lie"] in ("Fairway", "Green"):
            rows.append((r["round_id"], "hit"))
            continue
        if None in (r["pin_lat"], r["start_lat"], r["start_lon"], r["lat"], r["lon"]):
            rows.append((r["round_id"], "miss_other"))
            continue
        lat_mid = math.radians((r["start_lat"] + r["pin_lat"]) / 2)
        ax = (r["pin_lon"] - r["start_lon"]) * math.cos(lat_mid)
        ay = r["pin_lat"] - r["start_lat"]
        bx = (r["lon"] - r["start_lon"]) * math.cos(lat_mid)
        by = r["lat"] - r["start_lat"]
        cross = ax * by - ay * bx
        rows.append((r["round_id"], "miss_left" if cross > 0 else "miss_right"))

    if not rows:
        return pl.DataFrame(
            {"round_id": [], "outcome": [], "n": []},
            schema={"round_id": pl.UInt64, "outcome": pl.String, "n": pl.UInt32},
        )
    df = pl.DataFrame(rows, schema={"round_id": pl.UInt64, "outcome": pl.String}, orient="row")
    return df.group_by("round_id", "outcome").agg(pl.len().alias("n"))


def approach_shot_outcomes(round_ids: list[int] | None = None) -> pl.DataFrame:
    """Per-round approach outcomes using Garmin's APPROACH shot flag.

    hit = end-lie Green, or holed out (final shot of hole ending within ~6 yds of pin).
    Misses classified left/right by geometry against the tee->pin line.
    """
    holes = load_holes().filter(pl.col("source") == "garmin").select(
        "round_id", "hole_number", "par", "pin_lat", "pin_lon"
    )
    shots = (
        load_shots()
        .filter(pl.col("shot_type") == "APPROACH")
        .join(holes, on=["round_id", "hole_number"], how="inner")
        .sort("shot_number")
    )
    shots = _filter_rounds(shots, round_ids)
    if shots.height == 0:
        return pl.DataFrame(
            {"round_id": [], "outcome": [], "n": []},
            schema={"round_id": pl.UInt64, "outcome": pl.String, "n": pl.UInt32},
        )

    last_shot = shots.group_by("round_id", "hole_number").agg(
        pl.col("shot_number").max().alias("_hole_last")
    )
    shots = shots.join(last_shot, on=["round_id", "hole_number"], how="left")

    import math

    rows = []
    for r in shots.iter_rows(named=True):
        end_lie = r["lie"]
        holed = False
        if r["pin_lat"] is not None and r["lat"] is not None and r["lon"] is not None:
            dy = (r["lat"] - r["pin_lat"]) * 111_320
            dx = (r["lon"] - r["pin_lon"]) * 111_320 * math.cos(math.radians(r["lat"]))
            holed = math.hypot(dy, dx) / 0.9144 <= 6
        is_final_shot = r["_hole_last"] == r["shot_number"]

        if end_lie == "Green" or (holed and is_final_shot):
            outcome = "hit_reg" if r["shot_number"] <= r["par"] - 2 else "hit_noreg"
        elif None in (r["pin_lat"], r["start_lat"], r["start_lon"], r["lat"], r["lon"]):
            outcome = "miss_other"
        else:
            lat_mid = math.radians((r["start_lat"] + r["pin_lat"]) / 2)
            ax = (r["pin_lon"] - r["start_lon"]) * math.cos(lat_mid)
            ay = r["pin_lat"] - r["start_lat"]
            bx = (r["lon"] - r["start_lon"]) * math.cos(lat_mid)
            by = r["lat"] - r["start_lat"]
            cross = ax * by - ay * bx
            outcome = "miss_left" if cross > 0 else "miss_right"
        rows.append((r["round_id"], outcome))

    df = pl.DataFrame(rows, schema={"round_id": pl.UInt64, "outcome": pl.String}, orient="row")
    return df.group_by("round_id", "outcome").agg(pl.len().alias("n"))


def available_clubs(round_ids: list[int] | None = None) -> list[str]:
    shots = load_shots().filter(
        pl.col("club").is_not_null()
        & pl.col("distance_m").is_not_null()
        & (pl.col("shot_type") != "PUTT")
    )
    if round_ids is not None:
        shots = (
            shots.filter(pl.col("round_id").is_in(round_ids))
            if round_ids
            else shots.clear()
        )
    return (
        shots.group_by("club")
        .agg(pl.col("distance_m").mean().alias("_avg"))
        .sort("_avg", descending=True)["club"]
        .to_list()
    )


def club_distances(
    round_ids: list[int] | None = None,
    club_names: list[str] | None = None,
    trim_std: float | str | None = None,
    trim_std_high: float | str | None = None,
) -> pl.DataFrame:
    shots = shot_distances(
        club_names if club_names is not None else available_clubs(round_ids),
        round_ids,
        trim_std=trim_std,
        trim_std_high=trim_std_high,
    )
    return (
        shots.group_by("club")
        .agg(
            pl.col("distance_yds").mean().round(1).alias("avg_yds"),
            pl.len().alias("shots"),
        )
        .sort("avg_yds", descending=True)
    )

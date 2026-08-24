import polars as pl

ROUNDS_SCHEMA = {
    "round_id": pl.UInt64,
    "date": pl.String,
    "course_name": pl.String,
    "score": pl.Int64,
    "to_par": pl.Int64,
    "holes_played": pl.UInt8,
    "putts": pl.UInt8,
    "fairways_hit": pl.UInt8,
    "fairways_possible": pl.UInt8,
    "gir_count": pl.UInt8,
}

HOLES_SCHEMA = {
    "round_id": pl.UInt64,
    "hole_number": pl.UInt8,
    "par": pl.UInt8,
    "score": pl.Int64,
    "putts": pl.UInt8,
    "fairway": pl.String,
    "gir": pl.Boolean,
    "penalties": pl.UInt8,
}

SHOTS_SCHEMA = {
    "round_id": pl.UInt64,
    "hole_number": pl.UInt8,
    "shot_number": pl.UInt8,
    "club": pl.String,
    "is_club_tagged": pl.Boolean,
    "shot_type": pl.String,
    "lie": pl.String,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "distance_m": pl.Float64,
}


def empty_df(schema: dict) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)

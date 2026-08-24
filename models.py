import polars as pl

ROUNDS_SCHEMA = {
    "round_id": pl.UInt64,
    "date": pl.String,
    "course_name": pl.String,
    "score": pl.Int64,
    "to_par": pl.Int64,
    "holes_played": pl.UInt8,
    "tee_box": pl.String,
    "slope": pl.Float64,
    "rating": pl.Float64,
    "walk_distance_m": pl.Float64,
}

HOLES_SCHEMA = {
    "round_id": pl.UInt64,
    "hole_number": pl.UInt8,
    "par": pl.UInt8,
    "score": pl.Int64,
    "putts": pl.UInt8,
    "penalties": pl.UInt8,
}

SHOTS_SCHEMA = {
    "round_id": pl.UInt64,
    "hole_number": pl.UInt8,
    "shot_number": pl.UInt8,
    "club": pl.String,
    "is_club_tagged": pl.Boolean,
    "shot_type": pl.String,
    "shot_source": pl.String,
    "lie": pl.String,
    "start_lat": pl.Float64,
    "start_lon": pl.Float64,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "distance_m": pl.Float64,
}

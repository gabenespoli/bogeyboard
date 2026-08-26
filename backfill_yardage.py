"""One-time backfill: write inferred Garmin yardage to holes.parquet."""
import polars as pl
import paths

from stats import _inferred_yardage_cache, load_holes, load_rounds

DATA_DIR = paths.DATA_DIR
HOLES_PATH = DATA_DIR / "holes.parquet"


def main() -> None:
    paths.ensure_layout()

    print("Loading current holes...")
    holes = load_holes()
    print(f"  {holes.height} total holes")

    print("Computing inferred yardage...")
    inferred = _inferred_yardage_cache()
    print(f"  {inferred.height} (course, tee, hole, par) combinations with inferred yardage")

    if inferred.height == 0:
        print("No inferred yardage available (no shot data).")
        return

    # Get course/tee for each round
    rounds = load_rounds().select("round_id", "course_name", "tee_box")

    # Join holes with round info, then with inferred yardage
    garmin_holes = holes.filter(pl.col("source") == "garmin").join(
        rounds, on="round_id", how="left"
    )

    updated = garmin_holes.join(
        inferred, on=["course_name", "tee_box", "hole_number", "par"], how="left"
    ).with_columns(
        pl.coalesce("yardage", "inferred_yardage").alias("yardage")
    ).drop("inferred_yardage", "course_name", "tee_box")

    # Merge back with non-Garmin holes
    other_holes = holes.filter(pl.col("source") != "garmin")
    all_holes = pl.concat([other_holes, updated], how="vertical_relaxed")

    # Write back
    all_holes.sort(["round_id", "hole_number"]).write_parquet(HOLES_PATH)
    print(f"Written {all_holes.height} holes to {HOLES_PATH}")

    # Report
    garmin_with_yards = all_holes.filter(
        (pl.col("source") == "garmin") & pl.col("yardage").is_not_null()
    )
    print(f"Garmin holes with yardage: {garmin_with_yards.height} / {all_holes.filter(pl.col('source') == 'garmin').height}")


if __name__ == "__main__":
    main()
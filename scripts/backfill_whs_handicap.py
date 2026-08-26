"""One-time backfill: compute and persist WHS scaled differentials + HI history to rounds.parquet."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl
import paths

from stats import _compute_scaled_differentials, load_rounds, load_holes, handicap_index

DATA_DIR = paths.DATA_DIR
ROUNDS_PATH = DATA_DIR / "rounds.parquet"


def main() -> None:
    paths.ensure_layout()

    print("Loading rounds...")
    rounds = load_rounds()
    print(f"  {rounds.height} total rounds")

    print("Computing WHS scaled differentials chronologically...")
    updated = _compute_scaled_differentials(rounds)

    print("Writing updated rounds to parquet...")
    updated.sort(["date", "round_id"]).write_parquet(ROUNDS_PATH)
    print(f"Written {updated.height} rounds to {ROUNDS_PATH}")

    # Report
    with_diff = updated.filter(pl.col("differential").is_not_null())
    print(f"Rounds with differential: {with_diff.height} / {updated.height}")
    print(f"  18-hole: {with_diff.filter(pl.col('holes_played')==18).height}")
    print(f"  9-hole (scaled): {with_diff.filter(pl.col('is_scaled_9')==True).height}")
    print(f"  9-hole (fallback): {with_diff.filter((pl.col('holes_played')==9) & (pl.col('expected_9').is_null())).height}")

    # Current HI
    from stats import handicap_index
    hi = handicap_index(updated)
    print(f"Current WHS Handicap Index: {hi}")


if __name__ == "__main__":
    main()
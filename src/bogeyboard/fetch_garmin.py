"""Fetch all golf rounds from Garmin Connect into Parquet tables.

Usage:
    uv run python -m bogeyboard.fetch_garmin            # incremental
    uv run python -m bogeyboard.fetch_garmin --full     # re-backfill everything
    uv run python -m bogeyboard.fetch_garmin --since 2026-06-01
"""

import argparse
import json
import sys
import time
from pathlib import Path

import polars as pl

from .auth import get_client
from .models import HOLES_SCHEMA, ROUNDS_SCHEMA, SHOTS_SCHEMA

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"

FETCH_DELAY_S = 1.0


def _first(d, *keys):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v is not None:
            return v
    return None


def _coord(v):
    """Garmin sometimes returns coords scaled by 1e7."""
    if v is None:
        return None
    v = float(v)
    return v / 1e7 if abs(v) > 180 else v


def _to_par(score, par):
    if score is None or par is None:
        return None
    return int(score) - int(par)


def parse_round_summary(item: dict) -> dict | None:
    round_id = _first(item, "id", "scorecardId")
    if round_id is None:
        return None
    date = str(_first(item, "date", "startTimeLocal", "startTimeUtc") or "")[:10]
    course = str(_first(item, "courseName", "course", "name") or "")
    score = _first(item, "score", "totalStrokes")
    par = _first(item, "par", "coursePar")
    holes_played = _first(item, "holesPlayed", "holeCount")
    return {
        "round_id": int(round_id),
        "date": date,
        "course_name": course,
        "score": int(score) if score is not None else None,
        "to_par": _to_par(score, par),
        "holes_played": int(holes_played) if holes_played is not None else None,
        "putts": _first(item, "putts", "totalPutts"),
        "fairways_hit": _first(item, "fairwaysHit"),
        "fairways_possible": _first(item, "fairwayOpportunities"),
        "gir_count": _first(item, "girCount"),
    }


def parse_holes(detail: dict, round_id: int) -> list[dict]:
    holes = _first(detail, "holes", "golfHoles") or []
    rows = []
    for h in holes:
        num = _first(h, "holeNumber", "number", "holeId")
        if num is None:
            continue
        rows.append(
            {
                "round_id": round_id,
                "hole_number": int(num),
                "par": _first(h, "par"),
                "score": _first(h, "score", "strokes"),
                "putts": _first(h, "putts"),
                "fairway": _first(h, "fairwayMarking", "fairway"),
                "gir": _first(h, "gir", "greenInRegulation"),
                "penalties": _first(h, "penaltyCount", "penalties"),
            }
        )
    return rows


def parse_shots(shot_data: dict, round_id: int) -> list[dict]:
    """Shot payloads vary by device/firmware; extract defensively and keep raw JSON on disk."""
    rows = []

    def walk(obj, current_hole=None):
        if isinstance(obj, list):
            for x in obj:
                walk(x, current_hole)
            return
        if not isinstance(obj, dict):
            return

        hole = _first(obj, "holeNumber", "number") or current_hole
        shots = _first(obj, "shots", "shotList")
        if shots is not None:
            walk(shots, hole)
            return

        seq = _first(obj, "shotSequenceNumber", "sequenceNumber", "shotNumber")
        if seq is None:
            for v in obj.values():
                walk(v, hole)
            return

        club_obj = obj.get("clubType") or {}
        club = (
            club_obj.get("value") or club_obj.get("clubName")
            if isinstance(club_obj, dict)
            else club_obj
        )
        pos = _first(obj, "endPosition", "position", "location") or {}
        start_pos = _first(obj, "startPosition") or {}
        dist = _first(
            obj,
            "distanceMeters",
            "shotDistanceMeters",
            "distance",
            "meters",
        )
        if dist is None and pos.get("latitude") and start_pos.get("latitude"):
            from math import asin, cos, radians, sin, sqrt

            lat1, lon1 = _coord(start_pos["latitude"]), _coord(start_pos["longitude"])
            lat2, lon2 = _coord(pos["latitude"]), _coord(pos["longitude"])
            dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
            a = (
                sin(dlat / 2) ** 2
                + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
            )
            dist = 2 * 6_371_000 * asin(sqrt(a))

        rows.append(
            {
                "round_id": round_id,
                "hole_number": int(hole) if hole is not None else None,
                "shot_number": int(seq),
                "club": str(club) if club else None,
                "is_club_tagged": bool(club),
                "shot_type": _first(obj, "shotType", "type"),
                "lie": _first(obj, "lieType", "lie"),
                "lat": _coord(pos.get("latitude")),
                "lon": _coord(pos.get("longitude")),
                "distance_m": float(dist) if dist is not None else None,
            }
        )

    walk(shot_data)
    return rows


def fetch_all(full: bool, since: str | None) -> None:
    client = get_client()
    DATA_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)

    stored_rounds = pl.DataFrame(schema=ROUNDS_SCHEMA)
    rounds_path = DATA_DIR / "rounds.parquet"
    existing_ids: set[int] = set()
    if rounds_path.exists() and not full:
        stored_rounds = pl.read_parquet(rounds_path)
        existing_ids = set(stored_rounds["round_id"].to_list())
        print(f"Loaded {stored_rounds.height} existing rounds")

    print("Fetching round summaries...")
    summaries = []
    start = 0
    while True:
        batch = client.get_golf_summary(start=start, limit=100)
        if not batch:
            break
        summaries.extend(batch)
        if len(batch) < 100:
            break
        start += 100

    parsed = [r for s in summaries if (r := parse_round_summary(s))]
    if since:
        parsed = [r for r in parsed if r["date"] >= since]
    new_rounds = [r for r in parsed if r["round_id"] not in existing_ids]
    new_rounds.sort(key=lambda r: r["date"])
    print(f"{len(parsed)} total rounds found, {len(new_rounds)} new to fetch")

    holes_df = empty(HOLES_SCHEMA) if full else load_or_empty("holes.parquet", HOLES_SCHEMA)
    shots_df = empty(SHOTS_SCHEMA) if full else load_or_empty("shots.parquet", SHOTS_SCHEMA)
    if full:
        holes_df = holes_df.filter(pl.lit(False))
        shots_df = shots_df.filter(pl.lit(False))

    failures = []
    for i, rnd in enumerate(new_rounds, 1):
        rid = rnd["round_id"]
        label = f"{rnd['date']} {rnd['course_name']} ({rid})"
        try:
            detail = client.get_golf_scorecard(rid)
            time.sleep(FETCH_DELAY_S)
            raw_shots = None
            try:
                raw_shots = client.get_golf_shot_data(rid)
                time.sleep(FETCH_DELAY_S)
            except Exception as e:
                print(f"  no shot data for {label}: {e.__class__.__name__}")

            holes_rows = parse_holes(detail, rid)
            shots_rows = parse_shots(raw_shots, rid) if raw_shots else []

            (RAW_DIR / f"{rid}.json").write_text(
                json.dumps({"summary": rnd, "detail": detail, "shots": raw_shots}, default=str)
            )
            print(f"[{i}/{len(new_rounds)}] {label}: {len(holes_rows)} holes, {len(shots_rows)} shots")

            holes_df = pl.concat([holes_df, pl.DataFrame(holes_rows, schema=HOLES_SCHEMA)], how="vertical_relaxed")
            shots_df = pl.concat([shots_df, pl.DataFrame(shots_rows, schema=SHOTS_SCHEMA)], how="vertical_relaxed")
        except Exception as e:
            failures.append((label, e))
            print(f"  FAILED {label}: {e}")

    all_rounds = pl.concat(
        [stored_rounds, pl.DataFrame(new_rounds, schema=ROUNDS_SCHEMA)], how="vertical_relaxed"
    ).unique(subset=["round_id"], keep="last")
    all_rounds.sort("date").write_parquet(rounds_path)
    holes_df.sort(["round_id", "hole_number"]).write_parquet(DATA_DIR / "holes.parquet")
    shots_df.sort(["round_id", "hole_number", "shot_number"]).write_parquet(
        DATA_DIR / "shots.parquet"
    )

    print("\nDone:")
    print(f"  rounds: {all_rounds.height} -> data/rounds.parquet")
    print(f"  holes:  {holes_df.height} -> data/holes.parquet")
    print(f"  shots:  {shots_df.height} -> data/shots.parquet")
    if failures:
        print(f"\n{len(failures)} rounds failed — rerun to retry:")
        for label, e in failures:
            print(f"  {label}: {e}")
        sys.exit(1)


def load_or_empty(name: str, schema: dict) -> pl.DataFrame:
    path = DATA_DIR / name
    return pl.read_parquet(path) if path.exists() else pl.DataFrame(schema=schema)


def empty(schema: dict) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="re-fetch everything")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="only fetch rounds after this date")
    args = parser.parse_args()
    fetch_all(full=args.full, since=args.since)


if __name__ == "__main__":
    main()

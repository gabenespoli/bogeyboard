"""Fetch all golf rounds from Garmin Connect into Parquet tables.

Usage:
    uv run python fetch_garmin.py            # incremental
    uv run python fetch_garmin.py --full     # re-backfill everything
    uv run python fetch_garmin.py --since 2026-06-01
"""

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

import polars as pl
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

import credentials
import paths

DATA_DIR = paths.DATA_DIR
RAW_DIR = DATA_DIR / "raw"

FETCH_DELAY_S = 1.0
TOKEN_STORE = paths.GARMIN_TOKEN_STORE

# Set by main() when --headless is passed; the dashboard runs syncs headlessly.
HEADLESS = False

ROUNDS_SCHEMA = {
    "round_id": pl.UInt64,
    "source": pl.String,
    "date": pl.String,
    "course_name": pl.String,
    "score": pl.Int64,
    "to_par": pl.Int64,
    "holes_played": pl.UInt8,
    "tee_box": pl.String,
    "slope": pl.Float64,
    "rating": pl.Float64,
    "walk_distance_m": pl.Float64,
    "differential": pl.Float64,
    "differential_9_raw": pl.Float64,
    "expected_9": pl.Float64,
    "hi_before": pl.Float64,
    "hi_after": pl.Float64,
    "is_scaled_9": pl.Boolean,
    "rating9": pl.Float64,
    "slope9": pl.Float64,
    "rating18": pl.Float64,
    "slope18": pl.Float64,
}

HOLES_SCHEMA = {
    "round_id": pl.UInt64,
    "source": pl.String,
    "hole_number": pl.UInt8,
    "par": pl.UInt8,
    "score": pl.Int64,
    "putts": pl.UInt8,
    "penalties": pl.UInt8,
    "fairway": pl.String,
    "yardage": pl.UInt16,
    "pin_lat": pl.Float64,
    "pin_lon": pl.Float64,
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

CLUB_STATS_SCHEMA = {
    "club": pl.String,
    "averageDistance_m": pl.Float64,
    "averageDistance_yds": pl.Float64,
    "maxDistance_m": pl.Float64,
    "minDistance_m": pl.Float64,
    "shotsCount": pl.Int64,
}


def _prompt_mfa() -> str:
    code = os.environ.get("GARMIN_MFA_CODE", "").strip()
    if code:
        return code
    if HEADLESS:
        sys.exit("Garmin MFA required — enter a current code on the Accounts page before syncing")
    return input("Enter MFA code: ").strip()


def get_client(token_store: Path = TOKEN_STORE) -> Garmin:
    """Return a logged-in Garmin client, using cached tokens when possible."""
    if token_store.exists():
        try:
            client = Garmin()
            client.login(tokenstore=str(token_store))
            return client
        except (GarminConnectAuthenticationError, FileNotFoundError) as e:
            print(f"Cached tokens invalid ({e.__class__.__name__}), logging in fresh...")
        except GarminConnectConnectionError as e:
            sys.exit(f"Connection error while using cached tokens: {e}")

    saved = credentials.get_login("garmin")
    if saved:
        email, password = saved
        try:
            client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
            client.login(tokenstore=str(token_store))
            print("Login OK using stored credentials")
            return client
        except GarminConnectAuthenticationError as e:
            print(f"Stored credentials rejected ({e.__class__.__name__}), prompting...")
        except GarminConnectConnectionError as e:
            sys.exit(f"Connection error: {e}")

    if HEADLESS:
        sys.exit("No Garmin credentials stored — sign in on the Accounts page first")

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    try:
        client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
        client.login(tokenstore=str(token_store))
    except GarminConnectAuthenticationError as e:
        sys.exit(f"Authentication failed: {e}")
    except GarminConnectConnectionError as e:
        sys.exit(f"Connection error: {e}")

    if input("Save these credentials to the Bogeyboard login file? (y/n) ").strip().lower() == "y":
        credentials.save_login("garmin", email, password)
        print(f"Credentials saved to {credentials.LOGIN_FILE}")

    print(f"Login OK — tokens cached at {token_store} (valid ~1 year)")
    return client



def _coord(v):
    """Garmin returns coords scaled by 1e7."""
    return float(v) / 1e7 if v is not None else None


def parse_round_summary(item: dict) -> dict | None:
    round_id = item.get("id")
    if round_id is None:
        return None
    hole_pars = str(item.get("holePars") or "")
    par_total = sum(int(c) for c in hole_pars if c.isdigit())
    strokes = item.get("strokes")
    return {
        "round_id": int(round_id),
        "source": "garmin",
        "date": str(item.get("startTime") or "")[:10],
        "course_name": str(item.get("courseName") or ""),
        "score": int(strokes) if strokes is not None else None,
        "to_par": int(strokes) - par_total if strokes is not None and par_total else None,
        "holes_played": item.get("holesCompleted"),
        "tee_box": "",
        "slope": None,
        "rating": None,
        "walk_distance_m": None,
    }


def parse_round_detail(detail: dict, rnd: dict) -> dict:
    """Enrich a parsed summary with tee/slope/walk data from the scorecard detail."""
    cards = detail.get("scorecardDetails") or []
    sc = cards[0].get("scorecard", {}) if cards else {}
    rnd["tee_box"] = str(sc.get("teeBox") or "")
    rnd["slope"] = sc.get("teeBoxSlope")
    rnd["rating"] = sc.get("teeBoxRating")
    walked = sc.get("distanceWalked")
    rnd["walk_distance_m"] = float(walked) if walked else None
    return rnd


def parse_holes(detail: dict, round_id: int, pars_by_hole: dict[int, int]) -> list[dict]:
    cards = detail.get("scorecardDetails") or []
    holes = cards[0].get("scorecard", {}).get("holes", []) if cards else []
    rows = []
    for h in holes:
        num = h.get("number")
        if num is None:
            continue
        rows.append(
            {
                "round_id": round_id,
                "source": "garmin",
                "hole_number": int(num),
                "par": pars_by_hole.get(int(num)),
                "score": h.get("strokes"),
                "putts": h.get("putts"),
                "penalties": h.get("penalties"),
                "fairway": None,
                "yardage": None,
                "pin_lat": _coord(h.get("pinPositionLat")),
                "pin_lon": _coord(h.get("pinPositionLon")),
            }
        )
    return rows


def _compute_yardage(holes_rows: list[dict], shots_rows: list[dict]) -> list[dict]:
    """Infer yardage per hole from shot GPS data.
    Primary: tee -> first green shot. Fallback: sum of non-putt shots.
    """
    if not shots_rows:
        return holes_rows

    import math

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * R * math.asin(math.sqrt(a))

    # Group shots by hole
    shots_by_hole: dict[int, list[dict]] = {}
    for s in shots_rows:
        hn = s.get("hole_number")
        if hn is not None:
            shots_by_hole.setdefault(hn, []).append(s)

    # Compute per hole
    hole_yardage: dict[int, int] = {}
    for hn, shots in shots_by_hole.items():
        shots_sorted = sorted(shots, key=lambda x: x.get("shot_number") or 0)

        # Method 1: tee to first green
        tee_shot = next((s for s in shots_sorted if s.get("shot_number") == 1), None)
        green_shot = next((s for s in shots_sorted if s.get("lie") == "Green"), None)

        yds = None
        if tee_shot and green_shot:
            slat, slon = tee_shot.get("start_lat"), tee_shot.get("start_lon")
            glat, glon = green_shot.get("lat"), green_shot.get("lon")
            if None not in (slat, slon, glat, glon):
                yds = round(haversine(slat, slon, glat, glon) / 0.9144)

        # Method 2: sum of non-putt shots
        if yds is None:
            non_putt = [s for s in shots_sorted if s.get("shot_type") != "PUTT" and s.get("distance_m")]
            if non_putt:
                yds = round(sum(s["distance_m"] for s in non_putt) / 0.9144)

        if yds is not None:
            hole_yardage[hn] = yds

    # Apply to holes
    for h in holes_rows:
        hn = h["hole_number"]
        if hn in hole_yardage:
            h["yardage"] = hole_yardage[hn]

    return holes_rows


def parse_shots(shot_data: dict, round_id: int) -> list[dict]:
    clubs = {
        c["id"]: c.get("name")
        for c in shot_data.get("clubDetails") or []
        if c.get("id")
    }
    rows = []
    for hole in shot_data.get("holeShots") or []:
        hole_number = hole.get("holeNumber")
        for s in hole.get("shots") or []:
            club_id = s.get("clubId")
            start_loc = s.get("startLoc") or {}
            end_loc = s.get("endLoc") or {}
            dist = s.get("meters")
            rows.append(
                {
                    "round_id": round_id,
                    "hole_number": int(hole_number) if hole_number is not None else None,
                    "shot_number": s.get("shotOrder"),
                    "club": clubs.get(club_id),
                    "is_club_tagged": bool(club_id),
                    "shot_type": s.get("shotType"),
                    "shot_source": s.get("shotSource"),
                    "lie": end_loc.get("lie"),
                    "start_lat": _coord(start_loc.get("lat")),
                    "start_lon": _coord(start_loc.get("lon")),
                    "lat": _coord(end_loc.get("lat")),
                    "lon": _coord(end_loc.get("lon")),
                    "distance_m": float(dist) if dist is not None else None,
                }
            )
    return rows


def fetch_club_stats(client: Garmin) -> None:
    """Fetch Garmin's official club averages and store to parquet for replication."""
    try:
        data = client.get_golf_club_stats()
        # data is list of club dicts
        clubs = data if isinstance(data, list) else data.get("clubStats", []) if isinstance(data, dict) else []
        rows = []
        for c in clubs:
            name = c.get("name")
            cs = c.get("clubStats") or {}
            if not name or not cs:
                continue
            avg_m = cs.get("averageDistance")
            if avg_m is None:
                continue
            rows.append(
                {
                    "club": str(name),
                    "averageDistance_m": float(avg_m) if avg_m is not None else None,
                    "averageDistance_yds": float(avg_m) / 0.9144 if avg_m is not None else None,
                    "maxDistance_m": float(cs.get("maximumRecentDistance")) if cs.get("maximumRecentDistance") is not None else None,
                    "minDistance_m": float(cs.get("minimumRecentDistance")) if cs.get("minimumRecentDistance") is not None else None,
                    "shotsCount": int(cs.get("shotsCount")) if cs.get("shotsCount") is not None else None,
                }
            )
        if rows:
            df = pl.DataFrame(rows, schema=CLUB_STATS_SCHEMA)
            df.sort("averageDistance_yds", descending=True).write_parquet(DATA_DIR / "garmin_club_stats.parquet")
            # also save raw for inspection
            (DATA_DIR / "raw" / "garmin_club_stats.json").write_text(json.dumps(data, indent=2, default=str))
            print(f"  club stats: {df.height} clubs -> data/garmin_club_stats.parquet")
        else:
            print("  club stats: no data")
    except Exception as e:
        print(f"  club stats failed: {e.__class__.__name__}: {e}")


def fetch_all(full: bool, since: str | None) -> None:
    client = get_client()
    DATA_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)

    stored_rounds = pl.DataFrame(schema=ROUNDS_SCHEMA)
    rounds_path = DATA_DIR / "rounds.parquet"
    existing_ids: set[int] = set()
    if rounds_path.exists() and not full:
        _loaded = pl.read_parquet(rounds_path)
        # Clean up legacy duplicate *_right columns from earlier backfill bug
        _loaded = _loaded.select([c for c in _loaded.columns if not c.endswith("_right")])
        # Ensure schema matches ROUNDS_SCHEMA (add missing cols as null, drop extras)
        for col, dtype in ROUNDS_SCHEMA.items():
            if col not in _loaded.columns:
                _loaded = _loaded.with_columns(pl.lit(None, dtype=dtype).alias(col))
        stored_rounds = _loaded.select(list(ROUNDS_SCHEMA.keys()))
        existing_ids = set(stored_rounds["round_id"].to_list()) if stored_rounds.height else set()
        print(f"Loaded {stored_rounds.height} existing rounds")

    print("Fetching round summaries...")
    summaries = []
    start = 0
    total_rows = None
    while total_rows is None or len(summaries) < total_rows:
        batch = client.get_golf_summary(start=start, limit=100)
        items = batch.get("scorecardSummaries") or [] if isinstance(batch, dict) else batch
        total_rows = batch.get("totalRows", len(summaries)) if isinstance(batch, dict) else None
        summaries.extend(items)
        if not items:
            break
        start += len(items)

    parsed = []
    pars_by_round = {}
    for s in summaries:
        if r := parse_round_summary(s):
            parsed.append(r)
            pars_by_round[r["round_id"]] = {
                n + 1: int(c) for n, c in enumerate(str(s.get("holePars") or "")) if c.isdigit()
            }
    if since:
        parsed = [r for r in parsed if r["date"] >= since]
    new_rounds = [r for r in parsed if r["round_id"] not in existing_ids]
    new_rounds.sort(key=lambda r: r["date"])
    print(f"{len(parsed)} total rounds found, {len(new_rounds)} new to fetch")

    holes_df = load_or_empty("holes.parquet", HOLES_SCHEMA)
    shots_df = load_or_empty("shots.parquet", SHOTS_SCHEMA)
    if full:
        holes_df = holes_df.clear()
        shots_df = shots_df.clear()

    failures = []
    for i, rnd in enumerate(new_rounds, 1):
        rid = rnd["round_id"]
        label = f"{rnd['date']} {rnd['course_name']} ({rid})"
        try:
            detail = client.get_golf_scorecard(rid)
            parse_round_detail(detail, rnd)
            time.sleep(FETCH_DELAY_S)
            raw_shots = None
            try:
                raw_shots = client.get_golf_shot_data(rid)
                time.sleep(FETCH_DELAY_S)
            except Exception as e:
                print(f"  no shot data for {label}: {e.__class__.__name__}")

            pars_by_hole = pars_by_round.get(rid, {})

            holes_rows = parse_holes(detail, rid, pars_by_hole)
            shots_rows = parse_shots(raw_shots, rid) if raw_shots else []

            holes_rows = _compute_yardage(holes_rows, shots_rows)

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

    # Fetch official Garmin club averages for replication option
    fetch_club_stats(client)

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


def main() -> None:
    global HEADLESS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="re-fetch everything")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="only fetch rounds after this date")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="never prompt interactively; fail with a clear error if credentials are missing",
    )
    args = parser.parse_args()
    HEADLESS = args.headless
    paths.ensure_layout()
    fetch_all(full=args.full, since=args.since)


if __name__ == "__main__":
    main()

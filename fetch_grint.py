"""Fetch historical rounds from TheGrint into the shared Parquet tables.

Usage:
    uv run python fetch_grint.py                     # import rounds older than earliest Garmin round
    uv run python fetch_grint.py --cutoff 2021-08-14
"""

import argparse
import getpass
import json
import re
import sys
import time
from pathlib import Path

import polars as pl
import requests
from bs4 import BeautifulSoup

from fetch_garmin import HOLES_SCHEMA, ROUNDS_SCHEMA, load_or_empty

BASE = "https://thegrint.com"
SESSION_FILE = Path("~/.thegrint_session.json").expanduser()
DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DIR = DATA_DIR / "raw" / "grint"
COURSES_CACHE = DATA_DIR / "courses.json"
ROUNDS_PATH = DATA_DIR / "rounds.parquet"

FETCH_DELAY_S = 1.0
HANDICAP_COMPANY_ID = "7"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _save_session(session: requests.Session) -> None:
    SESSION_FILE.write_text(json.dumps(requests.utils.dict_from_cookiejar(session.cookies)))


def _load_session() -> requests.Session | None:
    if not SESSION_FILE.exists():
        return None
    session = requests.Session()
    session.headers["User-Agent"] = UA
    session.cookies.update(requests.utils.cookiejar_from_dict(json.loads(SESSION_FILE.read_text())))
    return session


def _is_logged_in(session: requests.Session) -> bool:
    r = session.get(f"{BASE}/score", params={"type_score": "0"}, timeout=30)
    return r.status_code == 200 and "scoresArray" in r.text


def login(session: requests.Session) -> None:
    email = input("TheGrint email/username: ").strip()
    password = getpass.getpass("TheGrint password: ")
    r = session.post(
        f"{BASE}/login",
        data={
            "username": email,
            "password": password,
            "redirect": "",
            "submit-form-login": "",
        },
        timeout=30,
    )
    time.sleep(FETCH_DELAY_S)
    if not _is_logged_in(session):
        sys.exit("TheGrint login failed — check credentials (and that /login didn't change)")
    _save_session(session)
    print(f"Login OK — cookies cached at {SESSION_FILE}")


def get_session() -> requests.Session:
    session = _load_session()
    if session and _is_logged_in(session):
        return session
    session = session or requests.Session()
    session.headers["User-Agent"] = UA
    login(session)
    return session


def _parse_scores_array(html: str) -> list[dict]:
    rounds = []
    for block in html.split("scoresArray.unshift"):
        rid = re.search(r"scoreId:\s*'(\d+)'", block)
        if not rid:
            continue

        def field(name: str) -> str:
            m = re.search(rf"{name}:\s*'((?:[^']|\\')*)'", block)
            return m.group(1).replace("\\'", "'") if m else ""

        score_m = re.search(r"score:\s*(\d+)", block)
        rounds.append(
            {
                "id": int(rid.group(1)),
                "score_type": re.search(r"scoreType:\s*'(\d+)'", block).group(1)
                if re.search(r"scoreType:\s*'(\d+)'", block)
                else "18",
                "short": field("short"),
                "date": field("date"),
                "course_name": field("courseName"),
                "score": int(score_m.group(1)) if score_m else None,
                "tees": field("tees"),
                "practice": field("practice") or "0",
            }
        )
    return rounds


def list_rounds(session: requests.Session) -> list[dict]:
    """Enumerate all rounds from page 1 + listMoreScores waves."""
    found: dict[int, dict] = {}

    def absorb(html: str) -> None:
        for rnd in _parse_scores_array(html):
            found.setdefault(rnd["id"], rnd)

    first = session.get(
        f"{BASE}/score",
        params={"type_score": "0", "handicap_company_id": HANDICAP_COMPANY_ID},
        timeout=30,
    )
    absorb(first.text)

    wave = 1
    while True:
        r = session.post(
            f"{BASE}/score/listMoreScores",
            data={
                "wave": wave,
                "wave18": len(found),
                "wave9": len(found),
                "userId": "67334",
                "courseId": "",
                "typeScore": "0",
                "handicap_company_id": HANDICAP_COMPANY_ID,
            },
            timeout=30,
        )
        before = len(found)
        absorb(r.text)
        if not r.text.strip() or len(found) == before:
            break
        wave += 1
        time.sleep(FETCH_DELAY_S)

    rounds = sorted(found.values(), key=lambda x: x["date"])
    print(f"{len(rounds)} total Grint rounds found")
    return rounds


def _selected(soup: BeautifulSoup, select_id: str) -> str:
    opt = soup.select_one(f"#{select_id} option[selected]")
    return opt["value"].strip() if opt else ""


def parse_scorecard(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    def hidden(selector: str) -> str:
        el = soup.select_one(selector)
        return el.get("value", "").strip() if el else ""

    scores, putts, penalties, fairways = {}, {}, {}, {}
    for inp in soup.select("input[data-hole]"):
        name = inp.get("name", "")
        hole = int(inp["data-hole"])
        val = inp.get("value", "").strip()
        if name.startswith("scH") and val:
            scores[hole] = int(val)
        elif name.startswith("ptH") and val:
            putts[hole] = int(val)
        elif name.startswith("pH") and val:
            penalties[hole] = val
        elif name.startswith("fH") and val:
            fairways[hole] = val

    return {
        "id": int(hidden("#score-id") or 0),
        "user_id": hidden("#userid1"),
        "date": f"{_selected(soup, 'year')}-{_selected(soup, 'month')}-{_selected(soup, 'date')}",
        "course_name": hidden("#cname"),
        "course_id": hidden("#cid"),
        "tee": hidden(".tees-db"),
        "scores": scores,
        "putts": putts,
        "penalties": penalties,
        "fairways": fairways,
    }


PENALTY_CODES = {"w", "o", "d"}


def fetch_scorecard(session: requests.Session, rnd: dict) -> dict:
    url = f"{BASE}/score/edit_score/{rnd['id']}"
    if rnd.get("score_type") == "9":
        url += "/9"
    r = session.get(url, timeout=30)
    time.sleep(FETCH_DELAY_S)
    card = parse_scorecard(r.text)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{rnd['id']}.html").write_text(r.text)
    return card


def load_course_cache() -> dict:
    return json.loads(COURSES_CACHE.read_text()) if COURSES_CACHE.exists() else {}


def save_course_cache(cache: dict) -> None:
    COURSES_CACHE.write_text(json.dumps(cache, indent=1))


def resolve_pars(session: requests.Session, card: dict, holes9: bool) -> dict:
    """Per-hole pars (+ any tee metadata) via the scorecard's own AJAX endpoint."""
    cache = load_course_cache()
    key = f"{card['course_id']}:{card['tee'].lower()}:{'9' if holes9 else '18'}"
    if key not in cache:
        r = session.post(
            f"{BASE}/ajax/get_course_data/0/0/0",
            data={
                "course_id": card["course_id"],
                "tee": card["tee"].lower(),
                "user_id": card["user_id"],
                "round": "9" if holes9 else "18",
                "score_id": str(card["id"]),
                "handicap_company_id": HANDICAP_COMPANY_ID,
            },
            timeout=30,
        )
        try:
            data = r.json()
        except ValueError:
            data = {}
        pars_html = data.get("par", "") or ""
        entry = {
            "pars": [int(x) for x in re.findall(r">\s*(\d+)\s*<", pars_html)],
            "course_par": data.get("coursePar"),
        }
        for meta in ("slope", "rating", "statistical_par", "yardage_total"):
            if meta in data:
                entry[meta] = data[meta]
        cache[key] = entry
        save_course_cache(cache)
        time.sleep(FETCH_DELAY_S)
    return cache[key]


def build_rows(card: dict, tee_data: dict, holes9: bool) -> tuple[dict, list[dict]]:
    holes = sorted(card["scores"])
    pars_list = tee_data.get("pars") or []
    # For 9-hole back nines the API returns front-nine ordering; map by position.
    pars_by_hole = {}
    if len(pars_list) == len(holes):
        pars_by_hole = dict(zip(holes, pars_list))
    elif len(pars_list) == 18 and holes9:
        pars_by_hole = {h: pars_list[h - 1] for h in holes}

    round_row = {
        "round_id": card["id"],
        "source": "grint",
        "date": card["date"],
        "course_name": card["course_name"] or "Unknown course",
        "score": sum(card["scores"].values()) or None,
        "to_par": (
            sum(card["scores"].values()) - sum(pars_by_hole.values())
            if len(pars_by_hole) == len(holes)
            else None
        ),
        "holes_played": len(holes),
        "putts": sum(card["putts"].values()) or None,
        "tee_box": card["tee"],
        "slope": tee_data.get("slope"),
        "rating": tee_data.get("rating") or tee_data.get("statistical_par"),
        "walk_distance_m": None,
    }

    hole_rows = []
    for h in holes:
        code = card["penalties"].get(h, "")
        hole_rows.append(
            {
                "round_id": card["id"],
                "source": "grint",
                "hole_number": h,
                "par": pars_by_hole.get(h),
                "score": card["scores"][h],
                "putts": card["putts"].get(h),
                "penalties": sum(1 for c in code.lower() if c in PENALTY_CODES),
                "fairway": card["fairways"].get(h),
            }
        )
    return round_row, hole_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", metavar="YYYY-MM-DD", help="only import rounds before this date")
    args = parser.parse_args()

    session = get_session()

    stored_rounds = load_or_empty("rounds.parquet", ROUNDS_SCHEMA)
    holes_df = load_or_empty("holes.parquet", HOLES_SCHEMA)
    grint_ids = set(
        stored_rounds.filter(pl.col("source") == "grint")["round_id"].to_list()
    ) if stored_rounds.height else set()

    cutoff = args.cutoff
    if not cutoff:
        garmin_dates = stored_rounds.filter(pl.col("source") == "garmin")["date"]
        cutoff = garmin_dates.min() if garmin_dates.len() else "9999-12-31"
    print(f"Cutoff: importing rounds before {cutoff}")

    candidates = [
        r
        for r in list_rounds(session)
        if r["short"] != "2"  # skip combined scores (double-counted 9s)
        and r["practice"] == "0"
        and len(r["date"].split("/")) == 3
        and "-".join(reversed(r["date"].split("/"))) < cutoff
        and r["id"] not in grint_ids
    ]
    candidates.sort(key=lambda r: r["date"])
    print(f"{len(candidates)} new rounds to import")

    failures = []
    new_rounds, new_holes = [], []
    for i, rnd in enumerate(candidates, 1):
        label = f"{rnd['date']} {rnd['course_name']} ({rnd['id']})"
        try:
            card = fetch_scorecard(session, rnd)
            holes9 = len(card["scores"]) <= 9
            tee_data = resolve_pars(session, card, holes9)
            round_row, hole_rows = build_rows(card, tee_data, holes9)
            new_rounds.append(round_row)
            new_holes.extend(hole_rows)
            pars = tee_data.get("pars") or []
            print(f"[{i}/{len(candidates)}] {label}: {len(hole_rows)} holes, par {sum(pars) if pars else '?'}")
        except Exception as e:
            failures.append((label, e))
            print(f"  FAILED {label}: {e}")

    if new_rounds:
        all_rounds = pl.concat(
            [stored_rounds, pl.DataFrame(new_rounds, schema=ROUNDS_SCHEMA)], how="vertical_relaxed"
        )
        all_holes = pl.concat(
            [holes_df, pl.DataFrame(new_holes, schema=HOLES_SCHEMA)], how="vertical_relaxed"
        )
        all_rounds.sort(["date", "source"]).write_parquet(ROUNDS_PATH)
        all_holes.sort(["round_id", "hole_number"]).write_parquet(DATA_DIR / "holes.parquet")
    else:
        all_rounds = stored_rounds

    print(f"\nDone: rounds={all_rounds.height} total, +{len(new_rounds)} grint, holes +{len(new_holes)}")
    if failures:
        print("\nFailures:")
        for label, e in failures:
            print(f"  {label}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Fetch rounds from Hole19 into the shared Parquet tables.

Usage:
    uv run python fetch_hole19.py                     # import all rounds not yet stored
    uv run python fetch_hole19.py --full              # re-fetch all Hole19 rounds
    uv run python fetch_hole19.py --since 2024-01-01
    uv run python fetch_hole19.py --debug             # dump raw pages for parser debugging
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

import credentials
from fetch_garmin import HOLES_SCHEMA, ROUNDS_SCHEMA, load_or_empty

BASE = "https://www.hole19golf.com"
SESSION_FILE = Path("~/.hole19_session.json").expanduser()
DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DIR = DATA_DIR / "raw" / "hole19"

FETCH_DELAY_S = 1.0

# Set by main() when --headless is passed; the dashboard runs syncs headlessly.
HEADLESS = False

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

HOLE19_FAIRWAY_CODES = {"center", "target", "left", "right"}


def _save_session(session: requests.Session) -> None:
    SESSION_FILE.write_text(json.dumps(requests.utils.dict_from_cookiejar(session.cookies)))


def _load_session() -> requests.Session | None:
    if not SESSION_FILE.exists():
        return None
    session = requests.Session()
    session.headers["User-Agent"] = UA
    session.cookies.update(requests.utils.cookiejar_from_dict(json.loads(SESSION_FILE.read_text())))
    return session


def _is_logged_in(session: requests.Session, debug: bool = False) -> bool:
    r = session.get(f"{BASE}/performance/rounds", timeout=30, allow_redirects=False)
    if debug:
        print(f"debug: /performance/rounds status={r.status_code} location={r.headers.get('Location')!r}")
    return r.status_code == 200


def _csrf_token(session: requests.Session, html: str | None = None) -> str | None:
    if html is None:
        html = session.get(f"{BASE}/users/sign_in", timeout=30).text
    m = re.search(r'name="authenticity_token"\s+value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else None


def _post_login(
    session: requests.Session, email: str, password: str, debug: bool = False
) -> bool:
    r0 = session.get(f"{BASE}/users/sign_in", timeout=30)
    token = _csrf_token(session, r0.text)
    if not token:
        if debug:
            print("debug: could not find authenticity_token on sign-in page")
        return False

    r = session.post(
        f"{BASE}/users/sign_in",
        data={
            "authenticity_token": token,
            "user[email]": email,
            "user[password]": password,
        },
        timeout=30,
    )
    time.sleep(FETCH_DELAY_S)

    if debug:
        print(
            f"debug: login POST status={r.status_code} url={r.url!r}\n"
            f"debug: jar after POST={[(c.name, c.domain) for c in session.cookies]}"
        )
    # Devise re-renders the sign-in form (with an error flash) on bad credentials;
    # success redirects away from /users/sign_in.
    return "/users/sign_in" not in r.url


def login(session: requests.Session, debug: bool = False) -> None:
    saved = credentials.get_login("hole19")
    if saved:
        email, password = saved
        if _post_login(session, email, password, debug=debug):
            _save_session(session)
            print("Login OK using stored credentials")
            return
        print("Stored credentials rejected, prompting...")

    if HEADLESS:
        sys.exit("No Hole19 credentials stored — sign in on the Accounts page first")
    email = input("Hole19 email: ").strip()
    password = getpass.getpass("Hole19 password: ")
    if not _post_login(session, email, password, debug=debug):
        sys.exit("Hole19 login rejected — check email/password")
    _save_session(session)
    if input(f"Save these credentials to {credentials.LOGIN_FILE}? (y/n) ").strip().lower() == "y":
        credentials.save_login("hole19", email, password)
        print(f"Credentials saved to {credentials.LOGIN_FILE}")
    if not _is_logged_in(session, debug=debug):
        sys.exit("Login POST seemed to succeed but /performance/rounds still looks logged-out")
    print(f"Login OK — cookies cached at {SESSION_FILE}")


def get_session(debug: bool = False) -> requests.Session:
    session = _load_session()
    if session and _is_logged_in(session, debug=debug):
        return session
    session = session or requests.Session()
    session.headers["User-Agent"] = UA
    login(session, debug=debug)
    return session


def _embedded_props(soup: BeautifulSoup) -> list[tuple[str, dict]]:
    """All (component-name, props) pairs from React-on-Rails JSON script tags."""
    out = []
    for script in soup.find_all("script", {"type": "application/json"}):
        try:
            props = json.loads(script.string or "")
        except ValueError:
            continue
        out.append((script.get("data-component-name", ""), props))
    return out


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _looks_like_round(d: dict) -> bool:
    return (
        isinstance(d.get("id"), (int, str))
        and any(k in d for k in ("played_date", "played_at", "date"))
        and ("course_name" in d or "course" in d)
    )


def _round_id_of(d: dict) -> int | None:
    try:
        rid = int(d["id"])
    except (KeyError, TypeError, ValueError):
        return None
    date = str(d.get("played_date") or d.get("played_at") or d.get("date") or "")
    if not date[:2].isdigit():  # require something date-like
        return None
    return rid


def parse_rounds_index(html: str) -> tuple[list[dict], str | None]:
    """Extract round summaries from the rounds-list page.

    Returns (rounds, next_page_url). The page structure is only known from a
    logged-in session; this walks every embedded JSON props blob looking for
    round-like objects, and detects pagination from ?page= links.
    """
    soup = BeautifulSoup(html, "lxml")

    found: dict[int, dict] = {}
    for _, props in _embedded_props(soup):
        for d in _walk(props):
            rid = _round_id_of(d) if _looks_like_round(d) else None
            if rid is not None and rid not in found:
                found[rid] = {
                    "id": rid,
                    "date": str(
                        d.get("played_date") or d.get("played_at") or d.get("date")
                    )[:10],
                    "course_name": str(d.get("course_name") or ""),
                }

    next_page = None
    for a in soup.select("a[rel=next][href]"):
        next_page = a["href"]
        break
    if not next_page:
        for a in soup.select("a[href*='page=']"):
            href = a["href"]
            if "rel=next" in href or "next" in (a.get_text() or "").lower():
                next_page = href
                break
    if next_page and next_page.startswith("/"):
        next_page = BASE + next_page
    return sorted(found.values(), key=lambda x: x["date"]), next_page


def list_rounds(session: requests.Session, debug: bool = False) -> list[dict]:
    """Enumerate all rounds by following the index pagination."""
    found: dict[int, dict] = {}
    url = f"{BASE}/performance/rounds"
    first_page_html = None

    for page in range(1, 101):  # hard cap as a runaway guard
        r = session.get(url, timeout=30)
        time.sleep(FETCH_DELAY_S)
        if r.status_code != 200:
            sys.exit(f"Rounds list request failed: HTTP {r.status_code} at {url}")
        if first_page_html is None:
            first_page_html = r.text

        rounds, next_page = parse_rounds_index(r.text)
        if debug:
            print(f"debug: page {page} ({url}): {len(rounds)} rounds parsed, next={next_page}")
        before = len(found)
        for rnd in rounds:
            found.setdefault(rnd["id"], rnd)

        if not next_page or len(found) == before:
            break
        url = next_page

    if not found:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / "index.html").write_text(first_page_html or "")
        msg = "No rounds found on the rounds-list page"
        if debug:
            soup = BeautifulSoup(first_page_html or "", "lxml")
            names = [n for n, _ in _embedded_props(soup)]
            msg += f" — components seen: {names}; HTML saved to {RAW_DIR / 'index.html'}"
        else:
            msg += " — rerun with --debug to dump the page for inspection"
        sys.exit(msg)

    rounds = sorted(found.values(), key=lambda x: x["date"])
    print(f"{len(rounds)} total Hole19 rounds found")
    return rounds


def parse_scorecard(html: str) -> dict | None:
    """Extract scorecard data from a round-detail page's MyScorecard props."""
    soup = BeautifulSoup(html, "lxml")
    for name, props in _embedded_props(soup):
        data = props.get("data") if isinstance(props, dict) else None
        if not isinstance(data, dict):
            continue
        holes = data.get("holes")
        if not holes or not all(isinstance(h, dict) for h in holes):
            continue
        if not any(("hole_tee" in h or "hole_score" in h) for h in holes):
            continue

        def hole_num(h: dict) -> int | None:
            for key in ("sequence", "hole_number", "number"):
                v = h.get(key)
                if v is not None:
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        pass
            return None

        holes_parsed = []
        for h in holes:
            tee = h.get("hole_tee") or {}
            sc = h.get("hole_score") or {}
            num = hole_num(h)
            if num is None:
                continue
            strokes = sc.get("total_of_strokes")
            putts = sc.get("total_of_putts")
            fairway = sc.get("fairway_hit")
            yardage = tee.get("yardage") or tee.get("meters") or tee.get("distance")
            penalties = sc.get("penalties") or sc.get("total_of_penalties")
            par = tee.get("par")
            holes_parsed.append(
                {
                    "hole_number": num,
                    "par": int(par) if par is not None else None,
                    "score": int(strokes) if strokes is not None else None,
                    "putts": int(putts) if putts is not None else None,
                    "penalties": int(penalties) if penalties is not None else None,
                    "fairway": fairway if fairway in HOLE19_FAIRWAY_CODES else None,
                    "yardage": int(yardage) if yardage is not None else None,
                }
            )

        played = str(data.get("played_date") or "")
        first_tee = (holes[0].get("hole_tee") or {}) if holes else {}
        tee_box = str(
            first_tee.get("tee_name")
            or first_tee.get("name")
            or data.get("tee_name")
            or data.get("tee_color")
            or ""
        )
        slope = rating = walk_distance_m = None
        for key in ("slope", "tee_slope"):
            if first_tee.get(key) or data.get(key):
                slope = float(first_tee.get(key) or data.get(key))
                break
        for key in ("rating", "course_rating", "tee_rating"):
            if first_tee.get(key) or data.get(key):
                rating = float(first_tee.get(key) or data.get(key))
                break
        dist = data.get("distance_meters") or data.get("distance_in_meters")
        if dist:
            walk_distance_m = float(dist)

        return {
            "id": int(data.get("id") or _round_id_of(data)),
            "date": played[:10],
            "course_name": str(data.get("course_name") or "Unknown course"),
            "holes": sorted(holes_parsed, key=lambda x: x["hole_number"]),
            "tee_box": tee_box,
            "slope": slope,
            "rating": rating,
            "walk_distance_m": walk_distance_m,
        }
    return None


def fetch_round(session: requests.Session, rnd: dict, debug: bool = False) -> dict:
    url = f"{BASE}/performance/rounds/{rnd['id']}"
    r = session.get(url, timeout=30)
    time.sleep(FETCH_DELAY_S)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} fetching round detail")
    card = parse_scorecard(r.text)
    if card is None:
        if debug:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            path = RAW_DIR / f"{rnd['id']}.html"
            path.write_text(r.text)
            raise RuntimeError(f"no MyScorecard props found (HTML saved to {path})")
        raise RuntimeError("no MyScorecard props found — rerun with --debug to save the HTML")
    if card["id"] != rnd["id"]:
        raise RuntimeError(f"detail page id mismatch ({card['id']} != {rnd['id']})")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{rnd['id']}.html").write_text(r.text)
    return card


def build_rows(card: dict) -> tuple[dict, list[dict]]:
    holes = [h for h in card["holes"] if h["score"] is not None]
    scored_holes = [h for h in holes if h["par"] is not None]

    round_row = {
        "round_id": card["id"],
        "source": "hole19",
        "date": card["date"],
        "course_name": card["course_name"],
        "score": sum(h["score"] for h in holes) or None,
        "to_par": (
            sum(h["score"] for h in scored_holes) - sum(h["par"] for h in scored_holes)
            if len(scored_holes) == len(card["holes"])
            and len(scored_holes) > 0
            else None
        ),
        "holes_played": len(card["holes"]),
        "putts": sum(h["putts"] for h in holes if h["putts"] is not None) or None,
        "tee_box": card["tee_box"],
        "slope": card["slope"],
        "rating": card["rating"],
        "walk_distance_m": card["walk_distance_m"],
    }

    hole_rows = [
        {
            "round_id": card["id"],
            "source": "hole19",
            "hole_number": h["hole_number"],
            "par": h["par"],
            "score": h["score"],
            "putts": h["putts"],
            "penalties": h["penalties"],
            "fairway": h["fairway"],
            "yardage": h["yardage"],
            "pin_lat": None,
            "pin_lon": None,
        }
        for h in holes
    ]
    return round_row, hole_rows


def main() -> None:
    global HEADLESS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="only import rounds on/after this date")
    parser.add_argument("--cutoff", metavar="YYYY-MM-DD", help="only import rounds before this date")
    parser.add_argument("--full", action="store_true", help="re-fetch all Hole19 rounds, replacing existing ones")
    parser.add_argument("--debug", action="store_true", help="dump raw pages and login diagnostics")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="never prompt interactively; fail with a clear error if credentials are missing",
    )
    args = parser.parse_args()
    HEADLESS = args.headless

    session = get_session(debug=args.debug)

    stored_rounds = load_or_empty("rounds.parquet", ROUNDS_SCHEMA)
    holes_df = load_or_empty("holes.parquet", HOLES_SCHEMA)
    if args.full:
        stored_rounds = stored_rounds.filter(pl.col("source") != "hole19")
        holes_df = holes_df.filter(pl.col("source") != "hole19")
        existing_ids: set[int] = set()
    else:
        existing_ids = set(
            stored_rounds.filter(pl.col("source") == "hole19")["round_id"].to_list()
        ) if stored_rounds.height else set()

    candidates = [
        r
        for r in list_rounds(session, debug=args.debug)
        if (not args.since or r["date"] >= args.since)
        and (not args.cutoff or r["date"] < args.cutoff)
        and r["id"] not in existing_ids
    ]
    candidates.sort(key=lambda r: r["date"])
    print(f"{len(candidates)} new rounds to import")

    failures = []
    new_rounds, new_holes = [], []
    for i, rnd in enumerate(candidates, 1):
        label = f"{rnd['date']} {rnd['course_name']} ({rnd['id']})"
        try:
            card = fetch_round(session, rnd, debug=args.debug)
            round_row, hole_rows = build_rows(card)
            new_rounds.append(round_row)
            new_holes.extend(hole_rows)
            print(f"[{i}/{len(candidates)}] {label}: {len(hole_rows)} holes, score {round_row['score']}")
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
        all_rounds.sort(["date", "source"]).write_parquet(DATA_DIR / "rounds.parquet")
        all_holes.sort(["round_id", "hole_number"]).write_parquet(DATA_DIR / "holes.parquet")
    else:
        all_rounds = stored_rounds

    print(f"\nDone: rounds={all_rounds.height} total, +{len(new_rounds)} hole19, holes +{len(new_holes)}")
    if failures:
        print("\nFailures:")
        for label, e in failures:
            print(f"  {label}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

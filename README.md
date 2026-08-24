# Bogeyboard

Personal golf dashboard: scrapes your own round history from Garmin Connect (Approach watch scorecards + shot data) and TheGrint (pre-Garmin history) into local Parquet tables, displayed in a Streamlit app.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Data sources

### Garmin Connect — `fetch_garmin.py`

Downloads all golf rounds from your Garmin account using the unofficial `garminconnect` API. Works with auto shot detection (Approach watches) and CT10 sensors.

```bash
# Incremental sync (default): fetches only rounds newer than what's stored
uv run python fetch_garmin.py

# Re-fetch everything from scratch
uv run python fetch_garmin.py --full

# Only fetch rounds played after a date
uv run python fetch_garmin.py --since 2026-06-01
```

First run prompts for email/password (and MFA code if enabled). Tokens are cached at `~/.garminconnect` and valid for roughly a year — subsequent runs need no login. If a run fails partway (e.g. rate limited), just rerun it; completed rounds are skipped and failed ones retried.

### TheGrint — `fetch_grint.py`

Scrapes round history from thegrint.com to fill in pre-Garmin rounds. Imports rounds **before the earliest Garmin round** by default so overlapping rounds aren't double-counted. Combined scores and practice rounds are skipped automatically.

```bash
# Import everything before your earliest Garmin round
uv run python fetch_grint.py

# Or with an explicit cutoff date (YYYY-MM-DD)
uv run python fetch_grint.py --cutoff 2021-08-14
```

First run prompts for TheGrint credentials; session cookies are cached at `~/.thegrint_session.json`. Reruns skip rounds already imported.

> Both scrapers use unofficial/private interfaces and may break if the sites change. All requests are your own account data, rate-limited with small delays between requests.

## Data output

Everything lands in `data/`:

| File | Contents |
| --- | --- |
| `rounds.parquet` | One row per round: id, source (`garmin`/`grint`), date, course, score, to_par, tee box, slope/rating |
| `holes.parquet` | Per-hole rows: score, putts, penalties, fairway code (Grint only) |
| `shots.parquet` | Shot-by-shot GPS data (Garmin only): club, lie, start/end coordinates, distance, shot type/source |
| `raw/*.json`, `raw/grint/*.html` | Unparsed API responses per round, kept for debugging |
| `courses.json` | Cached course/tee par data from TheGrint |

Delete any `.parquet` file and rerun the corresponding scraper (with `--full` for Garmin) to rebuild it.

## Dashboard

```bash
uv run streamlit run app.py
```

Multi-page Streamlit app fed by both sources (Grint rounds appear as historical context alongside Garmin data):

| Page | Contents |
| --- | --- |
| Overview | Handicap index, avg score, FIR%/GIR% KPIs; rounds bar chart with best-8-of-last-20 differentials highlighted |
| Scoring | Average score by hole number, hole par, and yardage bucket |
| Putting | Putt-count distribution donut, putts by GIR, last-20-rounds trend |
| Ball striking | FIR%, GIR%, and scrambling trends over time |
| Clubs | Average distance per club from shot tracking |
| Data | Raw rounds/holes/shots tables with round filters |

Derived stats (handicap differentials, FIR, GIR, scrambling) are computed in `stats.py` from the Parquet tables — FIR/GIR come from decoded TheGrint fairway codes or exact Garmin shot lies depending on the source.


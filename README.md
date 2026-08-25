# Bogeyboard

Personal golf dashboard: downloads your round history from Garmin Connect (Approach watch scorecards + shot data) and TheGrint (older rounds) into local files, then shows them in a dashboard in your web browser.

No programming knowledge needed — set it up once, then just double-click to open your dashboard and run two commands when you want to import new scores.

## Setup — Mac

One-time setup, about 10 minutes:

1. **Install Python** — go to [python.org/downloads](https://www.python.org/downloads/), download the latest version for macOS (**3.12 or newer is required**), and run the installer. Accept all defaults.
2. **Get the Bogeyboard folder** onto your computer (e.g. copy it into `Documents`).
3. **Open Terminal** (press `Cmd + Space`, type `Terminal`, press Enter).
4. In Terminal, go to the folder and make the launcher executable. Type these two lines, replacing the folder path with where you put it, pressing Enter after each:
   ```bash
   cd ~/Documents/bogeyboard
   chmod +x start_mac.command
   ```
5. **Double-click `start_mac.command`** in Finder. The first time, it installs everything it needs (a few minutes). After that it starts instantly, and your browser opens the dashboard at `http://localhost:8501`.

From now on: **double-click `start_mac.command` whenever you want to see your stats.** Close the Terminal window when you're done.

## Setup — Windows

One-time setup, about 10 minutes:

1. **Install Python** — go to [python.org/downloads](https://www.python.org/downloads/), download the latest version for Windows (**3.12 or newer is required**), and run the installer. **Important:** tick the box that says "Add Python to PATH" on the first installer screen.
2. **Get the Bogeyboard folder** onto your computer (e.g. copy it into `Documents`).
3. Open that folder and **double-click `start_windows.bat`**.
   - If Windows SmartScreen shows a warning, click "More info" → "Run anyway".
   - The first time, it installs everything it needs (a few minutes).
   - Your browser opens the dashboard at `http://localhost:8501`.

From now on: **double-click `start_windows.bat` whenever you want to see your stats.**

## Connecting your accounts

### Garmin Connect

1. Make sure the dashboard is closed, then open Terminal (Mac) or Command Prompt (Windows) **in the Bogeyboard folder**:
   - Mac: in Finder, right-click the Bogeyboard folder → "New Terminal at Folder" (or use `cd` as above)
   - Windows: click the address bar in File Explorer, type `cmd`, press Enter
2. Run:

   ```
   python fetch_garmin.py
   ```

   Mac users may need `python3 fetch_garmin.py` instead.
3. Enter your Garmin email and password when asked (and an MFA code if you use one).

The first sync downloads your entire shot history; later runs only fetch new rounds. When a login expires (~once a year), the app will offer to save your credentials so future logins are automatic.

### TheGrint

Same steps, but run:

```
python fetch_grint.py
```

This imports rounds from before you had your Garmin watch. Rounds you tracked in both places are handled automatically — no duplicates.

### Hole19

Same steps, but run:

```
python fetch_hole19.py
```

This imports all rounds from your Hole19 account (via the hole19golf.com website). By default every Hole19 round not yet stored is imported; if you also track rounds in Garmin or TheGrint, duplicates are not removed automatically.

## Credentials (optional)

Both apps save their login sessions after you sign in once. If you'd rather never be prompted at all — even when sessions expire — store your credentials in a file called `.bogeyboard_login.json` in your home folder (`~` on Mac, `C:\Users\YourName` on Windows):

```json
{
  "logins": {
    "garmin": {
      "email": "you@example.com",
      "password": "your-garmin-password"
    },
    "grint": {
      "email": "you@example.com",
      "password": "your-grint-password"
    },
    "hole19": {
      "email": "you@example.com",
      "password": "your-hole19-password"
    }
  }
}
```

Create it with TextEdit (Mac) or Notepad (Windows); make sure it's saved as plain text with exactly that name starting with a dot. Omit any service you don't use. Passwords are stored in plain text — keep the file private. Environment variables `GARMIN_EMAIL` / `GARMIN_PASSWORD`, `GRINT_EMAIL` / `GRINT_PASSWORD` and `HOLE19_EMAIL` / `HOLE19_PASSWORD` override the file if you prefer that route.

> Both scrapers talk to unofficial/private interfaces and may break if the websites change. All requests are your own account data, rate-limited with small delays between requests.

## Data output

Everything lands in the `data` folder inside Bogeyboard:

| File | Contents |
| --- | --- |
| `rounds.parquet` | One row per round: id, source (`garmin`/`grint`/`hole19`), date, course, score, to_par, tee box, slope/rating |
| `holes.parquet` | Per-hole rows: score, putts, penalties, fairway code (Grint: numeric code, Hole19: `center`/`target`/`left`/`right`), pin position (Garmin only) |
| `shots.parquet` | Shot-by-shot GPS data (Garmin only): club, lie, start/end coordinates, distance, shot type/source |
| `raw/*.json`, `raw/grint/*.html`, `raw/hole19/*.html` | Unparsed responses per round, kept for debugging |
| `courses.json` | Cached course/tee data from TheGrint |

## Refreshing your stats

After playing a round:

1. Double-click the launcher so the dashboard is running
2. In Terminal/Command Prompt (in the Bogeyboard folder):
   ```
   python fetch_garmin.py
   python fetch_grint.py
   python fetch_hole19.py
   ```
3. Refresh your browser tab

To force a complete re-download of one source:

```
python fetch_garmin.py --full
python fetch_grint.py --full
python fetch_hole19.py --full
```

Other options: `--since YYYY-MM-DD` and `--cutoff YYYY-MM-DD` limit what gets fetched; `--debug` prints login diagnostics.

## Dashboard pages

| Page | Contents |
| --- | --- |
| Overview | Handicap index, avg score, FIR%/GIR% KPIs; rounds bar chart with best-8-of-last-20 differentials highlighted |
| Scoring | Average score by hole number, hole par, and yardage bucket |
| Putting | Putt-count distribution donut, putts by GIR, putts-per-round bars |
| Ball striking | Driving misses (left/right/hit/other) and approach outcomes as 100% stacked bars, plus scrambling trend |
| Clubs | Distance distribution curves per club with outlier trimming, average distances |
| Data | Raw rounds/holes/shots tables with round filters |

Sidebar filters (course, year, round window, handicap rounds) apply across the chart pages; your club selection and trim preferences are remembered between sessions.

Derived stats (handicap differentials, FIR, GIR, scrambling) are computed in `stats.py` from the data files.

---

## Developer notes

This is a plain Python project. Install dependencies however you like — e.g. `pip install -r requirements.txt`, or with [uv](https://docs.astral.sh/uv/) via `uv sync` using the bundled `pyproject.toml`. Requires Python 3.12+ (the garminconnect dependency enforces this).

Run scrapers with `uv run python <script>` or from an activated environment. Useful extras: `fetch_grint.py --debug` prints Grint login diagnostics; `fetch_hole19.py --debug` prints login/pagination diagnostics and saves unparseable pages under `data/raw/hole19/`; raw API responses are kept under `data/raw/` for debugging parser issues.

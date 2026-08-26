"""Central app layout: all state lives under ~/.bogeyboard/ so it survives
re-downloading or updating the code folder.

    ~/.bogeyboard/
    ├── config.json      user settings (was ~/.bogeyboard.json)
    ├── login.json       saved passwords (was ~/.bogeyboard_login.json)
    ├── sessions/        login sessions / token caches per service
    └── data/            parquet tables, raw responses, sync logs & state
"""

import shutil
from pathlib import Path

APP_DIR = Path.home() / ".bogeyboard"
DATA_DIR = APP_DIR / "data"
SESSION_DIR = APP_DIR / "sessions"
LOGIN_FILE = APP_DIR / "login.json"
SETTINGS_FILE = APP_DIR / "config.json"

REPO_DIR = Path(__file__).resolve().parent
LEGACY_DATA_DIR = REPO_DIR / "data"

GARMIN_TOKEN_STORE = SESSION_DIR / "garminconnect"
GRINT_SESSION_FILE = SESSION_DIR / "grint.json"
HOLE19_SESSION_FILE = SESSION_DIR / "hole19.json"

# (old location, new location) — moved on first run when the destination is empty.
_MIGRATIONS = [
    (Path("~/.bogeyboard_login.json").expanduser(), LOGIN_FILE),
    (Path("~/.bogeyboard.json").expanduser(), SETTINGS_FILE),
    (Path("~/.thegrint_session.json").expanduser(), GRINT_SESSION_FILE),
    (Path("~/.hole19_session.json").expanduser(), HOLE19_SESSION_FILE),
    (Path("~/.garminconnect").expanduser(), GARMIN_TOKEN_STORE),
]

_migrated = False


def ensure_layout() -> None:
    """Create the app directory and move legacy files into it. Safe to call often."""
    global _migrated
    if _migrated:
        return
    _migrated = True

    APP_DIR.mkdir(parents=True, exist_ok=True)
    for old, new in _MIGRATIONS:
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))

    if LEGACY_DATA_DIR.exists() and not DATA_DIR.exists():
        if any(LEGACY_DATA_DIR.iterdir()):
            shutil.move(str(LEGACY_DATA_DIR), str(DATA_DIR))
        else:
            LEGACY_DATA_DIR.rmdir()

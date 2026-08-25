"""Credential storage for scrapers.

Resolution order per service:
1. Environment variables (GARMIN_EMAIL/GARMIN_PASSWORD, GRINT_EMAIL/GRINT_PASSWORD)
2. ~/.bogeyboard_login.json  ->  {"logins": {"<service>": {"email": ..., "password": ...}}}
"""

import json
import os
import stat
from pathlib import Path

LOGIN_FILE = Path("~/.bogeyboard_login.json").expanduser()

ENV_KEYS = {
    "garmin": ("GARMIN_EMAIL", "GARMIN_PASSWORD"),
    "grint": ("GRINT_EMAIL", "GRINT_PASSWORD"),
}


def load_logins() -> dict:
    try:
        return json.loads(LOGIN_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_login(service: str) -> tuple[str, str] | None:
    email_var, password_var = ENV_KEYS[service]
    if os.environ.get(email_var) and os.environ.get(password_var):
        return os.environ[email_var], os.environ[password_var]
    saved = load_logins().get("logins", {}).get(service)
    if saved and saved.get("email") and saved.get("password"):
        return saved["email"], saved["password"]
    return None


def save_login(service: str, email: str, password: str) -> None:
    data = load_logins()
    data.setdefault("logins", {})[service] = {"email": email, "password": password}
    LOGIN_FILE.write_text(json.dumps(data, indent=1))
    LOGIN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)

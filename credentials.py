"""Credential storage for scrapers.

Resolution order per service:
1. Environment variables (GARMIN_EMAIL/GARMIN_PASSWORD, GRINT_EMAIL/GRINT_PASSWORD,
   HOLE19_EMAIL/HOLE19_PASSWORD)
2. ~/.bogeyboard/login.json  ->  {"logins": {"<service>": {"email": ..., "password": ...}}}
"""

import json
import os
import stat

import paths

ENV_KEYS = {
    "garmin": ("GARMIN_EMAIL", "GARMIN_PASSWORD"),
    "grint": ("GRINT_EMAIL", "GRINT_PASSWORD"),
    "hole19": ("HOLE19_EMAIL", "HOLE19_PASSWORD"),
}


def load_logins() -> dict:
    paths.ensure_layout()
    try:
        return json.loads(paths.LOGIN_FILE.read_text())
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
    paths.ensure_layout()
    data = load_logins()
    data.setdefault("logins", {})[service] = {"email": email, "password": password}
    paths.LOGIN_FILE.write_text(json.dumps(data, indent=1))
    paths.LOGIN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)

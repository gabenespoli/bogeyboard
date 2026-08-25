"""Persistent user settings stored at ~/.bogeyboard.json."""

import json
from pathlib import Path

SETTINGS_FILE = Path("~/.bogeyboard.json").expanduser()


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=1))


def update_setting(key: str, value) -> None:
    settings = load_settings()
    if settings.get(key) != value:
        settings[key] = value
        save_settings(settings)

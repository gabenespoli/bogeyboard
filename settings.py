"""Persistent user settings stored at ~/.bogeyboard/config.json."""

import json

import paths


def load_settings() -> dict:
    paths.ensure_layout()
    try:
        return json.loads(paths.SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    paths.ensure_layout()
    paths.SETTINGS_FILE.write_text(json.dumps(settings, indent=1))


def update_setting(key: str, value) -> None:
    settings = load_settings()
    if settings.get(key) != value:
        settings[key] = value
        save_settings(settings)

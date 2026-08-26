"""Self-updates for git clones of Bogeyboard, driven from the Accounts page.

A check runs `git fetch` + counts commits behind upstream. An update runs
detached (so it survives page navigation): `git pull --ff-only`, reinstalling
dependencies only when requirements.txt changed. Streamlit's file watcher picks
up the new code automatically afterwards.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import paths
import sync_manager

REPO_URL = "https://github.com/gabenespoli/bogeyboard"
ZIP_URL = f"{REPO_URL}/archive/refs/heads/main.zip"

STATE_FILE = paths.DATA_DIR / ".sync" / "update.json"
LOG_FILE = paths.DATA_DIR / "logs" / "update.log"

CHECK_TTL_S = 300


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1))


def is_git_copy() -> bool:
    return (paths.REPO_DIR / ".git").exists()


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(paths.REPO_DIR), capture_output=True, text=True, timeout=timeout
    )


def status(refresh: bool = False) -> dict:
    """Update availability; uses the cached check unless refresh=True or it went stale."""
    state = _read_state()
    pid = state.get("pid")
    if pid and not state.get("finished_at") and not sync_manager._pid_alive(pid):
        state["finished_at"] = state.get("started_at") or _now()
        state["interrupted"] = True
        _write_state(state)
    running = bool(pid) and not state.get("finished_at")

    result = {
        "supported": is_git_copy(),
        "running": running,
        "current_commit": state.get("current_commit"),
        "commits_behind": state.get("commits_behind"),
        "checked_at": state.get("checked_at"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
        "exit_code": state.get("exit_code"),
        "interrupted": state.get("interrupted", False),
    }
    if not result["supported"] or running:
        return result

    checked_at = state.get("checked_at")
    fresh = checked_at and abs(
        dt.datetime.now().timestamp() - dt.datetime.fromisoformat(checked_at).timestamp()
    ) <= CHECK_TTL_S
    if refresh or not fresh:
        _git("fetch", "origin", timeout=20)
        head = _git("rev-parse", "--short", "HEAD")
        behind = _git("rev-list", "--count", "HEAD..@{u}")
        state.update(
            current_commit=head.stdout.strip(),
            commits_behind=int(behind.stdout.strip()) if behind.returncode == 0 else None,
            checked_at=_now(),
        )
        _write_state(state)
        result.update(current_commit=state["current_commit"], commits_behind=state["commits_behind"], checked_at=state["checked_at"])
    return result


def start_update() -> str | None:
    """Launch the detached update process. Returns an error message or None."""
    if not is_git_copy():
        return "This copy has no git history — download a fresh ZIP instead"
    if any(sync_manager.status(s)["running"] for s in sync_manager.SERVICES):
        return "Wait for syncing to finish before updating"
    if status()["running"]:
        return "An update is already running"

    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--run"],
        cwd=str(paths.REPO_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Optimistic state so the UI flips to "updating" immediately; the child
    # (same pid) rewrites this when it starts working.
    _write_state({**_read_state(), "pid": proc.pid, "started_at": _now(), "finished_at": None, "exit_code": None})
    return None


def _requirements_hash() -> str:
    return hashlib.sha256((paths.REPO_DIR / "requirements.txt").read_bytes()).hexdigest()


def run_update() -> int:
    """Executed by the detached child process."""
    _write_state(
        {
            **_read_state(),
            "pid": os.getpid(),
            "started_at": _now(),
            "finished_at": None,
            "exit_code": None,
            "interrupted": False,
        }
    )

    req_before = _requirements_hash()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "ab") as log:
        log.write(f"\n=== update started {_now()} ===\n".encode())
        result = _git("pull", "--ff-only", timeout=600)
        log.write(result.stdout.encode())
        log.write(result.stderr.encode())

        code = result.returncode
        if code == 0 and _requirements_hash() != req_before:
            log.write(b"\n=== dependencies changed, reinstalling ===\n")
            pip = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(paths.REPO_DIR / "requirements.txt")],
                cwd=str(paths.REPO_DIR),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            code = pip.returncode

    state = _read_state()
    head = _git("rev-parse", "--short", "HEAD")
    if head.returncode == 0:
        state["current_commit"] = head.stdout.strip()
    state["finished_at"] = _now()
    state["exit_code"] = code
    _write_state(state)
    return code


def log_tail(lines: int = 30) -> str:
    if not LOG_FILE.exists():
        return ""
    return "\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-lines:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the update (used internally)")
    args = parser.parse_args()
    if args.run:
        paths.ensure_layout()
        raise SystemExit(run_update())


if __name__ == "__main__":
    main()

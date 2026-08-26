"""Run the fetch_* scrapers as background subprocesses, managed from the dashboard.

State lives in data/.sync/<service>.json, logs append to data/logs/<service>.log,
and successful sync timestamps are recorded in data/sync_status.json. All work
happens in detached subprocesses so syncs survive page navigation or closing the
browser tab.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import paths

REPO_DIR = paths.REPO_DIR
STATE_DIR = paths.DATA_DIR / ".sync"
LOG_DIR = paths.DATA_DIR / "logs"
STATUS_FILE = paths.DATA_DIR / "sync_status.json"

SERVICES = ("garmin", "grint", "hole19")


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _script(service: str) -> Path:
    return REPO_DIR / f"fetch_{service}.py"


def _state_path(service: str) -> Path:
    return STATE_DIR / f"{service}.json"


def _read_state(service: str) -> dict:
    try:
        return json.loads(_state_path(service).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(service: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(service).write_text(json.dumps(state, indent=1))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def status(service: str) -> dict:
    """Current state of a service's sync: running/finished/exit code."""
    state = _read_state(service)
    pid = state.get("pid")
    if pid and not state.get("finished_at") and not _pid_alive(pid):
        # The process died without recording its exit (machine sleep, kill, crash).
        state["finished_at"] = state.get("started_at") or _now()
        state["interrupted"] = True
        _write_state(service, state)
    return {
        "running": bool(pid) and not state.get("finished_at"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
        "exit_code": state.get("exit_code"),
        "interrupted": state.get("interrupted", False),
        "full": state.get("full", False),
    }


def any_running() -> bool:
    return any(status(s)["running"] for s in SERVICES)


def last_synced(service: str) -> str | None:
    try:
        return json.loads(STATUS_FILE.read_text()).get(service)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def log_tail(service: str, lines: int = 30) -> str:
    path = LOG_DIR / f"{service}.log"
    if not path.exists():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])


def start(services: list[str], full: bool = False, extra_env: dict | None = None) -> str | None:
    """Launch a sync for the given services (run sequentially). Returns an error message or None."""
    if not services:
        return None
    if any_running():
        return "A sync is already running — wait for it to finish"
    for s in services:
        if not _script(s).exists():
            return f"Unknown service: {s}"

    env = {**os.environ, **(extra_env or {})}
    args = [sys.executable, str(Path(__file__).resolve()), "--run-all", *services]
    if full:
        args.append("--full")

    proc = subprocess.Popen(
        args,
        cwd=str(REPO_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    # Optimistic state so the UI sees "running" immediately; the wrapper process
    # (same pid) rewrites this when each service starts.
    first = services[0]
    _write_state(first, {"pid": proc.pid, "started_at": _now(), "finished_at": None, "exit_code": None, "full": full})
    return None


def _record_success(service: str) -> None:
    try:
        data = json.loads(STATUS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data[service] = _now()
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data, indent=1))


def _sync_one(service: str, full: bool, env: dict) -> int:
    """Run one fetch script to completion, updating state and logs. Returns its exit code."""
    _write_state(
        service,
        {"pid": os.getpid(), "started_at": _now(), "finished_at": None, "exit_code": None, "full": full},
    )
    cmd = [sys.executable, str(_script(service)), "--headless"]
    if full:
        cmd.append("--full")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / f"{service}.log", "ab") as log:
        log.write(f"\n=== sync started {_now()} ===\n".encode())
        log.flush()
        result = subprocess.run(
            cmd, cwd=str(REPO_DIR), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env
        )

    state = _read_state(service)
    state["finished_at"] = _now()
    state["exit_code"] = result.returncode
    state["interrupted"] = False
    _write_state(service, state)
    if result.returncode == 0:
        _record_success(service)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-all",
        nargs="*",
        dest="services",
        metavar="SERVICE",
        help="run the given services sequentially (defaults to all)",
    )
    parser.add_argument("--full", action="store_true", help="pass --full to each fetch script")
    args = parser.parse_args()
    paths.ensure_layout()

    services = args.services or list(SERVICES)
    failures = []
    for s in services:
        code = _sync_one(s, full=args.full, env=os.environ.copy())
        if code != 0:
            failures.append(s)

    if failures:
        print(f"failed: {', '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

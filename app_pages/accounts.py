import time
from pathlib import Path

import polars as pl
import streamlit as st

import credentials
import stats
import sync_manager

GARMIN_TOKEN_DIR = Path("~/.garminconnect").expanduser()

SERVICE_META = {
    "garmin": (
        "Garmin Connect",
        "Rounds and shot-by-shot shot data from your Garmin watch.",
        lambda: GARMIN_TOKEN_DIR.exists(),
    ),
    "grint": (
        "TheGrint",
        "Historical rounds from TheGrint.",
        lambda: Path("~/.thegrint_session.json").expanduser().exists(),
    ),
    "hole19": (
        "Hole19",
        "All rounds tracked in the Hole19 app.",
        lambda: Path("~/.hole19_session.json").expanduser().exists(),
    ),
}


def _has_creds(service: str) -> bool:
    return credentials.get_login(service) is not None or bool(
        st.session_state.get(f"{service}_creds")
    )


def _round_count(service: str) -> int | None:
    try:
        rounds = stats.load_rounds()
    except FileNotFoundError:
        return None
    return rounds.filter(pl.col("source") == service).height


def _status_line(service: str) -> str:
    bits = []
    if _has_creds(service):
        bits.append("password saved" if credentials.get_login(service) else "password for this session only")
    if SERVICE_META[service][2]():
        bits.append("signed-in session cached")
    n = _round_count(service)
    if n is not None:
        bits.append(f"{n} rounds imported")
    last = sync_manager.last_synced(service)
    if last:
        bits.append(f"last synced {last[:16].replace('T', ' ')}")
    return " · ".join(bits) if bits else "Not set up yet"


def _mfa_env() -> dict:
    code = (st.session_state.get("garmin_mfa") or "").strip()
    return {"GARMIN_MFA_CODE": code} if code else {}


def _launch(services: list[str], full: bool = False) -> None:
    err = sync_manager.start(services, full=full, extra_env=_mfa_env())
    if err:
        st.error(err)
    else:
        st.rerun()


st.title("Accounts & syncing")

statuses = {s: sync_manager.status(s) for s in sync_manager.SERVICES}
running = {s for s, v in statuses.items() if v["running"]}
any_running = bool(running)

# Clear cached data when a sync has finished since the last render, so chart pages refresh.
seen_finished = st.session_state.setdefault("_seen_finished", {})
for svc, v in statuses.items():
    fin = v["finished_at"]
    if fin and svc in seen_finished and seen_finished[svc] != fin:
        st.cache_data.clear()
    seen_finished[svc] = fin

with st.container(border=True):
    top = st.columns([1, 3])
    can_sync = not any_running and any(_has_creds(s) for s in sync_manager.SERVICES)
    if top[0].button("Sync all", type="primary", disabled=not can_sync, use_container_width=True):
        _launch(list(sync_manager.SERVICES))
    if any_running:
        top[1].info(f"Syncing: {', '.join(sorted(running))} — this page updates automatically.")
    else:
        top[1].caption(
            "Downloads new rounds from every signed-in service, one after another. "
            "First-time imports can take a while; later syncs are quick."
        )

for service, (label, blurb, _) in SERVICE_META.items():
    v = statuses[service]
    with st.container(border=True):
        header = st.columns([2, 2])
        header[0].markdown(f"**{label}**")
        header[1].caption(_status_line(service))
        st.caption(blurb)

        saved = credentials.get_login(service)
        with st.form(f"signin_{service}", border=False):
            email = st.text_input("Email", value=saved[0] if saved else "", key=f"{service}_email")
            password = st.text_input("Password", type="password", value="", key=f"{service}_password")
            remember = st.checkbox(
                "Remember password so expired sessions can re-login automatically",
                value=True,
                key=f"{service}_remember",
            )
            if service == "garmin":
                st.text_input(
                    "Two-factor code (only fill in if your account uses 2FA)",
                    key="garmin_mfa",
                    help="Enter a fresh code right before syncing — codes expire quickly.",
                )
            if st.form_submit_button("Save sign-in"):
                if not email or not password:
                    st.error("Enter both email and password.")
                elif remember:
                    credentials.save_login(service, email, password)
                    st.session_state.pop(f"{service}_creds", None)
                    st.success(f"{label} sign-in saved.")
                else:
                    st.session_state[f"{service}_creds"] = (email, password)
                    st.success(f"{label} sign-in saved for this session.")

        cols = st.columns(2)
        if cols[0].button(
            "Sync now",
            disabled=any_running or not _has_creds(service),
            use_container_width=True,
            key=f"sync_{service}",
        ):
            _launch([service])
        with cols[1].popover(
            "Full re-sync", disabled=any_running or not _has_creds(service), use_container_width=True
        ):
            st.write(
                f"Deletes the stored {label} rounds and downloads all of them again from scratch. "
                "Use this if data looks wrong."
            )
            if st.button("Yes, re-download everything", key=f"full_{service}", type="primary"):
                _launch([service], full=True)

        if v["running"]:
            st.info("Running…")
            st.code(sync_manager.log_tail(service) or "(no output yet)", language="text")
        elif v["finished_at"]:
            if v.get("interrupted"):
                st.warning("Last sync was interrupted before it finished — retry when ready.")
            elif v["exit_code"] not in (0, None):
                tail = sync_manager.log_tail(service, lines=5)
                st.error(f"Last sync failed. Log:\n\n```\n{tail}\n```")
            else:
                st.caption(f"Last sync finished at {v['finished_at'][:16].replace('T', ' ')}.")

if any_running:
    time.sleep(3)
    st.rerun()

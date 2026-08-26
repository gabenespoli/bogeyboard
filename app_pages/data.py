import time

import polars as pl
import streamlit as st

import credentials
import paths
import stats
import sync_manager
import updater

st.title("Data & Syncing")

stats.require_data()

rounds = stats.load_rounds()
holes = stats.load_holes()
shots = stats.load_shots()

round_ids = rounds.sort("date", descending=True)["round_id"].to_list()
labels = {
    rid: str(rounds.filter(pl.col("round_id") == rid).select("date", "course_name").row(0))
    for rid in round_ids
}


def pick_rounds(key: str) -> list[int]:
    return st.multiselect(
        "Rounds",
        options=round_ids,
        format_func=labels.get,
        key=key,
        placeholder="All rounds",
    )


SERVICE_META = {
    "garmin": (
        "Garmin Connect",
        "Rounds and shot-by-shot shot data from your Garmin watch.",
        lambda: paths.GARMIN_TOKEN_STORE.exists(),
    ),
    "grint": (
        "TheGrint",
        "Historical rounds from TheGrint.",
        lambda: paths.GRINT_SESSION_FILE.exists(),
    ),
    "hole19": (
        "Hole19",
        "All rounds tracked in the Hole19 app.",
        lambda: paths.HOLE19_SESSION_FILE.exists(),
    ),
}


def _has_creds(service: str) -> bool:
    return credentials.get_login(service) is not None or bool(
        st.session_state.get(f"{service}_creds")
    )


def _round_count(service: str) -> int | None:
    try:
        r = stats.load_rounds()
    except FileNotFoundError:
        return None
    return r.filter(pl.col("source") == service).height


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


tab_rounds, tab_holes, tab_shots, tab_accounts = st.tabs(["Rounds", "Holes", "Shots", "Accounts"])

with tab_rounds:
    st.dataframe(rounds, hide_index=True)

with tab_holes:
    picked = pick_rounds("hole_filter")
    df = holes if not picked else holes.filter(pl.col("round_id").is_in(picked))
    st.dataframe(df, hide_index=True)

with tab_shots:
    picked = pick_rounds("shot_filter")
    df = shots if not picked else shots.filter(pl.col("round_id").is_in(picked))
    st.dataframe(df, hide_index=True)

with tab_accounts:
    statuses = {s: sync_manager.status(s) for s in sync_manager.SERVICES}
    running = {s for s, v in statuses.items() if v["running"]}
    any_running = bool(running)
    update = updater.status()
    update_running = update["running"]
    busy = any_running or update_running

    seen_finished = st.session_state.setdefault("_seen_finished", {})
    for key, finished in [
        *((f"sync_{s}", v["finished_at"]) for s, v in statuses.items()),
        ("update", update["finished_at"]),
    ]:
        if finished and key in seen_finished and seen_finished[key] != finished:
            st.cache_data.clear()
        seen_finished[key] = finished

    with st.container(border=True):
        top = st.columns([1, 3])
        can_sync = not busy and any(_has_creds(s) for s in sync_manager.SERVICES)
        if top[0].button("Sync all", type="primary", disabled=not can_sync, width="stretch"):
            _launch(list(sync_manager.SERVICES))
        if update_running:
            top[1].info("Installing an app update — syncing is paused until it finishes.")
        elif any_running:
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
                disabled=busy or not _has_creds(service),
                width="stretch",
                key=f"sync_{service}",
            ):
                _launch([service])
            with cols[1].popover(
                "Full re-sync", disabled=busy or not _has_creds(service), width="stretch"
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

    with st.container(border=True):
        st.markdown("**App version**")

        if not update["supported"]:
            st.info(
                f"This copy of Bogeyboard can't check for updates on its own. "
                f"Download the latest version from [GitHub]({updater.ZIP_URL}) and replace this folder — "
                "your data and saved sign-ins live outside the app folder, so nothing is lost."
            )
        else:
            behind = update["commits_behind"]
            commit = update["current_commit"] or "?"
            if update_running:
                st.info("Updating… the app reloads automatically when it finishes.")
            elif behind is None:
                st.caption(f"Version {commit} — couldn't reach GitHub to check for updates.")
            elif behind == 0:
                st.caption(f"Version {commit} — up to date.")
            else:
                st.warning(f"Version {commit} — {behind} update{'s' if behind != 1 else ''} available.")

            cols = st.columns(2)
            checked = update["checked_at"]
            if cols[0].button(
                "Check for updates",
                disabled=busy,
                width="stretch",
                key="check_update",
            ):
                updater.status(refresh=True)
                st.rerun()
            if cols[1].button(
                "Update now",
                disabled=busy or not behind,
                width="stretch",
                key="run_update",
            ):
                err = updater.start_update()
                if err:
                    st.error(err)
                else:
                    st.rerun()

            if update_running:
                st.code(updater.log_tail() or "(working…)", language="text")
            elif update["finished_at"]:
                if update.get("interrupted"):
                    st.warning("The last update was interrupted — you can try again any time.")
                elif update["exit_code"] not in (0, None):
                    tail = updater.log_tail(lines=5)
                    st.error(f"The last update failed. Log:\n\n```\n{tail}\n```")
                else:
                    st.caption("Last update installed successfully.")
            if checked:
                st.caption(f"Last checked {checked[:16].replace('T', ' ')}.")

    if busy:
        time.sleep(3)
        st.rerun()

    st.caption(f"{rounds.height} rounds · {holes.height} holes · {shots.height} shots")

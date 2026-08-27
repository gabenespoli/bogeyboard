import altair as alt
import polars as pl
import streamlit as st

import stats
import settings as user_settings
from filters import club_filter_sidebar, sidebar_filters

st.title("Clubs")
st.caption("Shot data from Garmin tracking, putts excluded. All charts respect the sidebar filters.")

stats.require_data()

round_ids, _ = sidebar_filters()
effective = club_filter_sidebar(round_ids)

# Unified shot filter controls that can express all methods
st.subheader("Filters")
SHOT_TYPE_OPTIONS = ["TEE", "APPROACH", "CHIP", "LAYUP", "RECOVERY", "UNKNOWN", "PUTT"]
DEFAULT_SHOT_TYPES = ["TEE", "APPROACH", "UNKNOWN"]
saved = user_settings.load_settings()
saved_st = [s for s in saved.get("clubs_shot_types", DEFAULT_SHOT_TYPES) if s in SHOT_TYPE_OPTIONS]
picked_st = st.multiselect(
    "Shot types",
    options=SHOT_TYPE_OPTIONS,
    default=saved_st if saved_st else DEFAULT_SHOT_TYPES,
    key="clubs_shot_types_mselect",
    help="Filter which shot types count. PUTT excluded by default. Garmin exact uses TEE + APPROACH only.",
)
user_settings.update_setting("clubs_shot_types", picked_st)
effective_st = picked_st if picked_st else DEFAULT_SHOT_TYPES

c_type, c_low, c_high = st.columns(3)
trim_type_opts = ["std", "pct"]
saved_trim_type = saved.get("clubs_trim_type", "std")
if saved_trim_type not in trim_type_opts:
    saved_trim_type = "std"
with c_type:
    trim_type = st.selectbox(
        "Trim type",
        options=trim_type_opts,
        index=trim_type_opts.index(saved_trim_type),
        key="clubs_trim_type",
        help="std = mean ± k·σ per club (as before). pct = keep top/bottom X% per club by distance. Garmin exact: trim type = pct, Trim low = 50% (keep top 50% longest), Trim high = Off.",
    )
user_settings.update_setting("clubs_trim_type", trim_type)

# Garmin exact info tooltip
st.caption(
    "ℹ️ **Garmin exact** (replicates Garmin Golf `averageDistance`): Shot types = **TEE, APPROACH** • Trim type = **pct** • Trim low = **50%** (keep top 50% longest) • Trim high = **Off** • RMSE 2.6m vs official. Peak Top 25% = same with Trim low = 25%."
)

if trim_type == "std":
    trim_opts_std = ["Off", 2, 1, 0.5, 0.25]
    saved_low = saved.get("clubs_trim_low_std", "Off")
    saved_high = saved.get("clubs_trim_high_std", "Off")
    with c_low:
        trim_low = st.selectbox(
            "Trim below average (−σ)",
            options=trim_opts_std,
            index=trim_opts_std.index(saved_low) if saved_low in trim_opts_std else 0,
            key="clubs_trim_low_std",
            disabled=False,
        )
    with c_high:
        trim_high = st.selectbox(
            "Trim above average (+σ)",
            options=trim_opts_std,
            index=trim_opts_std.index(saved_high) if saved_high in trim_opts_std else 0,
            key="clubs_trim_high_std",
            disabled=False,
        )
    user_settings.update_setting("clubs_trim_low_std", trim_low)
    user_settings.update_setting("clubs_trim_high_std", trim_high)
    eff_low, eff_high = trim_low, trim_high
else:
    trim_opts_pct = ["Off", "10%", "25%", "50%", "75%"]
    saved_low = saved.get("clubs_trim_low_pct", "Off")
    saved_high = saved.get("clubs_trim_high_pct", "Off")
    with c_low:
        trim_low = st.selectbox(
            "Trim low (keep top X%)",
            options=trim_opts_pct,
            index=trim_opts_pct.index(saved_low) if saved_low in trim_opts_pct else 0,
            key="clubs_trim_low_pct",
            help="Keep top X% longest per club. 50% = Garmin exact, 25% = Peak.",
        )
    with c_high:
        trim_high = st.selectbox(
            "Trim high (drop top X%)",
            options=trim_opts_pct,
            index=trim_opts_pct.index(saved_high) if saved_high in trim_opts_pct else 0,
            key="clubs_trim_high_pct",
            help="Drop top X% longest (keep bottom). Usually Off.",
        )
    user_settings.update_setting("clubs_trim_low_pct", trim_low)
    user_settings.update_setting("clubs_trim_high_pct", trim_high)
    eff_low, eff_high = trim_low, trim_high

# Use unified filtered shot set for both KDE and mean lines
shots = stats.shot_distances(effective, round_ids, trim_std=eff_low, trim_std_high=eff_high, shot_types=effective_st, trim_type=trim_type)

st.subheader("Distance distribution")
if shots.height == 0:
    st.caption("No measurable shots for the selected clubs / filters in this range.")
else:
    if trim_type == "std":
        parts = []
        if eff_low != "Off":
            parts.append(f"−{eff_low}σ below")
        if eff_high != "Off":
            parts.append(f"+{eff_high}σ above")
        if parts:
            st.caption(f"Outlier trimming (std) — keeping shots within {' and '.join(parts)} the club average ({shots.height} shots).")
        else:
            st.caption(f"Std trim off — {shots.height} shots.")
    else:
        parts = []
        if eff_low != "Off":
            parts.append(f"keep top {eff_low}")
        if eff_high != "Off":
            parts.append(f"drop top {eff_high}")
        if parts:
            st.caption(f"Pct trim — {' + '.join(parts)} per club ({shots.height} shots).")
        else:
            st.caption(f"No pct trim — {shots.height} shots.")

    curves, means = stats.shot_density(
        effective, round_ids, trim_std=eff_low, trim_std_high=eff_high, shot_types=effective_st, trim_type=trim_type
    )
    areas = (
        alt.Chart(curves, height=350)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("distance:Q", title="Distance (yards)"),
            y=alt.Y("density:Q", title="Density"),
            color=alt.Color("club:N", title=None),
            tooltip=["club:N", alt.Tooltip("distance:Q", format=".0f")],
        )
    )
    rules = (
        alt.Chart(means)
        .mark_rule()
        .encode(
            x=alt.X("mean_yds:Q"),
            color=alt.Color("club:N", legend=None),
            tooltip=[
                "club:N",
                alt.Tooltip("mean_yds:Q", title="Mean distance (yds)", format=".1f"),
            ],
        )
    )
    labels = (
        alt.Chart(means)
        .mark_text(align="center", angle=90, fontSize=11, dy=8)
        .encode(
            x=alt.X("mean_yds:Q"),
            y=alt.Y("label_y:Q"),
            text=alt.Text("club:N"),
            color=alt.Color("club:N", legend=None),
        )
    )
    st.altair_chart((areas + rules + labels), width="stretch")

st.subheader("Average distances")

clubs = stats.club_distances(
    round_ids,
    club_names=effective,
    trim_std=eff_low,
    trim_std_high=eff_high,
    shot_types=effective_st,
    trim_type=trim_type,
)
if clubs.height == 0:
    st.caption("No club-tagged shots yet — rerun the Garmin fetch after playing with CT10 sensors paired.")
else:
    st.dataframe(clubs, hide_index=True)

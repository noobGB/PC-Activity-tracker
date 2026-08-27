"""
Local, on-demand Streamlit dashboard for activity_log.csv.

Run with: streamlit run dashboard.py
Opens a localhost page only -- nothing here talks to the network or leaves the
machine. Re-reads and re-aggregates the CSV on every interaction (cheap at this
data size; see analysis.py for the categorization/aggregation logic itself).
"""

import os

import pandas as pd
import streamlit as st

from analysis import (
    app_usage_with_categories,
    daily_bucket_minutes,
    filter_date_range,
    hours_by,
    load_log,
    web_activity_with_categories,
)
from pc_activity_tracker import CSV_PATH

st.set_page_config(page_title="Activity Tracker Dashboard", layout="wide")


@st.cache_data(show_spinner=False)
def _cached_load(csv_path, mtime):
    """Load + parse the CSV, cached per (path, mtime) so repeated interactions
    within the same session don't re-parse the file until it actually changes on
    disk (the tracker appends to it roughly once a minute)."""
    return load_log(csv_path)


def load_fresh():
    """Load the CSV, busting the cache automatically whenever the file's mtime
    has moved on -- so a manual 'Refresh data' click or the tracker's own next
    flush always shows up without a stale cache hit."""
    mtime = os.path.getmtime(CSV_PATH)
    return _cached_load(CSV_PATH, mtime)


st.title("Activity Tracker Dashboard")

if not os.path.exists(CSV_PATH):
    st.error(f"No activity log found at {CSV_PATH}. Is the tracker running?")
    st.stop()

df = load_fresh()
min_date, max_date = df["date"].min(), df["date"].max()

with st.sidebar:
    st.header("Filters")
    date_range = st.date_input(
        "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date

    st.divider()
    cap_minutes = st.slider(
        "Cap single-session minutes at",
        min_value=30, max_value=480, value=180, step=15,
        help=(
            "Rows written before the sleep/lock-gap fix (see technical_notes.md, "
            "issue #1) can carry multi-hour or multi-day durations from a single "
            "session that spanned a sleep/lock. This clips any single AppUsage "
            "session's duration so a handful of legacy outlier rows can't swamp "
            "the charts below. Raise it (or set it to 480) once your data is all "
            "post-fix."
        ),
    )

    st.divider()
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

df = filter_date_range(df, start_date, end_date)
n_days = df["date"].nunique()

if n_days == 0:
    st.warning("No data in the selected date range.")
    st.stop()

app_df = app_usage_with_categories(df, cap_minutes)
web_df = web_activity_with_categories(df)

total_hours = app_df["duration_minutes"].sum() / 60

col1, col2, col3 = st.columns(3)
col1.metric("Days covered", n_days)
col2.metric("Tracked active hours", f"{total_hours:.1f}")
col3.metric("Avg hours / day", f"{total_hours / n_days:.1f}")

st.subheader("Time by category")
bucket_hours = hours_by(app_df, "app_bucket")
st.bar_chart(bucket_hours)

left, right = st.columns(2)
with left:
    st.subheader("Time by app (top 15)")
    st.bar_chart(hours_by(app_df, "app_label").head(15))
with right:
    st.subheader("Web activity by category (visit-event counts)")
    web_counts = web_df["web_category"].value_counts().head(15)
    st.bar_chart(web_counts)

st.subheader("Daily trend: Development vs Browsing")
daily = daily_bucket_minutes(app_df, df["date"], ["Development", "Browsing"])
st.area_chart(daily)

with st.expander("Uncategorized ('Other') domains -- extend DOMAIN_CATEGORIES in analysis.py to label these"):
    other = web_df[web_df["web_category"].str.startswith("Other:")]
    st.dataframe(other["domain"].value_counts().rename("visits"), use_container_width=True)

with st.expander("Raw filtered rows"):
    st.dataframe(df, use_container_width=True)

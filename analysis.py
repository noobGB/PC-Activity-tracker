"""
Shared analysis logic for activity_log.csv.

Turns the raw per-event/per-session CSV rows written by pc_activity_tracker.py into
categorized, aggregated summaries: per-app active time, web activity by category, and
daily trends. Deliberately has no UI code of its own -- dashboard.py (and any future
CLI report) import from here so both stay in agreement instead of drifting apart.
"""

from urllib.parse import urlparse

import pandas as pd

from pc_activity_tracker import CSV_PATH

# ---------------------------------------------------------------------------
# App categorization
# ---------------------------------------------------------------------------

# Maps a process name (as logged in app_or_browser for AppUsage rows) to
# (friendly label, high-level bucket). Processes not listed here fall back to
# showing their raw exe name under the "Other" bucket -- extend this as new
# processes show up in your own log.
APP_CATEGORIES = {
    "Code.exe": ("VS Code", "Development"),
    "python.exe": ("Python scripts", "Development"),
    "WindowsTerminal.exe": ("Terminal", "Development"),
    "Docker Desktop.exe": ("Docker Desktop", "Development"),
    "notepad++.exe": ("Notepad++", "Development"),
    "draw.io.exe": ("draw.io", "Development"),
    "chrome.exe": ("Chrome", "Browsing"),
    "msedge.exe": ("Edge", "Browsing"),
    "claude.exe": ("Claude Desktop", "AI tools"),
    "Telegram.exe": ("Telegram", "Communication"),
    "Photos.exe": ("Photos", "Media"),
    "explorer.exe": ("File Explorer", "System"),
    "ApplicationFrameHost.exe": ("UWP app host", "System"),
    "SearchHost.exe": ("Windows Search", "System"),
    "logioptionsplus.exe": ("Logi Options+", "System"),
    "ShellHost.exe": ("Shell host", "System"),
    "ShellExperienceHost.exe": ("Shell experience host", "System"),
    "PickerHost.exe": ("Picker host", "System"),
    "SnippingTool.exe": ("Snipping Tool", "Utilities"),
    "Notepad.exe": ("Notepad", "Utilities"),
    "LockApp.exe": ("Lock screen", "Idle/Locked"),
    "Unknown": ("Unknown window", "Idle/Locked"),
}


def categorize_app(process_name):
    """Map a raw process name to (friendly_label, high_level_bucket). Anything not
    in APP_CATEGORIES is labeled with its own exe name under 'Other', so new
    processes still show up in the breakdown instead of disappearing."""
    return APP_CATEGORIES.get(process_name, (process_name, "Other"))


# ---------------------------------------------------------------------------
# Web (URL) categorization
# ---------------------------------------------------------------------------

# Maps a URL's domain (netloc, "www." stripped) to a friendly category label for
# WebReading/YouTube rows. These rows only carry visit events, not durations, so
# this feeds a "count of visits" view rather than a time view.
DOMAIN_CATEGORIES = {
    "google.com": "Search",
    "search.yahoo.com": "Search",
    "accounts.google.com": "Google account/services",
    "mail.google.com": "Email",
    "photos.google.com": "Google Photos",
    "calendar.google.com": "Google Calendar",
    "youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "github.com": "Dev: GitHub",
    "stackoverflow.com": "Dev: StackOverflow",
    "app.snowflake.com": "Learning: Snowflake",
    "learn.snowflake.com": "Learning: Snowflake",
    "platform.claude.com": "Dev: Claude/Anthropic console",
    "support.claude.com": "Dev: Claude/Anthropic console",
    "claude.ai": "AI tools: Claude",
    "claude.com": "AI tools: Claude",
    "anthropic.com": "Dev/Docs: Anthropic",
    "linkedin.com": "Social/Professional: LinkedIn",
    "medium.com": "Reading: Medium",
    "amazon.com": "Shopping",
    "amazon.in": "Shopping",
    "flipkart.com": "Shopping",
    "agoda.com": "Travel booking",
    "goindigo.in": "Travel booking",
    "imdb.com": "Entertainment: IMDb",
    "imdb.is": "Entertainment: streaming mirror",
    "m.imdb.com": "Entertainment: IMDb",
    "streamimdb.ru": "Entertainment: streaming mirror",
    "media.io": "Media downloader tool",
    "vidssave.com": "Media downloader tool",
    "en1.savefrom.net": "Media downloader tool",
    "app.ytdown.to": "Media downloader tool",
    "styles.refero.design": "Dev: design/CSS reference",
    "spectrum.ieee.org": "Reading: tech/robotics",
    "madmapper.com": "Research: hardware/projection tool",
}


def extract_domain(url):
    """Pull the bare domain (no 'www.' prefix) out of a URL, or None if url is
    missing/unparseable. Used as the lookup key into DOMAIN_CATEGORIES."""
    if not isinstance(url, str) or not url:
        return None
    try:
        return urlparse(url).netloc.lower().replace("www.", "") or None
    except ValueError:
        return None


def categorize_domain(domain):
    """Map a domain to a friendly category label. localhost/LAN addresses are
    grouped as 'Dev: local server' (any port) since they're always your own dev
    servers, not a site worth distinguishing by port. Anything else unrecognized
    is labeled 'Other: <domain>' so it still surfaces in per-domain breakdowns
    rather than disappearing into a single opaque bucket."""
    if domain is None:
        return "Unknown"
    if domain in DOMAIN_CATEGORIES:
        return DOMAIN_CATEGORIES[domain]
    if domain.startswith("localhost") or domain.startswith("127.0.0.1") or domain.startswith("192.168."):
        return "Dev: local server"
    return f"Other: {domain}"


# ---------------------------------------------------------------------------
# Loading + aggregation
# ---------------------------------------------------------------------------

def load_log(csv_path=None):
    """Load activity_log.csv into a DataFrame with 'date' parsed as a real date.
    Defaults to the same CSV_PATH the tracker itself writes to."""
    df = pd.read_csv(csv_path or CSV_PATH, low_memory=False)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def filter_date_range(df, start_date, end_date):
    """Return only rows with date in [start_date, end_date] inclusive."""
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)]


def app_usage_with_categories(df, cap_minutes):
    """Return the AppUsage rows with 'app_label'/'app_bucket' columns added, and
    'duration_minutes' clipped at cap_minutes.

    cap_minutes exists because rows written before the sleep/lock-gap fix (see
    technical_notes.md) can carry multi-hour or multi-day durations from a single
    session that spanned a sleep/lock -- without capping, one such legacy row can
    visually swamp an otherwise-accurate chart. Set cap_minutes high enough (or to
    None) to stop clipping once your data postdates the fix."""
    app_df = df[df["category"] == "AppUsage"].copy()
    labels = app_df["app_or_browser"].map(categorize_app)
    app_df["app_label"] = labels.map(lambda t: t[0])
    app_df["app_bucket"] = labels.map(lambda t: t[1])
    if cap_minutes is not None:
        app_df["duration_minutes"] = app_df["duration_minutes"].clip(upper=cap_minutes)
    return app_df


def web_activity_with_categories(df):
    """Return the WebReading/YouTube rows with 'domain'/'web_category' columns
    added. These rows have no duration -- only visit-event counts are meaningful."""
    web_df = df[df["category"].isin(["WebReading", "YouTube"])].copy()
    web_df["domain"] = web_df["url"].map(extract_domain)
    web_df["web_category"] = web_df["domain"].map(categorize_domain)
    return web_df


def hours_by(app_df, column):
    """Sum duration_minutes by the given column (e.g. 'app_bucket' or
    'app_label'), returned as hours, sorted descending."""
    return (app_df.groupby(column)["duration_minutes"].sum() / 60).sort_values(ascending=False)


def daily_bucket_minutes(app_df, dates, buckets):
    """Pivot capped AppUsage minutes into a date x bucket table, for a stacked
    daily trend chart. `buckets` is the list/order of app_bucket values to include
    as columns (others are dropped) -- typically ['Development', 'Browsing']."""
    subset = app_df[app_df["app_bucket"].isin(buckets)]
    pivot = subset.pivot_table(
        index="date", columns="app_bucket", values="duration_minutes", aggfunc="sum", fill_value=0.0
    )
    pivot = pivot.reindex(columns=buckets, fill_value=0.0)
    pivot = pivot.reindex(index=sorted(set(dates)), fill_value=0.0)
    return pivot / 60  # hours

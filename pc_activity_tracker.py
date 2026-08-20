"""
Personal PC activity tracker.

Runs continuously in the background, logging:
  - active window/app usage (what app + window title you had focused, and for how long)
  - browser history from Chrome and Edge (web reading + YouTube), tagged by category

Output: a single CSV in Google Drive (auto-synced), plus a small local state file
so re-runs never duplicate rows, and a local debug log for troubleshooting.
"""

import csv
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import time
import traceback

import psutil
import win32gui
import win32process

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Where the tracker writes its data. This is a path inside your local Google Drive
# sync folder, so anything written here gets uploaded to Drive automatically —
# no Google API/auth needed on our end.
DRIVE_DIR = r"G:\My Drive\ActivityTracker"
CSV_PATH = os.path.join(DRIVE_DIR, "activity_log.csv")     # the activity log itself
STATE_PATH = os.path.join(DRIVE_DIR, "state.json")          # bookkeeping so re-runs don't duplicate rows

# Local-only (not synced to Drive) folder for debug logs and scratch copies of
# browser history files. Kept off Drive since it's just internal plumbing.
LOCAL_DIR = os.path.join(os.environ["LOCALAPPDATA"], "ActivityTracker")
LOG_PATH = os.path.join(LOCAL_DIR, "tracker.log")           # our own run/error log
TMP_DIR = os.path.join(LOCAL_DIR, "tmp")                    # scratch copies of browser History DBs

# Default profile paths for Chrome/Edge's SQLite history databases.
CHROME_HISTORY = os.path.join(
    os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data", "Default", "History"
)
EDGE_HISTORY = os.path.join(
    os.environ["LOCALAPPDATA"], "Microsoft", "Edge", "User Data", "Default", "History"
)

CSV_HEADERS = [
    "timestamp", "date", "time", "category", "app_or_browser",
    "title", "url", "duration_minutes",
]

# Timing knobs. All overridable via environment variables, mainly so a manual
# test run can use short intervals instead of waiting minutes/hours for the
# real defaults to fire.
POLL_INTERVAL = int(os.environ.get("ACTIVITY_TRACKER_POLL_INTERVAL", 10))            # how often we check the foreground window
BROWSER_CHECK_INTERVAL = int(os.environ.get("ACTIVITY_TRACKER_BROWSER_INTERVAL", 300))  # how often we read new browser history
FLUSH_INTERVAL = int(os.environ.get("ACTIVITY_TRACKER_FLUSH_INTERVAL", 60))          # how often buffered rows get written to the CSV
MIN_SESSION_SECONDS = 5  # ignore window-focus flickers shorter than this (e.g. alt-tabbing through windows)

WEBKIT_EPOCH_DELTA = 11644473600  # seconds between 1601-01-01 and 1970-01-01 (Chrome/Edge timestamp base)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def log(message):
    """Append a timestamped line to the local debug log (tracker.log). Used for
    startup/shutdown notices and any error we want to be able to look back at,
    since the script runs silently in the background with no visible console."""
    os.makedirs(LOCAL_DIR, exist_ok=True)
    line = f"{datetime.datetime.now().isoformat()} {message}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def load_state():
    """Load state.json, which remembers the last browser-history timestamp we've
    already processed for each browser. Returns {} if it doesn't exist yet
    (first ever run) or is corrupt, so the caller just starts fresh."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    """Persist state.json. Written to a temp file first and then swapped in with
    os.replace (atomic), so a crash or Drive sync mid-write can't leave behind a
    half-written, corrupt state file."""
    os.makedirs(DRIVE_DIR, exist_ok=True)
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp_path, STATE_PATH)


def ensure_csv():
    """Create activity_log.csv with just the header row if it doesn't exist yet.
    Safe to call every startup — it's a no-op once the file is already there."""
    os.makedirs(DRIVE_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADERS)


def append_rows(rows):
    """Append a batch of already-built rows to the CSV. Retries a few times with
    a short delay on PermissionError, since Google Drive's sync process (or you
    having the file open) can briefly lock it.

    Returns True if the rows were written, False otherwise -- the caller must
    only drop the rows from its buffer on True, or a persistent lock would
    silently lose that batch instead of retrying it on the next flush."""
    if not rows:
        return True
    for attempt in range(5):
        try:
            with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            return True
        except PermissionError:
            # CSV may be briefly locked by Drive sync or if it's open elsewhere.
            time.sleep(2)
    log(f"ERROR: failed to flush {len(rows)} rows after retries -- will retry next flush")
    return False


def make_row(dt, category, app_or_browser, title, url, duration_minutes):
    """Build one CSV row (as a list of strings) from raw values, splitting a
    single datetime into separate 'date' and 'time' columns as well as a full
    ISO 'timestamp' column, so the log is easy to filter/sort either way once
    opened in Excel/Sheets."""
    return [
        dt.isoformat(timespec="seconds"),
        dt.date().isoformat(),
        dt.time().isoformat(timespec="seconds"),
        category,
        app_or_browser,
        title,
        url,
        f"{duration_minutes:.2f}" if duration_minutes != "" else "",
    ]


# ---------------------------------------------------------------------------
# Active window / app tracking
# ---------------------------------------------------------------------------

def get_foreground_info():
    """Return (app_name, window_title) for whatever window currently has focus,
    using pywin32 to get the window handle/title and psutil to resolve the
    owning process's executable name (e.g. 'chrome.exe', 'Code.exe'). Falls
    back to 'Unknown'/'Idle' if the window or its process can't be resolved
    (e.g. it closed between the two calls, or we're on the bare desktop)."""
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) or ""
    app = "Idle"
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid:
            app = psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        app = "Unknown"
    if not title:
        title = "(no title)"
    return app, title


class WindowTracker:
    """Tracks how long each app/window stays focused, turning window-switch
    events into completed 'AppUsage' rows.

    Call poll() on every main-loop tick; it compares the current foreground
    window against the in-progress session and, if it changed, closes out the
    old session as a row and starts timing the new one. flush_current() closes
    out whatever's still in progress, for use on shutdown so the last session
    isn't lost."""

    def __init__(self):
        self.current = None  # dict: app, title, start (datetime) -- the in-progress session

    def poll(self, buffered_rows):
        """Check the current foreground window; if it's different from the
        in-progress session, close that session out (appending a row if it
        lasted long enough) and start timing the new one."""
        app, title = get_foreground_info()
        now = datetime.datetime.now()
        if self.current is None:
            self.current = {"app": app, "title": title, "start": now}
            return
        if app != self.current["app"] or title != self.current["title"]:
            self._close_session(now, buffered_rows)
            self.current = {"app": app, "title": title, "start": now}

    def _close_session(self, end_time, buffered_rows):
        """Turn the in-progress session into a row, but only if it lasted at
        least MIN_SESSION_SECONDS -- otherwise it's almost certainly just
        window-switching flicker (e.g. alt-tab passing through), not real
        usage worth recording."""
        start = self.current["start"]
        duration_sec = (end_time - start).total_seconds()
        if duration_sec >= MIN_SESSION_SECONDS:
            buffered_rows.append(make_row(
                start, "AppUsage", self.current["app"], self.current["title"],
                "", duration_sec / 60.0,
            ))

    def flush_current(self, buffered_rows):
        """Close out whatever session is still in progress. Called on shutdown
        so the very last app/window you were using before the tracker stopped
        still gets recorded instead of being silently lost."""
        if self.current is not None:
            self._close_session(datetime.datetime.now(), buffered_rows)


# ---------------------------------------------------------------------------
# Browser history collection
# ---------------------------------------------------------------------------

def classify_url(url):
    """Tag a URL as 'YouTube' if it's a video-watch link, otherwise 'WebReading'.
    Used to split browsing activity into the two categories you asked to
    distinguish in the log."""
    if "youtube.com/watch" in url or "youtu.be/" in url:
        return "YouTube"
    return "WebReading"


def copy_locked_db(src_path):
    """Copy a browser's History SQLite file into our local scratch folder before
    reading it. Chrome/Edge keep the real file open while running, so we read
    from a point-in-time copy instead of trying to open the live one directly."""
    os.makedirs(TMP_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".sqlite", dir=TMP_DIR)
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path


def collect_chromium_history(browser_name, history_path, state, buffered_rows):
    """Read any browser-history visits newer than what we've already processed
    for this browser, and append them to buffered_rows.

    - On the very first run for a browser (no entry in state.json yet), we only
      backfill the last 24 hours rather than the browser's entire history, so
      we don't dump months of old browsing into the log in one shot.
    - Chrome/Edge timestamps are microseconds since 1601-01-01 ("WebKit time"),
      so we convert to a normal Unix timestamp before building each row.
    - state[browser_last_visit] is advanced to the newest visit_time we saw,
      so the next run picks up right where this one left off.
    """
    if not os.path.exists(history_path):
        return
    state_key = f"{browser_name}_last_visit"
    last_visit = state.get(state_key)
    if last_visit is None:
        # First run for this browser: only backfill the last 24h, not all of history.
        cutoff_dt = datetime.datetime.now() - datetime.timedelta(hours=24)
        last_visit = int((cutoff_dt.timestamp() + WEBKIT_EPOCH_DELTA) * 1_000_000)

    tmp_path = None
    try:
        tmp_path = copy_locked_db(history_path)
        conn = sqlite3.connect(tmp_path)
        cur = conn.execute(
            """
            SELECT urls.url, urls.title, visits.visit_time
            FROM visits JOIN urls ON visits.url = urls.id
            WHERE visits.visit_time > ?
            ORDER BY visits.visit_time ASC
            LIMIT 2000
            """,
            (last_visit,),
        )
        max_visit = last_visit
        for url, title, visit_time in cur.fetchall():
            max_visit = max(max_visit, visit_time)
            unix_ts = visit_time / 1_000_000 - WEBKIT_EPOCH_DELTA
            dt = datetime.datetime.fromtimestamp(unix_ts)
            category = classify_url(url)
            buffered_rows.append(make_row(dt, category, browser_name, title or "", url, ""))
        conn.close()
        state[state_key] = max_visit
    except sqlite3.Error as e:
        log(f"WARN: {browser_name} history read failed: {e}")
    finally:
        # Always clean up the scratch copy, even if reading it failed.
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def collect_browser_history(state, buffered_rows):
    """Run the Chromium history collector for both browsers we support."""
    collect_chromium_history("Chrome", CHROME_HISTORY, state, buffered_rows)
    collect_chromium_history("Edge", EDGE_HISTORY, state, buffered_rows)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    """Entry point: sets up the CSV/state, then loops forever doing three things
    on their own independent schedules:
      1. every POLL_INTERVAL seconds -- check the foreground window (app tracking)
      2. every BROWSER_CHECK_INTERVAL seconds -- pull new browser history
      3. every FLUSH_INTERVAL seconds -- write buffered rows out to the CSV

    The CSV is never trimmed -- it keeps the full history indefinitely.

    Each iteration is wrapped in its own try/except so a transient error (e.g.
    a locked file) gets logged and the loop keeps going, rather than the whole
    background process dying silently. On shutdown (Ctrl+C or being killed),
    the finally block flushes anything still buffered so nothing in progress
    is lost.
    """
    log("tracker starting")
    ensure_csv()
    state = load_state()

    window_tracker = WindowTracker()
    buffered_rows = []
    last_browser_check = 0.0
    last_flush = time.time()

    try:
        while True:
            try:
                window_tracker.poll(buffered_rows)

                now = time.time()
                if now - last_browser_check >= BROWSER_CHECK_INTERVAL:
                    collect_browser_history(state, buffered_rows)
                    save_state(state)
                    last_browser_check = now

                if now - last_flush >= FLUSH_INTERVAL and buffered_rows:
                    if append_rows(buffered_rows):
                        buffered_rows = []
                    last_flush = now
            except Exception:
                log("ERROR in main loop:\n" + traceback.format_exc())

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        # Make sure the in-progress window session and any unflushed rows
        # still make it into the CSV before the process actually exits.
        window_tracker.flush_current(buffered_rows)
        append_rows(buffered_rows)
        save_state(state)
        log("tracker stopped")


if __name__ == "__main__":
    main()

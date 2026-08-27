# PC Activity Tracker

A small background script for Windows that tracks what you do on your PC — which apps/windows you have focused and for how long, plus your Chrome/Edge browsing history (tagged separately for YouTube vs general web reading) — and logs it to a CSV file synced through Google Drive.

## Why

For keeping a personal, searchable record of what you read, watched, and worked on each day: date, time, a title, and a URL where applicable.

## How it works

- Runs continuously in the background (registered as a Windows Task Scheduler task that starts at logon).
- Polls the foreground window every 10s to track app/window usage.
- Reads new Chrome/Edge browser history every 5 minutes.
- Buffers everything in memory and flushes to the CSV once a minute.
- Keeps the full history indefinitely -- the CSV is never trimmed.
- No cloud APIs or accounts involved for storage — it just writes a file inside your local Google Drive sync folder, and Drive for Desktop handles the upload.

See [CLAUDE.md](CLAUDE.md) for a deeper architecture breakdown.

## Requirements

- Windows, with [Google Drive for Desktop](https://www.google.com/drive/download/) installed and syncing (the script writes to `G:\My Drive\ActivityTracker` by default — adjust `DRIVE_DIR` in `pc_activity_tracker.py` if your Drive is mounted elsewhere).
- Python 3, with dependencies installed:
  ```
  pip install -r requirements.txt
  ```
- Chrome and/or Edge (the only browsers currently supported).

## Setup

1. Clone this repo.
2. Install dependencies (see above).
3. Adjust `DRIVE_DIR` in `pc_activity_tracker.py` if needed.
4. Test it manually first:
   ```
   python pc_activity_tracker.py
   ```
   Let it run for a minute or two, then check that `activity_log.csv` is being created/updated in your Drive folder, and check `%LOCALAPPDATA%\ActivityTracker\tracker.log` for errors.
5. Edit the hardcoded paths in `run_tracker.bat` and `run_tracker_hidden.vbs` to match where you cloned the repo and your `pythonw.exe` location.
6. Register it to run automatically at logon, launched through the watchdog wrapper rather than directly (requires an elevated/Administrator shell):
   ```
   schtasks /create /tn "PCActivityTracker" /tr "wscript.exe \"<path to run_tracker_hidden.vbs>\"" /sc onlogon /rl limited /f
   ```
   The watchdog (`run_tracker_hidden.vbs` → `run_tracker.bat`) relaunches the tracker within ~10 seconds any time it exits for any reason (crash, killed across a sleep/wake cycle, etc.), instead of only restarting at the next logon. `run_tracker_hidden.vbs` is what keeps this invisible — running the `.bat` directly from Task Scheduler would otherwise flash/hold open a console window.

## Managing the scheduled task

Because of the watchdog, killing `pythonw.exe` alone doesn't stop tracking — the `.bat` loop just relaunches it within ~10s. And **`schtasks /end` alone isn't reliable either**: in testing, it only kills the `wscript.exe` process Task Scheduler directly launched, not the `cmd.exe`/`pythonw.exe` children underneath it — those survive as orphans, still running, just detached from Task Scheduler.

Use `stop_tracker.bat` to actually stop everything. It matches processes by command line (every `pythonw.exe` running `pc_activity_tracker.py`, every `cmd.exe` running `run_tracker.bat`) rather than relying on Task Scheduler's tracking, so it cleans up the whole chain -- and any orphaned/duplicate copies too, if that's ever happened:

```
stop_tracker.bat                                      # reliably stop everything
schtasks /run /tn "PCActivityTracker"                 # start now
schtasks /query /tn "PCActivityTracker" /v /fo list   # status
schtasks /change /tn "PCActivityTracker" /disable     # pause -- won't restart at next logon either (re-enable with /enable)
```

To remove it entirely, run `stop_tracker.bat` first, *then* delete the task:

```
stop_tracker.bat
schtasks /delete /tn "PCActivityTracker" /f
```

## Dashboard

A local, on-demand Streamlit dashboard reads `activity_log.csv` and shows a categorized breakdown — time by app, web activity by category, a daily development-vs-browsing trend, and a date-range filter — recomputed fresh each time you open or refresh it.

```
streamlit run dashboard.py
```

Opens a `localhost`-only page in your browser (locked to `127.0.0.1` via `.streamlit/config.toml` — it never binds to your LAN or exposes a network URL, since this data is personal). The categorization logic lives in `analysis.py`, separate from the UI, so it can be reused by a future CLI report too.

## Configuration

All timing is overridable via environment variables (useful for quickly testing changes without waiting on the production intervals):

| Variable | Default | Meaning |
|---|---|---|
| `ACTIVITY_TRACKER_POLL_INTERVAL` | `10` | Seconds between foreground-window checks |
| `ACTIVITY_TRACKER_BROWSER_INTERVAL` | `300` | Seconds between browser-history reads |
| `ACTIVITY_TRACKER_FLUSH_INTERVAL` | `60` | Seconds between CSV flushes |

## Privacy

This tool is meant for personal use, tracking your own machine, and writes only to your own local Drive folder — nothing is sent to any third-party service. Because it reads real browser history, the log will include anything you visited (except incognito/private windows, which browsers never record). Treat the resulting CSV and its Google Drive folder as sensitive personal data.

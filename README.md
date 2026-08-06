# PC Activity Tracker

A small background script for Windows that tracks what you do on your PC — which apps/windows you have focused and for how long, plus your Chrome/Edge browsing history (tagged separately for YouTube vs general web reading) — and logs it to a CSV file synced through Google Drive.

## Why

For keeping a personal, searchable record of what you read, watched, and worked on each day: date, time, a title, and a URL where applicable.

## How it works

- Runs continuously in the background (registered as a Windows Task Scheduler task that starts at logon).
- Polls the foreground window every 10s to track app/window usage.
- Reads new Chrome/Edge browser history every 5 minutes.
- Buffers everything in memory and flushes to the CSV once a minute.
- Once a day, trims the CSV down to the last 7 days to keep it small.
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
5. Register it to run automatically at logon (requires an elevated/Administrator shell):
   ```
   schtasks /create /tn "PCActivityTracker" /tr "\"<path to pythonw.exe>\" \"<path to pc_activity_tracker.py>\"" /sc onlogon /rl limited /f
   ```

## Managing the scheduled task

```
schtasks /run /tn "PCActivityTracker"      # start now
schtasks /end /tn "PCActivityTracker"      # stop
schtasks /query /tn "PCActivityTracker" /v /fo list   # status
schtasks /delete /tn "PCActivityTracker" /f           # remove entirely
```

## Configuration

All timing is overridable via environment variables (useful for quickly testing changes without waiting on the production intervals):

| Variable | Default | Meaning |
|---|---|---|
| `ACTIVITY_TRACKER_POLL_INTERVAL` | `10` | Seconds between foreground-window checks |
| `ACTIVITY_TRACKER_BROWSER_INTERVAL` | `300` | Seconds between browser-history reads |
| `ACTIVITY_TRACKER_FLUSH_INTERVAL` | `60` | Seconds between CSV flushes |
| `ACTIVITY_TRACKER_PRUNE_INTERVAL` | `86400` | Seconds between retention prune passes |
| `ACTIVITY_TRACKER_RETENTION_DAYS` | `7` | Days of history kept in the CSV |

## Privacy

This tool is meant for personal use, tracking your own machine, and writes only to your own local Drive folder — nothing is sent to any third-party service. Because it reads real browser history, the log will include anything you visited (except incognito/private windows, which browsers never record). Treat the resulting CSV and its Google Drive folder as sensitive personal data.

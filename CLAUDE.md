# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`pc_activity_tracker.py`) that runs as a background Windows process, logging PC activity — foreground app/window usage and browser history — to a CSV file inside a Google Drive sync folder. Only Chrome and Edge are supported (Chromium-based `History` SQLite schema); Firefox and other browsers are not read.

## Commands

- Run directly for manual testing: `python pc_activity_tracker.py` (runs in foreground, Ctrl+C to stop).
- Production launch uses `pythonw.exe pc_activity_tracker.py` instead of `python.exe`, so no console window appears.
- Speed up manual testing via env-var overrides (all default to production-scale intervals otherwise):
  - `ACTIVITY_TRACKER_POLL_INTERVAL` (default `10`) — foreground-window check interval, seconds
  - `ACTIVITY_TRACKER_BROWSER_INTERVAL` (default `300`) — browser-history read interval, seconds
  - `ACTIVITY_TRACKER_FLUSH_INTERVAL` (default `60`) — CSV flush interval, seconds
- No test suite, linter, or build system is configured. Verify changes by running manually with shortened intervals and inspecting `activity_log.csv` and the debug log (paths below).
- Dependencies: `pip install -r requirements.txt` (`psutil`, `pywin32` — imported as `win32gui`, `win32process`). Everything else is stdlib.
- Managing the deployed background task (Windows Task Scheduler, task name `PCActivityTracker`):
  - `schtasks /run /tn "PCActivityTracker"` — start immediately
  - `schtasks /end /tn "PCActivityTracker"` — stop
  - `schtasks /query /tn "PCActivityTracker" /v /fo list` — status
  - `schtasks /delete /tn "PCActivityTracker" /f` — remove
  - Registering/re-registering (`schtasks /create ... /f`) requires an elevated (Run as Administrator) shell on this machine, even though the task itself runs at logon with normal user rights (`/rl limited`). Use `/create /f` to change the task's action, not `schtasks /change` — `/change` reopens a stored-credentials code path that prompts for a run-as password even though this task's logon type never needed one; `/create /f` re-registers the whole task the same way it was first made, with no prompt.

## Architecture

- **Single process, three independently-timed subsystems** inside one `while True` loop in `main()`, each gated by its own "seconds since last run" check rather than separate threads: window-focus polling, browser-history collection, and CSV flush. Each loop iteration is wrapped in its own try/except so one failure (e.g. a locked file) gets logged without killing the background process. The CSV is append-only and never trimmed -- it grows indefinitely.
- **Two storage locations, different purposes**: `DRIVE_DIR` (`G:\My Drive\ActivityTracker`) holds what's meant to be synced/reviewed — `activity_log.csv` and `state.json`. `LOCAL_DIR` (`%LOCALAPPDATA%\ActivityTracker`) holds internal plumbing that shouldn't sync to Drive — the debug log (`tracker.log`) and scratch copies of browser history DBs.
- **Buffered writes, not per-event writes**: rows from window-tracking and browser-history collection accumulate in an in-memory `buffered_rows` list and only hit disk on the flush cycle. `append_rows()` returns success/failure, and the caller only clears the buffer on success — a transient Drive lock retries next flush instead of losing data.
- **Browser history is pulled, not pushed**: Chrome/Edge's live History SQLite file is locked while the browser runs, so it's copied out first, then queried for `visit_time > last_processed`. The cutoff is tracked per-browser in `state.json` (`{browser}_last_visit`, Chrome's WebKit-epoch microsecond format). A browser's first-ever run only backfills the last 24h rather than full history, to avoid dumping months of past browsing into the log at once. `collect_chromium_history()` is shared by both Chrome and Edge since they use the same schema; adding another Chromium-based browser (e.g. Brave) means adding another history-path constant and another `collect_chromium_history()` call — adding a non-Chromium browser (e.g. Firefox) would need a new reader function, since Firefox's `places.sqlite` schema differs.
- **Deployment is a watchdog chain, not a direct launch**: the Task Scheduler task fires `run_tracker_hidden.vbs` (`WScript.Shell.Run(..., 0, False)`, for a fully invisible window) → `run_tracker.bat` (an infinite `start "" /wait pythonw.exe pc_activity_tracker.py` loop with a 10s delay between restarts) → `pc_activity_tracker.py`. `start /wait` is required in the `.bat` because `pythonw.exe` is a GUI-subsystem executable that cmd does not block on by default. This exists because the trigger is "At logon" only (no periodic re-trigger), so without the watchdog, the tracker would silently stay dead until the next real logon if it were ever killed mid-session (observed in practice: the process was killed across a sleep/wake cycle and stayed off for ~18 hours until this was added). The watchdog makes it self-heal within ~10s of dying for any reason, while the logon trigger still handles the cold-start-after-reboot case.

## Conventions

- Every function gets a docstring explaining what it does; the module has a header docstring explaining its overall purpose. Favor small, clearly named, single-purpose functions over long inline blocks.

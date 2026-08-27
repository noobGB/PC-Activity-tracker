# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`pc_activity_tracker.py`) that runs as a background Windows process, logging PC activity — foreground app/window usage and browser history — to a CSV file inside a Google Drive sync folder. Only Chrome and Edge are supported (Chromium-based `History` SQLite schema); Firefox and other browsers are not read. `analysis.py` + `dashboard.py` are a separate, optional Streamlit UI for viewing that CSV on demand — see their own subsection below.

## Commands

- Run directly for manual testing: `python pc_activity_tracker.py` (runs in foreground, Ctrl+C to stop).
- Production launch uses `pythonw.exe pc_activity_tracker.py` instead of `python.exe`, so no console window appears.
- Speed up manual testing via env-var overrides (all default to production-scale intervals otherwise):
  - `ACTIVITY_TRACKER_POLL_INTERVAL` (default `10`) — foreground-window check interval, seconds
  - `ACTIVITY_TRACKER_BROWSER_INTERVAL` (default `300`) — browser-history read interval, seconds
  - `ACTIVITY_TRACKER_FLUSH_INTERVAL` (default `60`) — CSV flush interval, seconds
- No test suite, linter, or build system is configured. Verify changes by running manually with shortened intervals and inspecting `activity_log.csv` and the debug log (paths below).
- Dependencies: `pip install -r requirements.txt` (`psutil`, `pywin32` — imported as `win32gui`, `win32process`; `pandas`, `streamlit` for the dashboard only). Everything else is stdlib.
- Dashboard: `streamlit run dashboard.py` — see the Dashboard section below.
- Managing the deployed background task (Windows Task Scheduler, task name `PCActivityTracker`):
  - `schtasks /run /tn "PCActivityTracker"` — start immediately
  - `stop_tracker.bat` — reliably stop everything (see Architecture below for why `schtasks /end` alone isn't enough)
  - `schtasks /query /tn "PCActivityTracker" /v /fo list` — status
  - `schtasks /delete /tn "PCActivityTracker" /f` — remove (run `stop_tracker.bat` first)
  - Registering/re-registering (`schtasks /create ... /f`) requires an elevated (Run as Administrator) shell on this machine, even though the task itself runs at logon with normal user rights (`/rl limited`). Use `/create /f` to change the task's action, not `schtasks /change` — `/change` reopens a stored-credentials code path that prompts for a run-as password even though this task's logon type never needed one; `/create /f` re-registers the whole task the same way it was first made, with no prompt.

## Architecture

- **Single process, three independently-timed subsystems** inside one `while True` loop in `main()`, each gated by its own "seconds since last run" check rather than separate threads: window-focus polling, browser-history collection, and CSV flush. Each loop iteration is wrapped in its own try/except so one failure (e.g. a locked file) gets logged without killing the background process. The CSV is append-only and never trimmed -- it grows indefinitely.
- **Two storage locations, different purposes**: `DRIVE_DIR` (`G:\My Drive\ActivityTracker`) holds what's meant to be synced/reviewed — `activity_log.csv` and `state.json`. `LOCAL_DIR` (`%LOCALAPPDATA%\ActivityTracker`) holds internal plumbing that shouldn't sync to Drive — the debug log (`tracker.log`) and scratch copies of browser history DBs.
- **Buffered writes, not per-event writes**: rows from window-tracking and browser-history collection accumulate in an in-memory `buffered_rows` list and only hit disk on the flush cycle. `append_rows()` returns success/failure, and the caller only clears the buffer on success — a transient Drive lock retries next flush instead of losing data.
- **Browser history is pulled, not pushed**: Chrome/Edge's live History SQLite file is locked while the browser runs, so it's copied out first, then queried for `visit_time > last_processed`. The cutoff is tracked per-browser in `state.json` (`{browser}_last_visit`, Chrome's WebKit-epoch microsecond format). A browser's first-ever run only backfills the last 24h rather than full history, to avoid dumping months of past browsing into the log at once. `collect_chromium_history()` is shared by both Chrome and Edge since they use the same schema; adding another Chromium-based browser (e.g. Brave) means adding another history-path constant and another `collect_chromium_history()` call — adding a non-Chromium browser (e.g. Firefox) would need a new reader function, since Firefox's `places.sqlite` schema differs.
- **Deployment is a watchdog chain, not a direct launch**: the Task Scheduler task fires `run_tracker_hidden.vbs` (`WScript.Shell.Run(..., 0, True)`, for a fully invisible window) → `run_tracker.bat` (an infinite `start "" /wait pythonw.exe pc_activity_tracker.py` loop with a 10s delay between restarts) → `pc_activity_tracker.py`. `start /wait` is required in the `.bat` because `pythonw.exe` is a GUI-subsystem executable that cmd does not block on by default. This exists because the trigger is "At logon" only (no periodic re-trigger), so without the watchdog, the tracker would silently stay dead until the next real logon if it were ever killed mid-session (observed in practice: the process was killed across a sleep/wake cycle and stayed off for ~18 hours until this was added). The watchdog makes it self-heal within ~10s of dying for any reason, while the logon trigger still handles the cold-start-after-reboot case.
- **`schtasks /end` cannot be trusted to stop the whole chain, even with `Run(..., True)`**: the wait flag on `WScript.Shell.Run` matters for keeping Task Scheduler's own "is this task running" status accurate (with `False`, `wscript.exe` exited the instant it launched `cmd.exe`, and Task Scheduler considered the task complete -- losing track of the now-detached `cmd.exe`/`pythonw.exe` tree entirely, which let a duplicate orphaned instance survive an `/end` + `/run` cycle in practice). But even with `True`, testing showed `schtasks /end` only terminates the single `wscript.exe` process Task Scheduler directly launched -- it does **not** cascade to the `cmd.exe`/`pythonw.exe` children, which survive as orphans. `stop_tracker.bat` is the actual fix: it finds and kills every matching process by command line (`Name -eq 'pythonw.exe'/'python.exe'` AND commandline like `*pc_activity_tracker.py*`; `Name -eq 'cmd.exe'` AND commandline like `*run_tracker.bat*`) rather than relying on Task Scheduler's tracking at all, so it's correct regardless of how many instances or orphans exist. The process-name check in each clause matters: an earlier version matched `*pc_activity_tracker.py*` against *any* process's command line with no name restriction, and killed an unrelated `powershell.exe` that merely mentioned the path.

## Dashboard (`analysis.py` + `dashboard.py`)

- **Categorization logic is separated from UI on purpose**: `analysis.py` has no Streamlit imports and does all loading/categorizing/aggregating; `dashboard.py` only renders. This is so a future CLI report (or a second UI) can reuse the same categorization without redefining it and silently drifting out of agreement -- keep it this way when extending either file.
- **`APP_CATEGORIES`/`DOMAIN_CATEGORIES` in `analysis.py` are manually maintained lookup tables**, not inferred. New processes/domains that show up in your own usage will fall back to an `Other`/`Other: <domain>` bucket rather than erroring -- the dashboard's "Uncategorized domains" expander exists specifically to surface what's fallen into that bucket so you know what to add.
- **`cap_minutes` in `app_usage_with_categories()` exists only because of legacy data**: rows written before the sleep/lock-gap fix (see `technical_notes.md`, issue #1) can carry multi-hour/multi-day single-session durations. The dashboard exposes this as a sidebar slider rather than a hardcoded constant, since capping too aggressively would also clip a genuinely long, uninterrupted session (e.g. hours in the same VS Code window) on data collected after the fix.
- **Streamlit is locked to loopback via `.streamlit/config.toml`** (`server.address = "127.0.0.1"`). Without it, `streamlit run` binds `0.0.0.0` by default and advertises a Network/External URL -- verified by binding without the config first and seeing another interface's IP printed as reachable. This matters here specifically because the CSV is real personal browsing/app-usage history (see README's Privacy section), not because of any general Streamlit best practice.
- **`load_fresh()`'s cache key is `(CSV_PATH, mtime)`**, not just the path -- so the cache only serves stale data between the tracker's own ~60s flush cycles, and the sidebar's "Refresh data" button (which calls `st.cache_data.clear()`) is a manual override for that window, not the only way data ever updates.

## Conventions

- Every function gets a docstring explaining what it does; the module has a header docstring explaining its overall purpose. Favor small, clearly named, single-purpose functions over long inline blocks.

# Technical Notes — activity-tracker

Non-obvious gotchas discovered while working with this project's own code/data, not
general enough for the workspace-root `technical_notes.md`.

## `duration_minutes` was inflated across sleep/lock/logoff gaps (fixed, issue #1)

`WindowTracker._close_session()` computed duration as `end_time - start`, where `start`
is when a window first became foreground and `end_time` is whenever the foreground
window next changes. There was no cap on this interval and no check for a
suspended/locked machine in between.

Effect: if the same window was foreground both right before sleep/lock and right after
wake/unlock (typically `LockApp.exe` — the lock screen itself — or `Unknown` when the
foreground window couldn't be resolved), the entire sleep/lock/away duration got
recorded as if it were active foreground time on that single row.

Observed in a 14-day sample (2026-08-13 to 2026-08-27, 5981 rows): one `Unknown` row
logged a single 7932-minute (5.5 day) "session", and several `LockApp.exe` rows logged
3-38 hour "sessions" — these alone summed to 267 hours against a physical ceiling of
336 hours for the whole 14-day window. Real app usage (VS Code, browsers, etc.) looked
plausible; only the idle/lock/unknown buckets were affected.

**Fix (`WindowTracker.poll()`)**: track the timestamp of the previous poll. If the gap
between two consecutive polls exceeds `IDLE_GAP_SECONDS` (`POLL_INTERVAL * 5`, floor 30s
— far more than a single `sleep(POLL_INTERVAL)` could account for), the machine was
almost certainly asleep/locked/suspended in between. The in-progress session is closed
out as of the *last poll time*, not now, and a fresh session starts at the current time
— so the gap itself is dropped instead of being attributed to whatever window happened
to be focused before/after it. Verified with a mocked-clock test simulating a 1-hour gap
between polls: the pre-gap session closes with its real ~10s duration, the gap
contributes no row at all, and tracking resumes cleanly afterward.

**If analyzing old data collected before this fix**: clip `duration_minutes` at a
reasonable ceiling (e.g. 90 min) before summing per-app time, or exclude
`LockApp.exe`/`Unknown` rows entirely — the bug above still applies to any rows written
before this commit.

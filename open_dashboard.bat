@echo off
REM Double-click launcher for the activity dashboard. Runs from this file's own
REM folder regardless of where it's launched from (%~dp0), so it works from a
REM desktop shortcut too. Leaves the console window open -- unlike the always-on
REM background tracker, this is an on-demand tool you start/stop yourself, so
REM seeing its logs and being able to Ctrl+C (or just close the window) to stop
REM it is useful rather than something to hide.
cd /d "%~dp0"
streamlit run dashboard.py

@echo off
rem Reliably stops the tracker and its watchdog, independent of whatever
rem Task Scheduler thinks is running. Matches processes by command line
rem (every pythonw.exe running pc_activity_tracker.py, every cmd.exe running
rem run_tracker.bat) instead of a single tracked PID, so it also cleans up
rem any orphaned/duplicate instances -- see CLAUDE.md for how those happen.

powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { (($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*pc_activity_tracker.py*') -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run_tracker.bat*') } | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId + ': ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Done.

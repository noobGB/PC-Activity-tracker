@echo off
rem Self-healing launcher for pc_activity_tracker.py.
rem `start /wait` is required: pythonw.exe is a GUI-subsystem executable, so
rem cmd does not block on it by default -- without /wait this loop would
rem spawn unbounded overlapping instances instead of waiting for one to exit.
rem Whenever the tracker exits for any reason (crash, killed on sleep/wake,
rem anything), this relaunches it after a short delay instead of staying dead
rem until the next logon.

:loop
start "" /wait "C:\Users\gaura\AppData\Local\Programs\Python\Python312\pythonw.exe" "c:\Users\gaura\Desktop\Claude\activity-tracker\pc_activity_tracker.py"
timeout /t 10 /nobreak >nul
goto loop

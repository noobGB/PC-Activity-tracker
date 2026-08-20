' Launches run_tracker.bat with a fully hidden window (the 0 flag).
'
' The wait flag is True, not fire-and-forget: run_tracker.bat loops forever,
' so wscript.exe stays alive (blocked) for as long as the watchdog does. This
' keeps Task Scheduler's job tracking for the task alive too, so `schtasks
' /end` can actually find and kill the whole process tree.
'
' With wait=False, wscript.exe used to exit immediately after launching
' cmd.exe, and Task Scheduler considered the task "completed" the moment its
' own process exited -- losing track of the now-detached cmd.exe/pythonw.exe
' tree entirely. In practice this let an orphaned duplicate tracker instance
' survive a `schtasks /end` + `schtasks /run` cycle, running alongside a
' second full instance and double-logging everything.
CreateObject("WScript.Shell").Run """c:\Users\gaura\Desktop\Claude\activity-tracker\run_tracker.bat""", 0, True

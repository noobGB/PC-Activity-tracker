' Launches run_tracker.bat with a fully hidden window (the 0 flag), so
' Task Scheduler running it at logon never flashes/holds open a console.
CreateObject("WScript.Shell").Run """c:\Users\gaura\Desktop\Claude\activity-tracker\run_tracker.bat""", 0, False

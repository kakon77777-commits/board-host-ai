' Launches run_scheduled.ps1 with a fully invisible window (style 0).
' PowerShell's own -WindowStyle Hidden can still flash a console briefly
' on some Windows versions; WScript.Shell.Run with style 0 does not.
' Used as the Task Scheduler action instead of invoking powershell.exe
' directly, so Board Host runs silently without popping a terminal.

Dim shell, scriptDir, psPath
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
psPath = """" & scriptDir & "\run_scheduled.ps1"""

shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & psPath, 0, False

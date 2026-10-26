@echo off
rem Starts Corvis Node automatically when you sign in to Windows, so the hub can use this
rem PC whenever it's on. Run Remove_Node_From_Startup.bat to undo.
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Corvis Node.lnk'); $s.TargetPath='%~dp0Start_Corvis_Node.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (echo Couldn't add it. & goto end)
echo Done. Corvis Node will start (minimized) when you sign in.
:end
pause

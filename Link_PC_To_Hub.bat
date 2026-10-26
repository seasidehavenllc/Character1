@echo off
rem Links this PC to your Corvis hub (run once). You'll need the hub's address and the
rem pairing code the hub installer printed.
title Link PC to Corvis hub
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    call Setup_Corvis.bat
    if errorlevel 1 goto end
)
call .venv\Scripts\activate.bat
python -m corvis link-pc
if errorlevel 1 goto end
echo.
set /p go="Start Corvis Node now? [Y/n] "
if /i "%go%"=="n" goto end
start "" "%~dp0Start_Corvis_Node.bat"
:end
pause

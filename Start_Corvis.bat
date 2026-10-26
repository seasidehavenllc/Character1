@echo off
rem Double-click to open Corvis in your browser (running on this PC).
rem Keep this window open while you use Corvis; close it to shut him down.
title Corvis
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo First run: setting up Corvis...
    call Setup_Corvis.bat
    if errorlevel 1 goto failed
)
call .venv\Scripts\activate.bat

rem Install anything new (e.g. after an update) without bothering you otherwise.
python -c "import starlette, uvicorn, pypdf" 2>nul || pip install -q -r requirements.txt

rem "serve" keeps Corvis running: it restarts him after he updates himself, and undoes
rem an update that stops him from starting.
python -m corvis serve
goto end

:failed
echo Setup failed. Scroll up to see why.

:end
pause

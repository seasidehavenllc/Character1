@echo off
rem Lends this PC to your Corvis hub: files, apps and games, while this window is open.
title Corvis Node
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    call Setup_Corvis.bat
    if errorlevel 1 goto end
)
call .venv\Scripts\activate.bat
python -c "import starlette, uvicorn, pypdf" 2>nul || pip install -q -r requirements.txt
python -m corvis node
:end
pause

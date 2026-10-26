@echo off
rem One-time setup: creates Corvis's Python environment and installs what it needs.
cd /d "%~dp0"
python -m venv .venv || (echo Python not found. Install it from python.org and tick "Add to PATH". & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || exit /b 1
echo.
echo Setup complete. Checking the model connection...
python -m corvis check || echo The model isn't reachable yet. Start Ollama; Corvis will still open.
exit /b 0

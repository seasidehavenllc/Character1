@echo off
rem Installs private voice input: your speech is turned into text on this PC (Whisper).
title Corvis voice setup
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" call Setup_Corvis.bat
call .venv\Scripts\activate.bat
pip install faster-whisper
if errorlevel 1 (
    echo.
    echo Couldn't install it. faster-whisper may not support this Python version yet.
    echo Corvis will keep using your browser's speech recognition for the mic.
    goto end
)
echo.
echo Done. Restart Corvis; the mic now works privately on this PC.
echo The first time you use it, the speech model downloads once (about 150 MB).
:end
pause

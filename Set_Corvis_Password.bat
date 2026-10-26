@echo off
rem Sets the owner password used to sign in to Corvis from your phone or other devices.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" call Setup_Corvis.bat
call .venv\Scripts\activate.bat
python -m corvis set-password
pause

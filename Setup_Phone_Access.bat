@echo off
rem Sets up Corvis on your phone through Tailscale: password, HTTPS, config. Step by step.
title Corvis phone setup
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" call Setup_Corvis.bat
call .venv\Scripts\activate.bat
python -m corvis phone-setup
pause

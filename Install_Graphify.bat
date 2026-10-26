@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional Graphify knowledge-graph CLI for Corvis...
echo Official project: https://github.com/Graphify-Labs/graphify
echo This does not install or send your project to a cloud service.
where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv was not found on PATH.
  echo Install uv from https://docs.astral.sh/uv/getting-started/installation/ then run this script again.
  pause
  exit /b 1
)
uv tool install graphifyy
if errorlevel 1 (
  echo Graphify installation failed. Review the error above.
  pause
  exit /b 1
)
echo.
echo Graphify installed. If Corvis was already running, restart it so it detects the CLI.
echo Open Mission Control and use the Graphify knowledge graph panel.
pause

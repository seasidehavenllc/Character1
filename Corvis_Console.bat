@echo off
rem Terminal version of Corvis. Starts from wherever this folder lives (no hard-coded paths).
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo First run: setting up Corvis...
    call Setup_Corvis.bat
    if errorlevel 1 goto end
)
call .venv\Scripts\activate.bat

echo.
echo   1. Work on a project
echo   2. Improve Corvis itself (safe self-edit)
echo   3. Check the model connection
echo.
set /p choice="Choose 1, 2 or 3: "
if "%choice%"=="1" goto project
if "%choice%"=="2" goto selfedit
goto check

:project
set /p repo="Project folder (paste the path): "
python -m corvis code --repo "%repo%"
goto end

:selfedit
python -m corvis self-edit
goto end

:check
python -m corvis check

:end
pause

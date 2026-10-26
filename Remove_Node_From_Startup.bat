@echo off
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Corvis Node.lnk" 2>nul && echo Removed. || echo It wasn't in startup.
pause

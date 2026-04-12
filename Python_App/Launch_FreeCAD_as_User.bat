@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "UI_Launcher.py" --launch-as-user
    goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "UI_Launcher.py" --launch-as-user
    goto :eof
)

echo Python was not found in PATH.
pause

@echo off
setlocal
cd /d "%~dp0"
py -3 UI_Launcher.py
if errorlevel 1 python UI_Launcher.py
endlocal

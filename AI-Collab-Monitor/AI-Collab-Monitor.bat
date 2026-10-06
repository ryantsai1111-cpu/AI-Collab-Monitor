@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-monitor.ps1"
set "monitorExit=%ERRORLEVEL%"
if not "%monitorExit%"=="0" pause
exit /b %monitorExit%

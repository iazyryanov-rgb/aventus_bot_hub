@echo off
setlocal
cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "HUB=%~dp0AventusBotHub.ps1"
if /i "%~1"=="console" goto :console
REM -WindowStyle Hidden — без чёрного окна PowerShell (только форма WinForms).
start "Aventus Bot Hub" /D "%~dp0" "%PSX%" -NoProfile -ExecutionPolicy Bypass -Sta -NoLogo -WindowStyle Hidden -File "%HUB%"
exit /b 0
:console
"%PSX%" -NoProfile -ExecutionPolicy Bypass -Sta -NoLogo -File "%HUB%"
if errorlevel 1 pause
exit /b %ERRORLEVEL%

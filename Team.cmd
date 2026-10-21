@echo off
setlocal
if "%~1"=="" goto interactive
if /i "%~1"=="--help" goto help
powershell.exe -NoLogo -NoProfile -File "%~dp0Team.ps1" %*
exit /b %errorlevel%
:help
powershell.exe -NoLogo -NoProfile -File "%~dp0Team.ps1" -Action help
exit /b %errorlevel%
:interactive
powershell.exe -NoLogo -NoProfile -File "%~dp0Team.ps1"
set "team_exit=%errorlevel%"
echo.
pause
exit /b %team_exit%

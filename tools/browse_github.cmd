@echo off
rem ============================================================================
rem  Open GitHub in Edge through the local DNS-fix proxy.
rem  No admin rights and no system changes needed.
rem
rem   Step 1: start the proxy in another window:
rem             python tools\github_proxy.py
rem   Step 2: double-click this file (optionally pass a URL as argument)
rem ============================================================================
setlocal
set "PROXY=127.0.0.1:8899"
set "URL=%~1"
if "%URL%"=="" set "URL=https://github.com/YHSome/oj-ojojoj"
set "PROFILE=%TEMP%\oj-github-proxy"

echo Checking proxy %PROXY% ...
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8899);$c.Close();'OK'}catch{'DOWN'}" > "%TEMP%\_ojproxystate.txt"
set /p STATE=<"%TEMP%\_ojproxystate.txt"
if not "%STATE%"=="OK" (
  echo.
  echo [!] The local proxy is not running yet. Please run this first:
  echo         python tools\github_proxy.py
  echo     then double-click this file again.
  echo.
  pause
  exit /b 1
)

set "EDGE="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if not defined EDGE (
  echo Edge not found. Opening with the default browser instead.
  echo Remember to set the proxy manually to %PROXY%
  start "" "%URL%"
  exit /b 0
)

echo Opening %URL% via proxy %PROXY% (separate profile, your normal browser is untouched)
start "" "%EDGE%" --proxy-server="%PROXY%" --user-data-dir="%PROFILE%" --no-first-run "%URL%"
exit /b 0

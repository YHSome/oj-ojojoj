@echo off
rem ============================================================================
rem  OJ judge backend one-click switch.
rem    double-click            -> toggle (start if stopped, stop if running)
rem    oj_service.cmd status   -> show status only
rem    oj_service.cmd start|stop|restart|watch|shortcut|install|uninstall
rem ============================================================================
setlocal
set "OJ_PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%OJ_PY%" set "OJ_PY=python"
set "OJ_ROOT=%~dp0.."
set "ACT=%~1"
if "%ACT%"=="" set "ACT=toggle"
chcp 65001 >nul
"%OJ_PY%" "%OJ_ROOT%\tools\oj_service.py" %ACT% %2 %3
echo.
if "%ACT%"=="toggle" timeout /t 3 >nul

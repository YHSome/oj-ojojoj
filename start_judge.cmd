@echo off
rem ============================================================
rem  OJ-OJOJOJ 判题机启动脚本（常驻，Ctrl+C 优雅退出）
rem ============================================================
setlocal
set "OJ_PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%OJ_PY%" set "OJ_PY=python"
set "OJ_ROOT=%~dp0"
cd /d "%OJ_ROOT%\backend"

echo [OJ] python = %OJ_PY%
echo [OJ] root   = %OJ_ROOT%

"%OJ_PY%" "%OJ_ROOT%tools\selfcheck.py"
echo.
echo [OJ] 启动判题机（workers=4）...
"%OJ_PY%" "%OJ_ROOT%backend\daemon.py" --workers 4 -v %*
pause

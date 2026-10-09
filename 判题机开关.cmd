@echo off
rem ============================================================================
rem  OJ 判题机 一键开关（命令行版；图形版见 OJ中控台.exe）
rem    双击本文件：在跑就停，没跑就起（等价 tools\oj_service.py toggle）
rem    想放桌面：直接把本文件拖到桌面（内部会自动定位仓库目录）
rem    其它用法：判题机开关.cmd status | start | stop | restart | watch
rem ============================================================================
title OJ 判题机开关
setlocal
set "OJ_ROOT=%~dp0"
if not exist "%OJ_ROOT%tools\oj_service.py" set "OJ_ROOT=D:\OJ\"
set "OJ_PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%OJ_PY%" set "OJ_PY=python"
set "ACT=%~1"
if "%ACT%"=="" set "ACT=toggle"

echo [OJ] 仓库目录 = %OJ_ROOT%
"%OJ_PY%" "%OJ_ROOT%tools\oj_service.py" %ACT%
set RC=%ERRORLEVEL%
echo.
if "%ACT%"=="toggle" (
  echo 本窗口 4 秒后自动关闭。图形界面：双击 OJ中控台.exe
  timeout /t 4 >nul
) else (
  pause
)
exit /b %RC%

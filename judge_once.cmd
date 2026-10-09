@echo off
rem 判完当前队列就退出，适合放进 Windows 计划任务（每 1 分钟一次）
setlocal
set "OJ_PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%OJ_PY%" set "OJ_PY=python"
set "OJ_ROOT=%~dp0"
"%OJ_PY%" "%OJ_ROOT%backend\daemon.py" --once --quiet %*

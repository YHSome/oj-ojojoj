@echo off
rem ============================================================================
rem  Fix github.com DNS pollution by pinning a working IP in the hosts file.
rem  Just double-click this file. It will ask for administrator rights.
rem
rem    fix_hosts_admin.cmd           add the fix
rem    fix_hosts_admin.cmd revert    undo the fix
rem    fix_hosts_admin.cmd dry       show what would be written
rem ============================================================================
setlocal
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0fix_hosts_admin.ps1','%1' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_hosts_admin.ps1" %1
echo.
pause

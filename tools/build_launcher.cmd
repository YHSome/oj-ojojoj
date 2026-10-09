@echo off
rem ============================================================================
rem  编译 OJ 一键启动器（用 Windows 自带的 C# 编译器，不需要装任何东西）
rem  产物： D:\OJ\OJ中控台.exe
rem ============================================================================
setlocal
set "CSC=%windir%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%windir%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo 找不到 csc.exe，请确认已安装 .NET Framework 4.x
  pause
  exit /b 1
)

set "SRC=%~dp0launcher\OJLauncher.cs"
set "OUT=%~dp0..\OJ中控台.exe"

echo 编译: %SRC%
echo 输出: %OUT%
"%CSC%" /nologo /target:winexe /codepage:65001 /optimize+ /out:"%OUT%" ^
  /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll ^
  "%SRC%"
if errorlevel 1 (
  echo 编译失败
  pause
  exit /b 1
)
echo.
echo 编译成功: %OUT%
pause

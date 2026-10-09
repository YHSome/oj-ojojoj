# -*- coding: utf-8 -*-
"""用 GBK 写 .cmd（cmd.exe 按 OEM 代码页读批处理，UTF-8 中文会让解析器错乱）。

    python tools/write_gbk_cmds.py       # 重新生成下面两个批处理
        D:\\OJ\\判题机开关.cmd
        D:\\OJ\\tools\\build_launcher.cmd
"""
import os

ROOT = r"D:\OJ"
PY = r"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

SWITCH = [
    "@echo off",
    "rem ============================================================================",
    "rem  OJ 判题机 一键开关（命令行版；图形版见 OJ中控台.exe）",
    "rem    双击本文件：在跑就停，没跑就起（等价 tools\\oj_service.py toggle）",
    "rem    想放桌面：直接把本文件拖到桌面（内部会自动定位仓库目录）",
    "rem    其它用法：判题机开关.cmd status | start | stop | restart | watch",
    "rem ============================================================================",
    "title OJ 判题机开关",
    "setlocal",
    'set "OJ_ROOT=%~dp0"',
    'if not exist "%OJ_ROOT%tools\\oj_service.py" set "OJ_ROOT=' + ROOT + '\\"',
    'set "OJ_PY=' + PY + '"',
    'if not exist "%OJ_PY%" set "OJ_PY=python"',
    'set "ACT=%~1"',
    'if "%ACT%"=="" set "ACT=toggle"',
    "",
    "echo [OJ] 仓库目录 = %OJ_ROOT%",
    '"%OJ_PY%" "%OJ_ROOT%tools\\oj_service.py" %ACT%',
    "set RC=%ERRORLEVEL%",
    "echo.",
    'if "%ACT%"=="toggle" (',
    "  echo 本窗口 4 秒后自动关闭。图形界面：双击 OJ中控台.exe",
    "  timeout /t 4 >nul",
    ") else (",
    "  pause",
    ")",
    "exit /b %RC%",
    "",
]

BUILD = [
    "@echo off",
    "rem ============================================================================",
    "rem  编译 OJ 一键启动器（用 Windows 自带的 C# 编译器，不需要装任何东西）",
    "rem  产物： D:\\OJ\\OJ中控台.exe",
    "rem ============================================================================",
    "setlocal",
    'set "CSC=%windir%\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe"',
    'if not exist "%CSC%" set "CSC=%windir%\\Microsoft.NET\\Framework\\v4.0.30319\\csc.exe"',
    "if not exist \"%CSC%\" (",
    "  echo 找不到 csc.exe，请确认已安装 .NET Framework 4.x",
    "  pause",
    "  exit /b 1",
    ")",
    "",
    'set "SRC=%~dp0launcher\\OJLauncher.cs"',
    'set "OUT=%~dp0..\\OJ中控台.exe"',
    "",
    "echo 编译: %SRC%",
    "echo 输出: %OUT%",
    '"%CSC%" /nologo /target:winexe /codepage:65001 /optimize+ /out:"%OUT%" ^',
    "  /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll ^",
    '  "%SRC%"',
    "if errorlevel 1 (",
    "  echo 编译失败",
    "  pause",
    "  exit /b 1",
    ")",
    "echo.",
    "echo 编译成功: %OUT%",
    "pause",
    "",
]


def write(path, lines):
    with open(path, "w", encoding="gbk", newline="\r\n") as f:
        f.write("\n".join(lines))
    print("已写入 %s（%d 字节）" % (path, os.path.getsize(path)))


def main():
    write(os.path.join(ROOT, "判题机开关.cmd"), SWITCH)
    write(os.path.join(ROOT, "tools", "build_launcher.cmd"), BUILD)


if __name__ == "__main__":
    main()

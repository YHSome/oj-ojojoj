# -*- coding: utf-8 -*-
"""用 GBK 写 .cmd（cmd.exe 按 OEM 代码页读批处理，UTF-8 中文会让解析器错乱）。

    python tools/write_gbk_cmd.py
"""
import os

ROOT = r"D:\OJ"
PY = r"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

LINES = [
    "@echo off",
    "rem ============================================================================",
    "rem  OJ 判题机 一键开关",
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
    "  echo 本窗口 4 秒后自动关闭。看详细日志：tools\\oj.sh console 打开中控台。",
    "  timeout /t 4 >nul",
    ") else (",
    "  pause",
    ")",
    "exit /b %RC%",
    "",
]


def main():
    path = os.path.join(ROOT, "判题机开关.cmd")
    with open(path, "w", encoding="gbk", newline="\r\n") as f:
        f.write("\n".join(LINES))
    print("已写入（GBK）:", path)
    print("大小:", os.path.getsize(path), "字节")
    with open(path, "r", encoding="gbk") as f:
        print("\n前 4 行预览:")
        for i, line in enumerate(f):
            if i >= 4:
                break
            print("   ", line.rstrip())


if __name__ == "__main__":
    main()

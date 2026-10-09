# -*- coding: utf-8 -*-
"""编译 OJ 一键启动器（Windows 自带 csc.exe，无需安装任何东西）。

    python tools/build_launcher.py

为什么用 Python 而不是批处理：批处理里的中文会按 OEM 代码页传给编译器，
生成的文件名会变成乱码（实测 OJ中控台.exe -> OJ\ufffdп\ufffd\u0328.exe）。
Python 用 Unicode 参数调用进程，路径完全正确。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "launcher", "OJLauncher.cs")
OUT_NAME = "OJ中控台.exe"
OUT = os.path.join(ROOT, OUT_NAME)
TMP_ASCII = os.path.join(ROOT, "_oj_launcher_build.exe")   # csc 只写 ASCII 名

CSC_CANDIDATES = [
    os.path.join(os.environ.get("windir", r"C:\Windows"),
                 r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    os.path.join(os.environ.get("windir", r"C:\Windows"),
                 r"Microsoft.NET\Framework\v4.0.30319\csc.exe"),
]


def find_csc():
    for p in CSC_CANDIDATES:
        if os.path.isfile(p):
            return p
    # 兜底：在 .NET 目录里搜
    base = os.path.join(os.environ.get("windir", r"C:\Windows"), "Microsoft.NET")
    for dirpath, _dirs, files in os.walk(base):
        if "csc.exe" in files:
            return os.path.join(dirpath, "csc.exe")
    return None


def compile_to(csc, out_path):
    cmd = [csc, "/nologo", "/target:winexe", "/codepage:65001", "/optimize+",
           "/out:" + out_path,
           "/reference:System.dll", "/reference:System.Drawing.dll",
           "/reference:System.Windows.Forms.dll", SRC]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def main():
    csc = find_csc()
    if not csc:
        print("找不到 csc.exe：请确认已安装 .NET Framework 4.x")
        return 1
    if not os.path.isfile(SRC):
        print("找不到源码:", SRC)
        return 1

    # 清掉可能存在的乱码文件名（早期批处理编译留下的）
    for name in os.listdir(ROOT):
        if name.endswith(".exe") and name.startswith("OJ") and name != OUT_NAME:
            try:
                os.remove(os.path.join(ROOT, name))
                print("已删除旧产物:", name)
            except OSError:
                pass
    if os.path.isfile(TMP_ASCII):
        try:
            os.remove(TMP_ASCII)
        except OSError:
            pass

    print("编译器:", csc)
    print("源码  :", SRC)
    print("输出  :", OUT)

    # 先直接编到仓库里
    rc, log = compile_to(csc, TMP_ASCII)
    if rc != 0 or not os.path.isfile(TMP_ASCII):
        # D:\OJ 目录带 Everyone:(CI)(DENY)(DC)，csc 的"临时文件+改名"写法会被拒
        # → 退到系统临时目录编译，再拷回来（DSH 沙箱下 TEMP 也不可写，故容错处理）
        tmpdir = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp",
                              "ojbuild")
        try:
            os.makedirs(tmpdir, exist_ok=True)
        except OSError as e:
            for line in (log or "").splitlines():
                print("   " + line)
            print("\n编译失败，且临时目录不可写（%r）：%s" % (e, tmpdir))
            print("提示：本仓库目录带 DENY(Delete-Child) 的 ACL 时 csc 无法直接写产物；")
            print("      在普通用户环境下重跑本脚本即可，或改用 PowerShell 编译：")
            print('      & "$env:windir\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe" '
                  '/target:winexe /codepage:65001 /out:"%s" '
                  '/reference:System.dll /reference:System.Drawing.dll '
                  '/reference:System.Windows.Forms.dll "%s"' % (OUT, SRC))
            return 1
        alt = os.path.join(tmpdir, "OJLauncher.exe")
        if os.path.isfile(alt):
            os.remove(alt)
        print("\n直接编译失败（%s），改为在临时目录编译再拷回：%s" % (log.splitlines()[0][:90] if log else "未知", alt))
        rc2, log2 = compile_to(csc, alt)
        if rc2 != 0 or not os.path.isfile(alt):
            for line in (log2 or log).splitlines():
                print("   " + line)
            print("编译失败")
            return 1
        if not TMP_ASCII.lower().endswith("_oj_launcher_build.exe"):
            pass
        tmp_target = os.path.join(ROOT, "_oj_launcher_build.exe")
        import shutil
        shutil.copyfile(alt, tmp_target)
        print("   已拷回:", tmp_target)
    else:
        for line in (log or "").splitlines():
            print("   " + line)

    # csc/沙箱都不愿意直接写中文名：先落 ASCII 名，再改名
    try:
        if os.path.isfile(OUT):
            os.remove(OUT)
        os.replace(TMP_ASCII, OUT)
    except OSError as e:
        print("改名失败（%r），保留 ASCII 名：%s" % (e, TMP_ASCII))
        out_actual = TMP_ASCII
    else:
        out_actual = OUT
    print("\n编译成功: %s（%d 字节）" % (out_actual, os.path.getsize(out_actual)))
    print("双击即：启动判题机 + 启动中控台 + 打开浏览器")
    return 0


if __name__ == "__main__":
    sys.exit(main())

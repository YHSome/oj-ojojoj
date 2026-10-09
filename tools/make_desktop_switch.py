# -*- coding: utf-8 -*-
"""桌面一键开关：优先建 .lnk，失败就退化成 .cmd（都能双击运行）。"""
import os
import subprocess
import sys

ROOT = r"D:\OJ"
DESKTOP_CANDIDATES = [
    os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
    os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "Desktop"),
    os.path.join(os.environ.get("USERPROFILE", ""), "桌面"),
]
PY = sys.executable

desktop = None
for d in DESKTOP_CANDIDATES:
    if os.path.isdir(d):
        desktop = d
        break
print("桌面目录:", desktop)

if not desktop:
    raise SystemExit("找不到桌面目录")

# 1) 先试直接写文件（判断到底能不能写桌面）
probe = os.path.join(desktop, "_oj_write_test.txt")
try:
    with open(probe, "w", encoding="utf-8") as f:
        f.write("ok")
    os.remove(probe)
    writable = True
    print("  桌面可写: ✔")
except OSError as e:
    writable = False
    print("  桌面可写: ✘ %r" % e)

if not writable:
    print("\n结论：脚本无法直接写桌面（沙箱/权限限制）。")
    print("请手动把这个文件拖到桌面：")
    print("   %s" % os.path.join(ROOT, "tools", "oj_toggle_on_desktop.cmd"))
    raise SystemExit(2)

# 2) 纯 ASCII 名字 + 简单路径再试一次 .lnk
lnk = os.path.join(desktop, "OJ-Judge.lnk")
target = os.path.join(ROOT, "tools", "oj_service.cmd")
ps = ("$w=New-Object -ComObject WScript.Shell;"
      "$s=$w.CreateShortcut('%s');"
      "$s.TargetPath='%s';$s.Arguments='toggle';"
      "$s.WorkingDirectory='%s';"
      "$s.IconLocation='%%SystemRoot%%\\System32\\shell32.dll,137';"
      "$s.Save()" % (lnk, target, ROOT))
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True, timeout=60)
if os.path.isfile(lnk):
    print("  ✔ 已建快捷方式:", lnk)
    raise SystemExit(0)

print("  .lnk 失败:", (r.stderr or r.stdout).strip()[:200])

# 3) 退化成 .cmd（双击即可）
cmd = os.path.join(desktop, "OJ-Judge.cmd")
body = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    "title OJ 判题机开关\r\n"
    '"%s" "%s\\tools\\oj_service.py" %%*\r\n'
    "if \"%%1\"==\"\" timeout /t 4 >nul\r\n" % (PY, ROOT)
)
with open(cmd, "w", encoding="gbk", errors="replace") as f:
    f.write(body)
print("  ✔ 已建桌面启动器:", cmd)

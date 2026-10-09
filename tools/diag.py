# -*- coding: utf-8 -*-
"""诊断：1) 编译器子程序能否被 spawn（cwd 影响） 2) 云端 res: 标签原始返回为何解析失败。"""
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import runner

BIN = r"D:\OJ\tools\w64devkit\bin"
CC1 = r"D:\OJ\tools\w64devkit\libexec\gcc\x86_64-w64-mingw32\14.1.0\cc1plus.exe"
print("cc1plus 存在:", os.path.isfile(CC1), CC1)
print("libexec 目录:", os.path.isdir(os.path.dirname(CC1)))

work = os.path.join(ROOT, "data", "work", "_diag")
os.makedirs(work, exist_ok=True)
src = os.path.join(work, "main.cpp")
with open(src, "w", encoding="utf-8") as f:
    f.write('#include <cstdio>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}\n')

env = {"PATH": BIN + os.pathsep + os.environ.get("PATH", ""),
       "TMP": os.path.join(ROOT, "data", "tmp"),
       "TEMP": os.path.join(ROOT, "data", "tmp"),
       "TMPDIR": os.path.join(ROOT, "data", "tmp")}

for label, cwd in (("cwd=workdir(正确做法)", work), ("cwd=toolchain_bin(当前 bug)", BIN)):
    exe = os.path.join(work, "a.exe")
    ok, log, ms = runner.compile_program(
        [os.path.join(BIN, "g++.exe"), "-O2", "-std=c++17", "-static", "-o", exe, src],
        cwd=cwd, timeout_ms=15000, log_max=4096, env=env)
    print("\n[%s] ok=%s %sms\n  log=%s" % (label, ok, ms, log.replace("\n", "\n  ")))

print("\n== res: 标签原始返回 ==")
for tag in ("res:516815821", "sub:516815821"):
    body = urllib.parse.urlencode({"user": "YOUR_USER", "secret": "YOUR_SECRET",
                                   "action": "get", "tag": tag}).encode()
    req = urllib.request.Request("http://tinywebdb.appinventor.space/api", data=body)
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    print("[%s] 长度=%d" % (tag, len(raw)))
    print("  原始:", raw[:400])
    try:
        json.loads(raw)
        print("  json OK")
    except Exception as e:
        print("  json FAIL:", e)
        pos = getattr(e, "pos", None)
        if pos is not None:
            print("  出错位置附近:", repr(raw[max(0, pos - 60):pos + 60]))
        # 找出非法字符
        for i, ch in enumerate(raw):
            if ord(ch) < 0x20:
                print("  第 %d 个字符是控制字符 0x%02X" % (i, ord(ch)))
                break

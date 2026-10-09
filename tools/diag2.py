# -*- coding: utf-8 -*-
"""复核：干净环境下 g++ 能否编译 + 单引号安全编码修复后云端读写是否正常。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import config as ojconfig
import judge as ojjudge
import runner
import store as store_mod

cfg = ojconfig.load()
cfg.setv("paths.python", sys.executable)
J = ojjudge.Judge(cfg, lambda lvl, m: print("[%s] %s" % (lvl, m)))
env = J._toolchain_env()
print("PATH 前 3 段:", env["PATH"].split(os.pathsep)[:3])
print("TMP:", env.get("TMP"))
print("PATH 里有 MSYS 形态吗:", any(p.startswith("/") for p in env["PATH"].split(os.pathsep)))

work = os.path.join(ROOT, "data", "work", "_diag")
os.makedirs(work, exist_ok=True)
src = os.path.join(work, "main.cpp")
with open(src, "w", encoding="utf-8") as f:
    f.write('#include <cstdio>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}\n')
exe = os.path.join(work, "a.exe")
ok, log, ms = runner.compile_program(
    [os.path.join(r"D:\OJ\tools\w64devkit\bin", "g++.exe"), "-O2", "-std=c++17", "-static",
     "-o", exe, src], cwd=work, timeout_ms=20000, env=env, env_replace=True)
print("编译 ok=%s %sms log=%r" % (ok, ms, log[:200]))

if ok:
    r = runner.run_process([exe], cwd=work, stdin_path=os.devnull,
                           stdout_path=os.path.join(work, "o.txt"),
                           stderr_path=os.path.join(work, "e.txt"),
                           time_limit_ms=3000, env=env, env_replace=True)
    print("运行:", r.status, r.time_ms, "ms")

print("\n== 安全编码往返（含单引号） ==")
for s in ["it's ok", "gcc: cannot execute 'x'", "a'b\"c\\d", "line1\nline2"]:
    e = store_mod.safe(s)
    assert store_mod.unsafe(e) == s, (s, e)
    print("  %-30r -> %r  往返OK" % (s, e))

print("\n== 云端实写实读（单引号） ==")
from twdb import TinyWebDB
db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
               min_interval_s=0.5, retries=4)
st = store_mod.Store(db, cfg)
val = {"msg": "gcc: cannot execute 'cc1plus.exe': boom", "cases": [{"i": 1, "note": "it's\nok"}]}
st.put_json("t:safecheck", val)
back = st.get_json("t:safecheck", None)
print("  写入:", json.dumps(val, ensure_ascii=False))
print("  读回:", json.dumps(back, ensure_ascii=False))
print("  一致:", back == val)
db.delete("t:safecheck")

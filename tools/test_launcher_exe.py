# -*- coding: utf-8 -*-
"""验证 OJ中控台.exe 的命令行模式（GUI 子系统 exe 从 shell 启动是异步的，所以要等）。"""
import json
import os
import subprocess
import time
import urllib.request

EXE = r"D:\OJ\OJ中控台.exe"
LOG = r"D:\OJ\logs\launcher.log"


def run_exe(*args, wait=12):
    """启动 exe（不阻塞），等一会儿，再读它写的日志尾部。"""
    before = os.path.getsize(LOG) if os.path.isfile(LOG) else 0
    subprocess.Popen([EXE] + list(args), close_fds=True)
    time.sleep(wait)
    with open(LOG, "r", encoding="utf-8", errors="replace") as f:
        f.seek(before)
        return f.read().strip()


def http(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}),
                                    timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:90]


print("=" * 72)
print("1) 中控台页面")
print("=" * 72)
st, body = http("http://127.0.0.1:8090/")
print("  GET /                     ->", st)
st2, body2 = http("http://127.0.0.1:8090/api/status", {"X-OJ-Console": "1"})
print("  GET /api/status (带头)    ->", st2)
if st2 == 200:
    d = json.loads(body2)
    print("     字段:", ", ".join(list(d.keys())[:10]))
    if d.get("cluster"):
        print("     集群:", d["cluster"].get("judges"), "台，空闲", d["cluster"].get("free"))

print()
print("=" * 72)
print("2) exe --status")
print("=" * 72)
print(run_exe("--status", wait=6))

print("=" * 72)
print("3) exe --stop（全部停止）")
print("=" * 72)
print(run_exe("--stop", wait=20))
st3, _ = http("http://127.0.0.1:8090/")
print("  停止后再访问中控台 ->", st3 if st3 else "连不上（符合预期）")

print()
print("=" * 72)
print("4) exe --start --no-browser（重新拉起）")
print("=" * 72)
print(run_exe("--start", "--no-browser", wait=30))
st4, _ = http("http://127.0.0.1:8090/")
print("  中控台 ->", st4 if st4 else "没起来")
print("  launcher.log 尾部:")
for line in open(LOG, encoding="utf-8", errors="replace").read().strip().splitlines()[-6:]:
    print("     ", line)

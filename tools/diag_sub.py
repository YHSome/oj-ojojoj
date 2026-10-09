# -*- coding: utf-8 -*-
"""诊断一次加密提交的落地状态：云端标签 + 本地编译日志。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import config as ojconfig
from store import Store
from twdb import TinyWebDB

sid = sys.argv[1]
cfg = ojconfig.load()
db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
               min_interval_s=0.5, retries=4)
store = Store(db, cfg)

print("== 云端标签 ==")
for tag in ("code:%s" % sid, "code:%s:0" % sid, "sub:%s" % sid, "q:%s" % sid,
            "res:%s" % sid, "res:%s:0" % sid):
    raw = db.get(tag, None)
    if raw is None:
        print("  %-22s -> (不存在)" % tag)
    else:
        print("  %-22s -> %s" % (tag, raw[:220]))

print("\n== 本地工作目录 ==")
work = os.path.join(cfg.path("work"), sid)
if os.path.isdir(work):
    for name in sorted(os.listdir(work)):
        p = os.path.join(work, name)
        if os.path.isfile(p):
            print("  %-20s %8d 字节" % (name, os.path.getsize(p)))
        else:
            print("  %-20s <目录>" % name)
    for logname in ("__compile.log", "__compile.log.err"):
        p = os.path.join(work, logname)
        if os.path.isfile(p):
            print("\n  --- %s ---" % logname)
            print("  " + open(p, encoding="utf-8", errors="replace").read()[:1500].replace("\n", "\n  "))
    src = os.path.join(work, "main.cpp")
    if os.path.isfile(src):
        print("\n  --- 解密后落盘的源码（前 400 字） ---")
        print("  " + open(src, encoding="utf-8", errors="replace").read()[:400].replace("\n", "\n  "))
else:
    print("  (%s 不存在)" % work)

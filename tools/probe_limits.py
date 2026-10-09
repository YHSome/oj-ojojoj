# -*- coding: utf-8 -*-
"""测量云端 KV 的硬限制：单值长度上限 / search 条数上限 / 标签名长度。

这是架构的硬约束，必须实测：
  * search 单次 100 条（已知）
  * 单值长度上限  ?   ← 本脚本测
  * 是否存在静默截断
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from twdb import TinyWebDB

db = TinyWebDB("http://tinywebdb.appinventor.space/api", "YOUR_USER", "YOUR_SECRET",
               min_interval_s=0.5, retries=4)

print("== 单值长度上限（发送 N 个 'A'，看读回多少） ==")
for n in (50, 100, 120, 128, 150, 200, 255, 256, 300, 512, 1000, 2000, 5000):
    tag = "lim:%d" % n
    db.update(tag, "A" * n)
    raw = db.get(tag, None)
    got = len(raw) if isinstance(raw, str) else -1
    print("  send=%-5d got=%-5d %s" % (n, got, "OK" if got == n else "截断/失败"))

print("\n== UTF-8 中文长度（每字 3 字节） ==")
for n in (40, 50, 60, 80, 100, 200):
    tag = "limc:%d" % n
    db.update(tag, "中" * n)
    raw = db.get(tag, None)
    got = len(raw) if isinstance(raw, str) else -1
    print("  汉字数=%-4d 字符=%s 字节=%s 读回字符=%s %s"
          % (n, n, n * 3, got, "OK" if got == n else "截断"))

print("\n== 标签名长度 ==")
for n in (20, 50, 100, 200):
    tag = ("T" + "x" * n)[:n]
    db.update(tag, "v")
    got = db.get(tag, None)
    print("  长度=%-4d 读回=%r" % (n, got))

print("\n== 清理 ==")
for n in (50, 100, 120, 128, 150, 200, 255, 256, 300, 512, 1000, 2000, 5000):
    db.delete("lim:%d" % n)
for n in (40, 50, 60, 80, 100, 200):
    db.delete("limc:%d" % n)
for n in (20, 50, 100, 200):
    db.delete(("T" + "x" * n)[:n])
print("done")

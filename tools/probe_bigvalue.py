# -*- coding: utf-8 -*-
"""测云端单值上限（更大范围），决定密文信封是否需要拆成多个标签。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from twdb import TinyWebDB

db = TinyWebDB("http://tinywebdb.appinventor.space/api", "YOUR_USER", "YOUR_SECRET",
               min_interval_s=0.5, retries=4)


def probe(name, alphabet, sizes):
    print("== %s ==" % name)
    for n in sizes:
        tag = "big:%s:%d" % (name, n)
        val = (alphabet * (n // len(alphabet) + 1))[:n]
        db.update(tag, val)
        raw = db.get(tag, None)
        got = len(raw) if isinstance(raw, str) else -1
        print("  send=%-7d got=%-7d %s" % (n, got, "OK" if got == n else "❌ 截断/丢失"))
        try:
            db.delete(tag)
        except Exception:  # noqa: BLE001
            pass


probe("base64", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", 
      [5000, 10000, 20000, 30000, 50000, 100000])
probe("json", '{"a":"b",', [5000, 20000, 50000])

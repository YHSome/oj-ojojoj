# -*- coding: utf-8 -*-
"""探测 delete 的真实语义：是"真删除"还是"软删除（写 null）"？"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from twdb import TinyWebDB

db = TinyWebDB("http://tinywebdb.appinventor.space/api", "YOUR_USER", "YOUR_SECRET",
               min_interval_s=0.5, retries=4)

print("before count:", db.count())
db.update("delprobe:1", "hello")
db.update("delprobe:2", "world")
print("after write :", db.count(), db.get("delprobe:1"))
db.delete("delprobe:1")
print("after delete:", db.count())
print("  get(delprobe:1)    =", repr(db.get("delprobe:1")))
print("  search(delprobe)   =", db.search(tag="delprobe", count=100))
print("  search_tags        =", db.search_tags(tag="delprobe"))
db.delete("delprobe:2")
print("after del 2 :", db.count(), db.search(tag="delprobe", count=100))

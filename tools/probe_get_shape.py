# -*- coding: utf-8 -*-
"""测云端 get 的返回形态：值是"看起来像 JSON"时，服务端会不会直接解析成对象/数组？"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from twdb import TinyWebDB

db = TinyWebDB("http://tinywebdb.appinventor.space/api", "YOUR_USER", "YOUR_SECRET",
               min_interval_s=0.5, retries=4)

cases = {
    "shape:arr": '["a","b"]',
    "shape:obj": '{"k":"v"}',
    "shape:objnum": '{"n":1}',
    "shape:str": '"hello"',
    "shape:num": '123',
    "shape:bool": 'true',
    "shape:null": 'null',
    "shape:arrpct": '["a%0Ab","c"]',
    "shape:objpct": '{"s":"a%0Ab"}',
    "shape:arrspace": '[1, 2]',
    "shape:plainarr": 'P1001,P1002',
}
print("%-16s %-28s %-12s %s" % ("tag", "发送值", "读回 Python 类型", "读回值"))
for tag, val in cases.items():
    db.update(tag, val)
    raw = db.get(tag, None)
    tname = type(raw).__name__
    show = json.dumps(raw, ensure_ascii=False) if not isinstance(raw, str) else raw
    print("%-16s %-28s %-12s %s" % (tag, val[:28], tname, show[:60]))

print("\n== 清理由上 ==")
for tag in cases:
    db.delete(tag)
print("done")

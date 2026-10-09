# -*- coding: utf-8 -*-
"""云端取值编码实验：确认 TinyWebDB 对特殊字符的往返行为。"""
import json
import os
import sys

sys.path.insert(0, "D:/OJ/backend")
from twdb import TinyWebDB

db = TinyWebDB("http://tinywebdb.appinventor.space/api", "YOUR_USER", "YOUR_SECRET",
               min_interval_s=0.6, retries=4)

cases = {
    "t:plain": 'hello world',
    "t:quote": 'say "hi" now',
    "t:bslash": r'a\nb\t"c"',
    "t:brace": '{"k":"v"}',
    "t:newline": 'line1\nline2',
    "t:percent": 'a%b&c=d',
}

for tag, val in cases.items():
    db.update(tag, val)
    raw = db.call("get", tag=tag)          # 原始解析前的文本我们拿不到，这里看解析结果
    print("%-12s send=%r -> parsed=%r" % (tag, val, raw))

print("\n--- 原始 HTTP 文本（绕过 json.loads）---")
import urllib.parse
import urllib.request

for tag, val in cases.items():
    body = urllib.parse.urlencode({"user": "YOUR_USER", "secret": "YOUR_SECRET",
                                   "action": "get", "tag": tag}).encode()
    req = urllib.request.Request("http://tinywebdb.appinventor.space/api", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    ok = True
    try:
        json.loads(text)
    except Exception as e:
        ok = False
    print("%-12s RAW=%s  json_ok=%s" % (tag, repr(text), ok))

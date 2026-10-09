# -*- coding: utf-8 -*-
"""safe/unsafe 往返自测（纯本地，不打网络）。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import store

cases = [
    "hello",
    "line1\nline2",
    'say "hi" now',
    "a\\nb",
    'printf("%d%%\\n", x);',
    "tab\there",
    "50% done",
    "%0A",
    "%250A",
    "混合中文\n带\\反斜杠\"引号\"\t与制表符",
    "",
]
ok = True
for c in cases:
    e = store.safe(c)
    d = store.unsafe(e)
    flag = "ok  " if d == c else "FAIL"
    if d != c:
        ok = False
    print("%s %-36r -> %-40r -> %r" % (flag, c, e, d))

obj = {"statement": "A+B\n输入：\n  两个整数", "cases": [{"in": "1 2\n", "out": "3\n", "note": '100%\\n'}]}
e2 = store.safe_obj(obj)
txt = json.dumps(e2, ensure_ascii=False)
d2 = store.unsafe_obj(json.loads(txt))
print("JSON 文本里还有反斜杠吗:", "\\" in txt)
print("JSON 里还有真换行吗  :", "\n" in txt)
print("对象往返一致          :", d2 == obj)
print("JSON 片段             :", txt[:160])
print("结论:", "ALL OK" if ok and d2 == obj else "SOME FAIL")

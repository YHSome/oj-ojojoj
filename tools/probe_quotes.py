# -*- coding: utf-8 -*-
"""确认云端对单引号/双引号的转义行为（决定 safe() 的字符集）。"""
import json
import os
import sys
import urllib.parse
import urllib.request

API = "http://tinywebdb.appinventor.space/api"
CRED = {"user": "YOUR_USER", "secret": "YOUR_SECRET"}


def call(**params):
    p = dict(CRED)
    p.update(params)
    body = urllib.parse.urlencode(p).encode()
    req = urllib.request.Request(API, data=body)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


cases = {
    "esc:dq": 'double " quote',
    "esc:sq": "single ' quote",
    "esc:mix": "it's \"both\" ok",
    "esc:bs": "back\\slash",
    "esc:both": "a'b\"c\\d",
}
for tag, val in cases.items():
    call(action="update", tag=tag, value=val)
    raw = call(action="get", tag=tag)
    ok = True
    try:
        got = json.loads(raw)[tag]
    except Exception as e:
        ok = False
        got = "PARSE FAIL: %s" % e
    print("send=%-24r" % val)
    print("  raw=%s" % raw)
    print("  parsed=%r  json_ok=%s" % (got, ok))

for tag in cases:
    call(action="delete", tag=tag)
print("cleaned")

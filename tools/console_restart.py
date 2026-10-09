# -*- coding: utf-8 -*-
"""通过中控台重启判题机（让新的判题逻辑生效）。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"


def call(path, body=None, timeout=180):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 method="GET" if body is None else "POST",
                                 headers={"X-OJ-Console": "1"})
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


print("重启前:", call("/api/status")["running"])
print(call("/api/restart", {"workers": 4}).get("msg"))
print("重启后:", call("/api/status")["running"])

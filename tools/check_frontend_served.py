# -*- coding: utf-8 -*-
"""确认前端静态服务器发出来的是修复后的资源。"""
import urllib.request

BASE = "http://127.0.0.1:8000"
for path in ("/", "/assets/tinywebdb.js", "/assets/app.js", "/assets/crypto.js", "/assets/style.css"):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
        flags = []
        if "坑 1：云端会把" in body:
            flags.append("数组解析修复✔")
        if "先 JSON.parse 再反转义" in body:
            flags.append("换行解析修复✔")
        if "Cache-Control" in str(r.headers):
            flags.append("no-store")
        print("%-24s HTTP %s  %7d 字节  %s" % (path, r.status, len(body), " ".join(flags)))
    except Exception as e:  # noqa: BLE001
        print("%-24s 失败: %r" % (path, e))

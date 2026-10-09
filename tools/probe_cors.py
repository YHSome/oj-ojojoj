# -*- coding: utf-8 -*-
"""探测云端 API 的 CORS 行为：决定纯静态前端能否直连。"""
import urllib.parse
import urllib.request

API = "http://tinywebdb.appinventor.space/api"


def probe(origin, method="POST", preflight=False):
    params = {"user": "YOUR_USER", "secret": "YOUR_SECRET", "action": "count"}
    body = urllib.parse.urlencode(params).encode()
    headers = {"Origin": origin,
               "Content-Type": "application/x-www-form-urlencoded"}
    if preflight:
        headers.update({"Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type"})
    req = urllib.request.Request(API, data=None if preflight else body,
                                 headers=headers, method="OPTIONS" if preflight else method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("  status=%s" % r.status)
            for k, v in r.getheaders():
                if k.lower().startswith("access-control") or k.lower() in ("vary", "server"):
                    print("    %s: %s" % (k, v))
            if not any(k.lower().startswith("access-control") for k, _ in r.getheaders()):
                print("    (没有任何 Access-Control-* 响应头)")
    except Exception as e:  # noqa: BLE001
        print("  FAILED: %r" % e)


print("== 预检 OPTIONS（模拟浏览器跨域 POST） ==")
probe("http://127.0.0.1:8000", preflight=True)
print("== 实际 POST 带 Origin ==")
probe("http://127.0.0.1:8000")
print("== 实际 POST 带 Origin (file:// -> null) ==")
probe("null")

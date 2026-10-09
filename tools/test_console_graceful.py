# -*- coding: utf-8 -*-
"""验证优雅停止（不强制杀）与中控台页面可访问。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"X-OJ-Console": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, head=True):
    req = urllib.request.Request(BASE + path)
    if head:
        req.add_header("X-OJ-Console", "1")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")


st = json.loads(get("/api/status")[1])
print("停止前: running=%s pid=%s" % (st["running"], st["pid"]))
if not st["running"]:
    print("先启动:", post("/api/start", {"workers": 2}).get("msg"))

r = post("/api/stop")
print("stop ->", r.get("msg"))
ok1 = r.get("ok") and "强制" not in (r.get("msg") or "")
st = json.loads(get("/api/status")[1])
ok2 = not st["running"]
print("停止后: running=%s" % st["running"])

r = post("/api/start", {"workers": 4})
print("start ->", r.get("msg"))
st = json.loads(get("/api/status")[1])
ok3 = st["running"]

code, html = get("/")
has_ui = ("判题机中控台" in html and "btn-toggle" in html)
print("页面 GET / -> HTTP %s，关键元素: %s" % (code, has_ui))
code, js = get("/assets/console.js")
print("GET /assets/console.js -> HTTP %s (%d 字节)" % (code, len(js)))

print("\n" + ("✅ 优雅停止 / 启动 / 页面 全部正常"
              if (ok1 and ok2 and ok3 and has_ui) else "❌ 有问题（ok1=%s ok2=%s ok3=%s ui=%s）"
              % (ok1, ok2, ok3, has_ui)))
sys.exit(0 if (ok1 and ok2 and ok3 and has_ui) else 1)

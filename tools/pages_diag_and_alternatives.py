# -*- coding: utf-8 -*-
"""1) 打印失败 job 的原始 JSON（看每一步的结论与报错）
   2) 同时测几个"免 Pages"的静态托管通道（立刻可用，不用等设置）
"""
import json
import sys
import urllib.request

REPO = "YHSome/oj-ojojoj"
H = {"User-Agent": "oj", "Accept": "application/vnd.github+json"}


def api(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:  # noqa: BLE001
        return None, str(e)


print("=" * 76)
print("1) 失败 job 的每一步")
print("=" * 76)
code, body = api("https://api.github.com/repos/%s/actions/runs/37901496475/jobs" % REPO)
if code == 200:
    d = json.loads(body)
    for j in d.get("jobs", []):
        print("Job: %s  结论=%s  开始=%s 结束=%s" % (j.get("name"), j.get("conclusion"),
                                                    j.get("started_at"), j.get("completed_at")))
        for s in j.get("steps", []):
            print("   [%-9s] %-34s (%.0fs)" % (s.get("conclusion"), s.get("name"),
                                               s.get("completed_at") and 0 or 0))
        if not j.get("steps"):
            print("   （没有 steps 字段，原始片段）")
            print("   " + json.dumps(j, ensure_ascii=False)[:600])
else:
    print("code=", code, body[:200])

print()
print("=" * 76)
print("2) 免 Pages 的静态托管通道（直接测能否取到 index.html 并按 html 返回）")
print("=" * 76)
targets = [
    ("raw.githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/index.html"),
    ("jsDelivr", "https://cdn.jsdelivr.net/gh/YHSome/oj-ojojoj@main/frontend/index.html"),
    ("statically", "https://cdn.statically.io/gh/YHSome/oj-ojojoj/main/frontend/index.html"),
    ("gitcdn", "https://gitcdn.link/cdn/YHSome/oj-ojojoj/main/frontend/index.html"),
    ("ghproxy 直读", "https://ghproxy.net/https://raw.githubusercontent.com/YHSome/oj-ojojoj/main/frontend/index.html"),
]
for name, url in targets:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=20) as r:
            body = r.read(3000).decode("utf-8", "replace")
            ctype = r.headers.get("Content-Type", "")
            print("  %-14s ✔ HTTP %s  %-28s 是HTML: %s" % (name, r.status, ctype[:28],
                                                          "<!DOCTYPE html>" in body[:200]))
            print("                 %s" % url)
    except Exception as e:  # noqa: BLE001
        print("  %-14s ✘ %s" % (name, str(e)[:70]))

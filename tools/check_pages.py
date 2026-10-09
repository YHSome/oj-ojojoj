# -*- coding: utf-8 -*-
"""查看 GitHub Actions 运行状态与 Pages 状态（公开仓库无需 token）。"""
import json
import sys
import time
import urllib.request

REPO = sys.argv[1] if len(sys.argv) > 1 else "YHSome/oj-ojojoj"
WATCH = "--watch" in sys.argv


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "oj", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def show_runs():
    code, d = get("https://api.github.com/repos/%s/actions/runs?per_page=5" % REPO)
    if code != 200:
        print("  取不到 runs: %s" % (str(d)[:100]))
        return []
    runs = d.get("workflow_runs", [])
    if not runs:
        print("  还没有任何 workflow 运行（可能 Actions 被禁用，或还没触发）")
    for r in runs:
        print("  %-10s %-22s %-12s %s" % (
            r.get("status"), r.get("conclusion") or "-",
            r.get("head_sha", "")[:8], (r.get("name") or "")[:36]))
        print("      %s" % r.get("html_url"))
    return runs


def show_pages():
    code, d = get("https://api.github.com/repos/%s/pages" % REPO)
    if code == 200:
        print("  Pages: 已启用")
        print("    url    : %s" % d.get("html_url"))
        print("    source : %s / %s" % ((d.get("source") or {}).get("branch"),
                                        (d.get("source") or {}).get("path")))
        print("    build  : %s  status: %s" % (d.get("build_type"), d.get("status")))
        return True
    print("  Pages: 未启用或不可见（%s）" % str(d)[:80])
    return False


def site_ok():
    owner, name = REPO.split("/", 1)
    url = "https://%s.github.io/%s/" % (owner.lower(), name)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oj"}), timeout=25) as r:
            body = r.read(4000).decode("utf-8", "replace")
        print("  站点 %s -> HTTP %s, 含标题: %s" % (url, r.status, "OJ-OJOJOJ" in body))
        return True
    except Exception as e:  # noqa: BLE001
        print("  站点 %s -> 还没好（%s）" % (url, str(e)[:60]))
        return False


if not WATCH:
    print("=== Actions 运行 ===")
    show_runs()
    print("=== Pages ===")
    show_pages()
    print("=== 站点 ===")
    site_ok()
    sys.exit(0)

print("等待 Actions 完成（最多 6 分钟）…")
for i in range(24):
    code, d = get("https://api.github.com/repos/%s/actions/runs?per_page=3" % REPO)
    runs = d.get("workflow_runs", []) if code == 200 else []
    if runs:
        r = runs[0]
        print("  [%02d] %s / %s  %s" % (i, r.get("status"), r.get("conclusion") or "-",
                                        (r.get("name") or "")[:30]))
        if r.get("status") == "completed":
            print("  运行详情: %s" % r.get("html_url"))
            break
    else:
        print("  [%02d] 还没有 run" % i)
    time.sleep(15)

print()
print("=== Pages ===")
show_pages()
print("=== 站点 ===")
for _ in range(6):
    if site_ok():
        break
    time.sleep(12)

# -*- coding: utf-8 -*-
"""立刻查清 Actions 为什么失败：run -> job -> 每个 step 的结论。（不等待、不轮询）"""
import json
import sys
import urllib.request

REPO = sys.argv[1] if len(sys.argv) > 1 else "YHSome/oj-ojojoj"
H = {"User-Agent": "oj", "Accept": "application/vnd.github+json"}


def api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return None, str(e)


code, runs = api("/repos/%s/actions/runs?per_page=5" % REPO)
if code != 200:
    print("取 runs 失败:", runs)
    sys.exit(1)

print("=== 最近的 workflow 运行 ===")
for r in runs.get("workflow_runs", []):
    print("  #%-8s %-10s %-10s %s" % (r["id"], r["status"], r.get("conclusion") or "-",
                                      r.get("head_commit", {}).get("message", "")[:50]))

if not runs.get("workflow_runs"):
    print("  没有任何运行记录：可能 Actions 被禁用（Settings -> Actions -> General）")
    sys.exit(0)

run = runs["workflow_runs"][0]
print("\n=== 失败详情：run %s ===" % run["id"])
print("  结论:", run.get("conclusion"), " 事件:", run.get("event"))
print("  地址:", run.get("html_url"))

code, jobs = api("/repos/%s/actions/runs/%s/jobs" % (REPO, run["id"]))
if code != 200:
    print("取 jobs 失败:", jobs)
    sys.exit(1)

for j in jobs.get("jobs", []):
    print("\n  Job: %s  ->  %s" % (j.get("name"), j.get("conclusion")))
    for s in j.get("steps", []):
        mark = "✔" if s.get("conclusion") == "success" else ("✘" if s.get("conclusion") == "failure" else "·")
        print("    %s %-32s %s" % (mark, s.get("name"), s.get("conclusion")))
    # 失败步骤的日志（公开仓库可能允许匿名取）
    if j.get("conclusion") == "failure":
        code2, logs = api("/repos/%s/actions/jobs/%s/logs" % (REPO, j["id"]))
        if code2 == 200 and isinstance(logs, str):
            print("\n  --- 日志尾部（关键错误）---")
            for line in logs.strip().splitlines()[-40:]:
                print("   ", line[:200])
        else:
            print("\n  （取不到日志正文: %s）" % str(logs)[:120])

print("\n=== Pages 状态 ===")
code, pg = api("/repos/%s/pages" % REPO)
print(" ", code, str(pg)[:200])

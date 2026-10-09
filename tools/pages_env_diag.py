# -*- coding: utf-8 -*-
"""查清当前 Pages 配置 + environment 保护规则 + 最近运行（不发等待，直接出结果）。"""
import json
import sys
import urllib.request

REPO = "YHSome/oj-ojojoj"
H = {"User-Agent": "oj", "Accept": "application/vnd.github+json"}


def api(path):
    try:
        with urllib.request.urlopen(urllib.request.Request("https://api.github.com" + path, headers=H),
                                    timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:  # noqa: BLE001
        return None, str(e)


print("=" * 74)
print("1) Pages 配置")
print("=" * 74)
code, d = api("/repos/%s/pages" % REPO)
if code == 200:
    print("  ✅ Pages 已启用")
    print("     url        : %s" % d.get("html_url"))
    print("     build_type : %s   (workflow = 用 Actions 部署；legacy = 用分支)" % d.get("build_type"))
    print("     source     : %s" % json.dumps(d.get("source"), ensure_ascii=False))
    print("     status     : %s" % d.get("status"))
else:
    print("  ✘ 未启用或查不到:", code, str(d)[:150])

print()
print("=" * 74)
print("2) Environments 保护规则")
print("=" * 74)
code, d = api("/repos/%s/environments" % REPO)
if code == 200 and isinstance(d, dict):
    envs = d.get("environments", [])
    if not envs:
        print("  没有 environment")
    for e in envs:
        print("  environment: %s" % e.get("name"))
        for rule in e.get("protection_rules", []):
            print("     保护规则: %s  %s" % (rule.get("type"), json.dumps(
                {k: v for k, v in rule.items() if k not in ("id", "type", "node_id")}, ensure_ascii=False)))
        pol = e.get("deployment_branch_policy")
        print("     分支策略: %s" % json.dumps(pol, ensure_ascii=False))
        if pol:
            if pol.get("protected_branches"):
                print("       -> 只允许【受保护分支】部署（main 若未被保护就会被拒）")
            elif pol.get("custom_branch_policies"):
                print("       -> 只允许【指定分支】部署，需要在设置里把分支加进白名单")
else:
    print("  查不到（%s）: %s" % (code, str(d)[:160]))

print()
print("=" * 74)
print("3) 最近 5 次运行（含结论）")
print("=" * 74)
code, d = api("/repos/%s/actions/runs?per_page=5" % REPO)
if code == 200:
    for r in d.get("workflow_runs", []):
        print("  %-9s %-9s %-8s %s" % (r["status"], r.get("conclusion") or "-",
                                       r.get("head_branch"), r.get("head_commit", {}).get("message", "")[:42]))
else:
    print("  查不到:", code, str(d)[:120])

print()
print("=" * 74)
print("4) 分支保护情况（main 是否受保护）")
print("=" * 74)
code, d = api("/repos/%s/branches/main" % REPO)
if code == 200:
    print("  main: protected=%s" % d.get("protected"))
else:
    print("  查不到:", code, str(d)[:120])

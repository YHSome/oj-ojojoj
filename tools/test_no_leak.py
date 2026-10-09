# -*- coding: utf-8 -*-
"""验证：判题机只回判定，不回"期望/实际"这类答案明细。

  期望：
    * WA 时对外只有「答案错误」，不含 期望/实际 内容
    * 明细落在判题机本地 __judge_detail.txt（管理员复盘用）
    * RE 仍可看到选手自己的报错（不含标准答案）
    * 打开 judge.public_case_detail 后明细恢复（可配置）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import config as ojconfig
import judge as ojjudge

cfg = ojconfig.load()
cfg.setv("paths.python", sys.executable)
J = ojjudge.Judge(cfg, lambda lvl, m: print("   [%s] %s" % (lvl, m)))

WA_CPP = '#include <bits/stdc++.h>\nint main(){ long long a,b; scanf("%lld %lld",&a,&b); printf("%lld\\n",a+b+1); return 0; }\n'
RE_CPP = '#include <bits/stdc++.h>\nint main(){ int*p=nullptr; *p=1; return 0; }\n'
problem = {"pid": "T", "title": "t", "time_limit_ms": 2000, "memory_limit_kb": 262144,
           "output_limit_kb": 8192, "checker": "tokens", "total_score": 100}
tests = [{"i": 1, "in": "1000000000 1000000000\n", "out": "2000000000\n", "score": 100}]

def run(name, code, lang="cpp"):
    work = os.path.join(cfg.path("work"), "_leak_probe_" + name)
    v, score, cases, clog, ms, kb, msg, chk = J.judge_submission({"sid": name, "lang": lang},
                                                                 code, problem, tests, work)
    print("\n=== %s ===" % name)
    print("  对外 verdict = %s" % v)
    for c in cases:
        print("  对外 case%d msg = %r" % (c["i"], c["msg"]))
    detail = os.path.join(work, "__judge_detail.txt")
    if os.path.isfile(detail):
        print("  本地明细文件: %s" % open(detail, encoding="utf-8").read().strip().splitlines()[-1][:110])
    return v, cases

print("== 默认（public_case_detail=false）==")
v, cases = run("wa_hidden", WA_CPP)
leak = any("2000000000" in (c.get("msg") or "") or "期望" in (c.get("msg") or "") for c in cases)
print("  → 泄露标准答案: %s" % ("❌ 是" if leak else "✔ 否"))
run("re_keep", RE_CPP)

print("\n== 打开明细开关（public_case_detail=true）==")
cfg.setv("judge.public_case_detail", True)
J2 = ojjudge.Judge(cfg, lambda lvl, m: None)
work = os.path.join(cfg.path("work"), "_leak_probe_on")
v2, s2, cases2, c2, ms2, kb2, msg2, chk2 = J2.judge_submission(
    {"sid": "on", "lang": "cpp"}, WA_CPP, problem, tests, work)
print("  对外 case1 msg = %r" % (cases2[0]["msg"] if cases2 else ""))
print("  → 明细已恢复: %s" % ("✔" if cases2 and "期望" in cases2[0]["msg"] else "❌"))

ok = (not leak) and v == "WA" and cases2 and "期望" in cases2[0]["msg"]
print("\n" + ("✅ 判定与明细分离正确" if ok else "❌ 有问题"))
sys.exit(0 if ok else 1)

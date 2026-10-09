#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回归：Python 版 RE 的报错信息是否带 traceback + 人话提示。

用后端 judge.Judge 直接判（不经过云端），最后打印每个测试点的 msg / stderr。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import config as ojconfig
import judge as ojjudge

cfg = ojconfig.load()
cfg.setv("paths.python", sys.executable)
J = ojjudge.Judge(cfg, lambda lvl, m: print("[%s] %s" % (lvl, m)))

BAD = "a , b = map(int, input().split)\nprint(a + b)\n"          # 用户这次提交的代码
GOOD = "a , b = map(int, input().split())\nprint(a + b)\n"       # 修好的
ZERO = "print(1/0)\n"
IDX = "a=[1]\nprint(a[5])\n"

problem = {"pid": "T", "title": "t", "time_limit_ms": 2000, "memory_limit_kb": 262144,
           "output_limit_kb": 8192, "checker": "tokens", "total_score": 100}
tests = [{"i": 1, "in": "1 2\n", "out": "3\n", "score": 100}]
work = os.path.join(cfg.path("work"), "_re_probe")

for name, code in (("RE:input.split 少括号", BAD), ("正确写法", GOOD),
                   ("RE:除零", ZERO), ("RE:越界", IDX)):
    v, score, cases, clog, ms, kb, msg, chk = J.judge_submission(
        {"sid": "probe", "lang": "py"}, code, problem, tests, work)
    print("\n=== %s ===" % name)
    print("  判定: %s  分数: %s  用时: %sms" % (v, score, ms))
    for c in cases:
        print("  msg: %s" % c["msg"])
        if c.get("stderr"):
            print("  stderr 保留 %d 字节，首行: %s" % (len(c["stderr"]), c["stderr"].splitlines()[0][:60]))

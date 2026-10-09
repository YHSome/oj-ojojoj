# -*- coding: utf-8 -*-
"""清理实验残留标签 + 重新播种题库（修掉旧格式里被云端吞掉换行的测试数据）。

  python tools/cleanup_probe.py            # 清理 + seed
  python tools/cleanup_probe.py --only-del # 只清理
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import admin_cli
import config as ojconfig
from store import Store
from twdb import TinyWebDB

JUNK = ["t:plain", "t:quote", "t:bslash", "t:brace", "t:newline", "t:percent",
        "oj_init_test"]
JUNK += ["%s:%s" % (p, sid) for sid in ("512983398", "100001")
         for p in ("code", "sub", "q", "res", "lock", "arc")]
JUNK += ["esc:dq", "esc:sq", "esc:mix", "esc:bs", "esc:both", "t:safecheck"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-del", action="store_true")
    ap.add_argument("--pid", action="append")
    a = ap.parse_args()

    cfg = ojconfig.load()
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                   min_interval_s=cfg.getv("api.min_interval_s", 0.45),
                   retries=cfg.getv("api.retries", 5))
    store = Store(db, cfg)

    print("== 清理实验标签（delete 幂等，直接删） ==")
    for tag in JUNK:
        db.delete(tag)
    print("  已删除 %d 个候选残留标签" % len(JUNK))
    store.cache_drop()
    print("  本地题目缓存已清空")

    if a.only_del:
        return 0

    print("== 重新播种题库（safe 编码后的测试数据） ==")
    pids = a.pid or [d for d in sorted(os.listdir(cfg.path("problems")))
                     if os.path.isfile(os.path.join(cfg.path("problems"), d, "problem.json"))]
    for pid in pids:
        admin_cli.push_problem(cfg, store, pid)

    print("== 校验云端读回 ==")
    for pid in pids:
        prob = store.get_problem(pid)
        tests = store.get_tests(pid)
        print("  %s: title=%r 测试点=%d" % (pid, (prob or {}).get("title"), len(tests)))
        for t in tests:
            print("     case %s in=%r out=%r score=%s" % (t.get("i"), t.get("in"), t.get("out"), t.get("score")))
    store.write_meta({"seeded": True})
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

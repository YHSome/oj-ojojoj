# -*- coding: utf-8 -*-
"""压测：一次投递 N 个提交，然后统计被哪台判题机判的、有没有重复判。

    python tools/burst_submit.py --count 10 --pid a-plus-b --lang cpp

统计口径：
  * 每个 sid 只应有一个 sub.judge（谁判的）
  * attempt 表示被认领次数：>1 说明有争抢（多机共判下正常，但应当很少）
  * 全部 done 才算完成（否则可能有任务被漏掉）
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import config as ojconfig            # noqa: E402
from store import Store, new_sid     # noqa: E402
from twdb import TinyWebDB, TwdbError  # noqa: E402

AC = ('#include <bits/stdc++.h>\nint main(){ long long a,b; '
      'if(scanf("%lld %lld",&a,&b)!=2) return 0; printf("%lld\\n",a+b); return 0; }\n')
PY = "import sys\nprint(sum(map(int, sys.stdin.read().split())))\n"
CE = '#include <bits/stdc++.h>\nint main(){ this is not c++ }\n'
SLEEPY = '#include <bits/stdc++.h>\nint main(){long long a,b;scanf("%lld %lld",&a,&b);'
SLEEPY += ' volatile double s=0; for(long long i=0;i<1200000000LL;i++) s+=i; printf("%lld\\n",a+b);}\n'

MIX = {"ac": AC, "py": PY, "ce": CE, "tle": SLEEPY}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--pid", default="a-plus-b")
    ap.add_argument("--lang", default="cpp")
    ap.add_argument("--mix", action="store_true", help="混合 ac/tle/ce/py 制造不同耗时")
    ap.add_argument("--user", default="burst")
    ap.add_argument("--timeout", type=float, default=240)
    a = ap.parse_args()

    cfg = ojconfig.load()
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                   min_interval_s=cfg.getv("api.min_interval_s", 0.45),
                   retries=cfg.getv("api.retries", 5))
    store = Store(db, cfg)

    prob = store.get_problem(a.pid)
    if not prob:
        print("题目不存在:", a.pid)
        return 1

    kinds = ["ac", "ac", "tle", "ac", "ce", "ac", "py", "ac"] if a.mix else ["ac"] * a.count
    kinds = (kinds * ((a.count // len(kinds)) + 1))[:a.count]

    sids = []
    t0 = time.time()
    for i, kind in enumerate(kinds):
        sid = str(int(time.time() * 1000) % 100000000) + "%02d" % i
        lang = "py" if kind == "py" else a.lang
        code = MIX[kind]
        ts = int(time.time())
        store.put_raw("code:" + sid, code)
        store.put_json("sub:" + sid, {
            "sid": sid, "user": "%s%d" % (a.user, i % 3), "pid": a.pid, "lang": lang,
            "status": "pending", "ts": ts, "judge": "", "verdict": "", "score": 0,
            "time_ms": 0, "memory_kb": 0, "cases_passed": 0, "case_count": 0,
            "msg": "排队中", "prob_rev": prob.get("rev", ""), "attempt": 0,
            "lease_token": "", "lease_until": 0, "rejudge": "",
            "enc": "plain", "client_pubkey": None})
        store.put_json("q:" + sid, {"sid": sid, "ts": ts, "pid": a.pid,
                                    "lang": lang, "user": "%s%d" % (a.user, i % 3)})
        sids.append((sid, kind))
        print("  投递 %-12s %-4s %s" % (sid, kind, a.pid))
    print("\n%d 个提交已入队（%.1fs）" % (len(sids), time.time() - t0))

    print("等待判完…（最多 %.0fs）" % a.timeout)
    deadline = time.time() + a.timeout
    done = {}
    while time.time() < deadline:
        done = {}
        for sid, kind in sids:
            sub = store.get_sub(sid)
            if sub and sub.get("status") in ("done", "failed"):
                done[sid] = sub
        if len(done) == len(sids):
            break
        time.sleep(4)

    print("\n" + "=" * 78)
    print("结果（%d/%d 完成）" % (len(done), len(sids)))
    print("=" * 78)
    per_judge = {}
    attempts = {}
    for sid, kind in sids:
        sub = done.get(sid)
        if not sub:
            print("  %-14s 未完成（可能被漏掉，检查 q: 与判题机日志）" % sid)
            continue
        j = sub.get("judge") or "?"
        per_judge[j] = per_judge.get(j, 0) + 1
        attempts[sid] = int(sub.get("attempt") or 0)
        print("  %-14s %-4s -> %-16s %-5s attempt=%s score=%s"
              % (sid, kind, j, sub.get("verdict"), sub.get("attempt"), sub.get("score")))

    print("\n按判题机分布：")
    for j, n in sorted(per_judge.items()):
        print("  %-18s %d 个" % (j, n))
    multi = {k: v for k, v in attempts.items() if v and v > 1}
    print("\n被多次认领的提交数：%d（多机争抢，正常但应很少）" % len(multi))
    ok = len(done) == len(sids)
    print("\n" + ("✅ 全部完成，无遗漏" if ok else "❌ 有任务未完成"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

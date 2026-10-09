# -*- coding: utf-8 -*-
"""模拟 App Inventor 前端：只用 TinyWebDB 的 update/get/search/count 走完整闭环。

这是在"没有手机"时验证前后端契约的端到端客户端，与 App Inventor 里
Web 组件发出的请求完全同构（POST user/secret/action + 参数）。

用法
----
  python mock_client.py hello
  python mock_client.py register --user alice --pass 1234
  python mock_client.py login    --user alice --pass 1234
  python mock_client.py list
  python mock_client.py submit   --user alice --pid P1001 --lang cpp --file ac.cpp
  python mock_client.py submit   --user alice --pid P1001 --lang cpp --code "int main(){}"
  python mock_client.py wait     --sid 123456789 --timeout 60
  python mock_client.py rank
  python mock_client.py demo     --pid P1001          # 自动跑 AC / WA / TLE 三条闭环
  python mock_client.py raw --action search --tag sub: --count 100
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import config as ojconfig
from store import Store, new_sid
from twdb import TinyWebDB, TwdbError, dumps, loads

# ---------------------------------------------------------------- 样例程序
AC_CPP = """#include <bits/stdc++.h>
int main(){ long long a,b; if(scanf("%lld %lld",&a,&b)!=2) return 0; printf("%lld\\n",a+b); return 0; }
"""
WA_CPP = """#include <bits/stdc++.h>
int main(){ long long a,b; scanf("%lld %lld",&a,&b); printf("%lld\\n",a*b); return 0; }
"""
TLE_CPP = """#include <bits/stdc++.h>
int main(){ long long a,b; scanf("%lld %lld",&a,&b); volatile double s=0; for(long long i=0;i<20000000000LL;i++) s+=i; printf("%lld\\n",a+b); return 0; }
"""
CE_CPP = """#include <bits/stdc++.h>
int main(){ this is not c++ }
"""
RE_CPP = """#include <bits/stdc++.h>
int main(){ int *p = nullptr; *p = 1; printf("%d\\n", *p); return 0; }
"""
MLE_CPP = """#include <bits/stdc++.h>
int main(){
    std::vector<std::vector<char>> hold;
    for (int i = 0; i < 20000; i++) { hold.push_back(std::vector<char>(1 << 20, (char)i)); }
    printf("%zu\\n", hold.size());
    return 0;
}
"""
OLE_CPP = """#include <bits/stdc++.h>
int main(){ for (;;) fputs("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\\n", stdout); return 0; }
"""
AC_PY = """import sys
a, b = map(int, sys.stdin.read().split())
print(a + b)
"""
# P1002 区间求和的正解（前缀和）
AC2_CPP = """#include <bits/stdc++.h>
int main(){
    int n, m; if(scanf("%d %d", &n, &m) != 2) return 0;
    std::vector<long long> s(n + 1, 0);
    for (int i = 1; i <= n; i++){ long long x; scanf("%lld", &x); s[i] = s[i-1] + x; }
    while (m--){ int l, r; scanf("%d %d", &l, &r); printf("%lld\\n", s[r] - s[l-1]); }
    return 0;
}
"""

SAMPLES = {"ac": AC_CPP, "wa": WA_CPP, "tle": TLE_CPP, "ce": CE_CPP,
           "re": RE_CPP, "mle": MLE_CPP, "ole": OLE_CPP, "pyac": AC_PY}
# 按题目覆盖同名样例（demo 会自动挑对应题目的正解）
SAMPLES_FOR = {"P1002": {"ac": AC2_CPP}}


def sample_code(pid, name):
    return SAMPLES_FOR.get(pid, {}).get(name) or SAMPLES.get(name, "")


def sample_lang(name, override=None):
    """pyac 这类样例自带语言，否则用命令行指定（默认 cpp）。"""
    if override:
        return override
    return "py" if name.startswith("py") else "cpp"


def make_client(cfg):
    db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                   timeout_s=cfg.getv("api.timeout_s", 15),
                   retries=cfg.getv("api.retries", 3),
                   min_interval_s=cfg.getv("api.min_interval_s", 0.12),
                   page_size=cfg.getv("api.search_page_size", 100),
                   max_pages=cfg.getv("api.search_max_pages", 20))
    return db, Store(db, cfg)


# ------------------------------------------------------- 前端侧的命令总线 RPC
def rpc(store, op, args=None, token=None, timeout=25.0, poll=1.5):
    """模拟前端：写 cmd:<CID> → 轮询 reply:<CID>。"""
    cid = "m%d%04d" % (int(time.time()) % 1000000, random.randint(0, 9999))
    store.put_cmd(cid, op, args or {}, self_user(token), token)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rep = store.get_json("reply:" + cid, None)
        if isinstance(rep, dict):
            return rep
        time.sleep(poll)
    return {"ok": False, "msg": "超时：daemon 没在跑？(cmd=%s)" % cid, "data": {}}


def self_user(token):
    return ""


def front_submit(store, sid, user, pid, lang, code):
    """前端三连写：code: → sub: → q:（与 App Inventor 积木一一对应）。

    prob_rev 取自 `prob:<PID>.rev`：把提交固定到当时的题目版本
    （对齐 MiniJudge：更新题目不影响已经排队的提交）。
    """
    ts = int(time.time())
    prob = store.get_problem(pid) or {}
    store.put_raw("code:" + sid, code)
    store.put_json("sub:" + sid, {
        "sid": sid, "user": user, "pid": pid, "lang": lang,
        "status": "pending", "ts": ts, "judge": "", "verdict": "",
        "score": 0, "time_ms": 0, "memory_kb": 0, "cases_passed": 0,
        "case_count": 0, "msg": "排队中",
        "prob_rev": prob.get("rev", ""), "attempt": 0,
        "lease_token": "", "lease_until": 0, "rejudge": ""})
    store.put_json("q:" + sid, {"sid": sid, "ts": ts, "pid": pid,
                               "lang": lang, "user": user})


# ------------------------------------------------------------------ 子命令
def cmd_hello(a, cfg, db, store):
    print(json.dumps(rpc(store, "hello"), ensure_ascii=False, indent=2))


def cmd_register(a, cfg, db, store):
    print(json.dumps(rpc(store, "register", {"user": a.user, "pass": a.password,
                                             "nick": a.nick or a.user}),
                     ensure_ascii=False, indent=2))


def cmd_login(a, cfg, db, store):
    print(json.dumps(rpc(store, "login", {"user": a.user, "pass": a.password}),
                     ensure_ascii=False, indent=2))


def cmd_list(a, cfg, db, store):
    print("== 前端方式 get(idx:problems) ==")
    ids = store.get_json("idx:problems", [])
    print(ids)
    print("== 前端方式 search(tag=prob:, type=tag) ==")
    print(db.search(tag="prob:", count=100, type_="tag"))
    print("== 题目详情 get(prob:<PID>) ==")
    for pid in ids[:5]:
        p = store.get_problem(pid)
        print("  %-8s %-20s %sms %sKB %s点" % (pid, p.get("title") if p else "-",
                                               (p or {}).get("time_limit_ms"),
                                               (p or {}).get("memory_limit_kb"),
                                               (p or {}).get("case_count")))


def cmd_submit(a, cfg, db, store):
    if not store.get_user(a.user):
        rep = rpc(store, "register", {"user": a.user, "pass": "demo1234"})
        print("（用户 %s 不存在，已自动注册）%s" % (a.user, rep.get("msg")))
    code = sample_code(a.pid, a.sample)
    if a.file:
        with open(a.file, "r", encoding="utf-8") as f:
            code = f.read()
    if a.code:
        code = a.code
    if not code:
        raise SystemExit("需要 --file / --code / --sample")
    sid = str(a.sid or new_sid())
    lang = sample_lang(a.sample, None if a.lang == "auto" else a.lang)
    front_submit(store, sid, a.user, a.pid, lang, code)
    print("已提交 sid=%s（user=%s pid=%s lang=%s, %d 字节）"
          % (sid, a.user, a.pid, lang, len(code)))
    if not a.no_wait:
        cmd_wait(argparse.Namespace(sid=sid, timeout=a.timeout, poll=1.0, quiet=False),
                 cfg, db, store)


def cmd_wait(a, cfg, db, store):
    t0 = time.time()
    last = None
    while time.time() - t0 < a.timeout:
        sub = store.get_sub(a.sid)
        if not sub:
            print("提交不存在: %s" % a.sid)
            return 1
        if sub.get("status") != last:
            last = sub.get("status")
            if not a.quiet:
                print("  status=%s %s" % (last, sub.get("msg", "")))
        if sub.get("status") in ("done", "failed"):
            res = store.get_result(a.sid) or {}
            print("结果: %s 分数=%s 用时=%sms 内存=%sKB 通过 %s/%s"
                  % (sub.get("verdict"), sub.get("score"), sub.get("time_ms"),
                     sub.get("memory_kb"), sub.get("cases_passed"), sub.get("case_count")))
            for c in res.get("cases", []):
                print("   case %-3s %-4s %6sms %8sKB %s"
                      % (c.get("i"), c.get("verdict"), c.get("time_ms"),
                         c.get("memory_kb"), str(c.get("msg", ""))[:60]))
            if res.get("compile_log"):
                print("   编译日志:")
                print("   " + "\n   ".join(res["compile_log"].splitlines()[:12]))
            return 0 if sub.get("verdict") == "AC" else 2
        time.sleep(a.poll)
    print("等待超时（%ss）。判题机在线吗？python backend/daemon.py --once" % a.timeout)
    return 1


def cmd_rank(a, cfg, db, store):
    print(json.dumps(store.get_json("rank", {}), ensure_ascii=False, indent=2))


def cmd_demo(a, cfg, db, store):
    """完整闭环自测：注册 → 登录 → 提交 AC/WA/CE → 取结果 → 排行榜。"""
    user = a.user or ("demo%d" % random.randint(100, 999))
    pwd = "demo1234"
    print("== 1) hello ==")
    print(json.dumps(rpc(store, "hello"), ensure_ascii=False))
    print("== 2) register %s ==" % user)
    print(json.dumps(rpc(store, "register", {"user": user, "pass": pwd}), ensure_ascii=False))
    print("== 3) login ==")
    rep = rpc(store, "login", {"user": user, "pass": pwd})
    token = (rep.get("data") or {}).get("token")
    print("token =", token)

    expect = {"ac": "AC", "wa": "WA", "ce": "CE", "tle": "TLE",
              "re": "RE", "mle": "MLE", "ole": "OLE", "pyac": "AC"}
    rc = 0
    for sample in a.samples:
        sid = str(new_sid())
        print("\n== 4) 提交 %s（期望 %s） sid=%s ==" % (sample, expect.get(sample, "?"), sid))
        lang = sample_lang(sample)
        front_submit(store, sid, user, a.pid, lang, sample_code(a.pid, sample))
        code = cmd_wait(argparse.Namespace(sid=sid, timeout=a.timeout, poll=1.0, quiet=False),
                        cfg, db, store)
        if expect.get(sample) and code == 0 and expect[sample] != "AC":
            rc = 1
    print("\n== 5) 排行榜 get(rank) ==")
    cmd_rank(a, cfg, db, store)
    print("\n== 6) 我的提交 ==")
    print(json.dumps(rpc(store, "mysubs", {"user": user}), ensure_ascii=False)[:600])
    return rc


def cmd_raw(a, cfg, db, store):
    print(db.call(a.action, **json.loads(a.params)) if a.params else db.call(a.action))


def main(argv=None):
    ap = argparse.ArgumentParser(description="模拟 App Inventor 前端")
    ap.add_argument("--config", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("hello").set_defaults(func=cmd_hello)
    p = sub.add_parser("register")
    p.add_argument("--user", required=True); p.add_argument("--pass", dest="password", required=True)
    p.add_argument("--nick"); p.set_defaults(func=cmd_register)
    p = sub.add_parser("login")
    p.add_argument("--user", required=True); p.add_argument("--pass", dest="password", required=True)
    p.set_defaults(func=cmd_login)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("rank").set_defaults(func=cmd_rank)

    p = sub.add_parser("submit")
    p.add_argument("--user", required=True); p.add_argument("--pid", required=True)
    p.add_argument("--lang", default="auto"); p.add_argument("--file")
    p.add_argument("--code"); p.add_argument("--sample", default="ac",
                                             choices=sorted(SAMPLES))
    p.add_argument("--sid"); p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--no-wait", action="store_true")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("wait")
    p.add_argument("--sid", required=True); p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--poll", type=float, default=1.0); p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("demo")
    p.add_argument("--pid", default="P1001"); p.add_argument("--user")
    p.add_argument("--samples", nargs="*", default=["ac", "wa", "ce", "tle"])
    p.add_argument("--timeout", type=float, default=120)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("raw")
    p.add_argument("action"); p.add_argument("--params", default="{}")
    p.set_defaults(func=cmd_raw)

    a = ap.parse_args(argv)
    cfg = ojconfig.load(a.config, a.overrides)
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    db, store = make_client(cfg)
    return a.func(a, cfg, db, store) or 0


if __name__ == "__main__":
    sys.exit(main())

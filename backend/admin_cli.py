# -*- coding: utf-8 -*-
"""运维 CLI：题库播种 / 推送拉取 / 重测 / 排行榜 / 归档 / 直读标签。

常用：
  python admin_cli.py probe
  python admin_cli.py seed
  python admin_cli.py add-problem --pid P1002 --title "A*B" --tl 1000 --ml 262144 --tests-dir D:\\OJ\\data\\problems\\P1002\\tests
  python admin_cli.py push --pid P1002
  python admin_cli.py pull --pid P1002
  python admin_cli.py list --what problems|subs|queue|judges|users|cmds
  python admin_cli.py inspect --sid 123456789
  python admin_cli.py rejudge --pid P1001
  python admin_cli.py rank
  python admin_cli.py archive --ttl-hours 24
  python admin_cli.py gc
  python admin_cli.py get prob:P1001
  python admin_cli.py put tag value
  python admin_cli.py del tag
  python admin_cli.py adduser --user alice --pass 1234 [--admin]
  python admin_cli.py mkproblem --pid P1003 --title "求和"
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as ojconfig
import judge as ojjudge
from store import Store, STATUS_PENDING, now_ts
from twdb import TinyWebDB, TwdbError, dumps, loads


def build(args):
    cfg = ojconfig.load(args.config, args.overrides)
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                   timeout_s=cfg.getv("api.timeout_s", 15),
                   retries=cfg.getv("api.retries", 5),
                   min_interval_s=cfg.getv("api.min_interval_s", 0.45),
                   page_size=cfg.getv("api.search_page_size", 100),
                   max_pages=cfg.getv("api.search_max_pages", 20))
    return cfg, db, Store(db, cfg)


# ============================================================== 题库本地副本
def problem_dir(cfg, pid):
    return os.path.join(cfg.path("problems"), str(pid))


def load_local_problem(cfg, pid):
    """读本地题库副本，**兼容 MiniJudge 题包**：
        problem.json（id/title/time_limit_ms/memory_limit_mb/output_limit_bytes/
                      sample_input/sample_output/checker/float_*_tolerance）
        statement.md     UTF-8 中文 Markdown 题面
        tests/NN.in      + tests/NN.ans（或本项目惯用的 .out）
    """
    d = problem_dir(cfg, pid)
    meta_path = os.path.join(d, "problem.json")
    if not os.path.isfile(meta_path):
        raise SystemExit("缺少 %s" % meta_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    prob = dict(raw)
    prob["pid"] = prob.get("pid") or prob.get("id") or pid
    # MiniJudge 字段名 → 本项目字段名
    if "memory_limit_mb" in raw and "memory_limit_kb" not in raw:
        prob["memory_limit_kb"] = int(raw["memory_limit_mb"]) * 1024
    if "output_limit_bytes" in raw and "output_limit_kb" not in raw:
        prob["output_limit_kb"] = max(1, int(raw["output_limit_bytes"]) // 1024)
    if raw.get("float_absolute_tolerance") is not None:
        prob.setdefault("float_eps", raw["float_absolute_tolerance"])
    if raw.get("float_relative_tolerance") is not None:
        prob.setdefault("float_relative_eps", raw["float_relative_tolerance"])
    prob.setdefault("checker", cfg.getv("checker.default", "tokens"))

    md = os.path.join(d, "statement.md")
    if os.path.isfile(md) and not prob.get("statement"):
        prob["statement_md"] = read_file(md)
        prob["statement"] = markdown_to_text(prob["statement_md"])
    elif prob.get("statement") and not prob.get("statement_md"):
        prob["statement_md"] = prob["statement"]

    # 公开样例（MiniJudge 放在 problem.json 里）
    if raw.get("sample_input") is not None or raw.get("sample_output") is not None:
        prob["samples"] = [{"in": raw.get("sample_input", ""),
                            "out": raw.get("sample_output", "")}]

    tests_dir = os.path.join(d, "tests")
    ins = sorted(glob.glob(os.path.join(tests_dir, "*.in")))
    if not ins:
        raise SystemExit("题目 %s 没有测试数据（%s/*.in）" % (pid, tests_dir))
    cases_meta = {str(c.get("file") or c.get("i")): c for c in prob.get("cases", [])}
    total = int(prob.get("total_score", 100))
    n_cases = len(ins)
    base_score = max(1, total // max(1, n_cases))     # 未显式配分时均分，余数给最后一点
    tests = []
    for i, in_path in enumerate(ins, 1):
        base = os.path.splitext(os.path.basename(in_path))[0]
        ans_path = None
        for ext in (".ans", ".out"):           # .ans 是 MiniJudge 的写法
            cand = os.path.join(tests_dir, base + ext)
            if os.path.isfile(cand):
                ans_path = cand
                break
        if ans_path is None:
            if prob.get("checker") not in ("custom", "spj"):
                raise SystemExit("测试点 %s 缺少 .ans/.out" % base)
            ans_path = in_path
        cm = cases_meta.get(base) or cases_meta.get(str(i)) or {}
        default = base_score if i < n_cases else max(base_score, total - base_score * (n_cases - 1))
        tests.append({"i": i,
                      "name": cm.get("name") or base,
                      "score": int(cm.get("score", default)),
                      "in": read_file(in_path),
                      "out": read_file(ans_path)})
    prob["case_count"] = len(tests)
    prob["total_score"] = sum(t["score"] for t in tests)
    return prob, tests


def markdown_to_text(md):
    """极简 Markdown→纯文本（给 App Inventor 这类不能渲染 Markdown 的前端）。"""
    import re
    text = md.replace("\r\n", "\n")
    text = re.sub(r"```[^\n]*\n(.*?)```", lambda m: m.group(1), text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"^\s*[-*+]\s+", "· ", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_file(p):
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def write_file(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def push_problem(cfg, store, pid, verbose=True):
    prob, tests = load_local_problem(cfg, pid)
    # 内容指纹 rev：题面或测试点任一变化都会变，判题机本地缓存靠它判失效
    blob = json.dumps({"p": {k: v for k, v in prob.items() if k != "checker_src"},
                       "t": tests}, ensure_ascii=False, sort_keys=True)
    prob["rev"] = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
    prob["updated"] = now_ts()
    store.put_problem(prob, update_index=True)
    for t in tests:
        store.put_test(pid, t["i"], t)
    chk = os.path.join(problem_dir(cfg, pid), "checker.py")
    if prob.get("checker") == "spj" and os.path.isfile(chk):
        prob["checker_src"] = read_file(chk)
        store.put_problem(prob, update_index=False)
    store.cache_drop(pid)          # 本机缓存立即失效
    if verbose:
        print("[push] %s 《%s》 %d 个测试点，总分 %s，rev=%s"
              % (pid, prob.get("title", ""), len(tests), prob.get("total_score"), prob["rev"]))
    return prob, tests


def pull_problem(cfg, store, pid):
    prob = store.get_problem(pid)
    if not prob:
        raise SystemExit("云端没有题目 %s" % pid)
    tests = store.get_tests(pid)
    d = problem_dir(cfg, pid)
    meta = {k: v for k, v in prob.items() if k != "checker_src"}
    write_file(os.path.join(d, "problem.json"), json.dumps(meta, ensure_ascii=False, indent=2))
    for t in tests:
        base = "%02d" % int(t.get("i", 0))
        write_file(os.path.join(d, "tests", base + ".in"), t.get("in", ""))
        write_file(os.path.join(d, "tests", base + ".out"), t.get("out", ""))
    if prob.get("checker_src"):
        write_file(os.path.join(d, "checker.py"), prob["checker_src"])
    print("[pull] %s -> %s（%d 个测试点）" % (pid, d, len(tests)))


# ================================================================== 子命令
def cmd_probe(args, cfg, db, store):
    info = db.ping()
    print("API      :", cfg.getv("api.base"))
    print("浏览页   :", cfg.getv("api.browse"))
    print("连通性   :", info)
    if not info.get("ok"):
        return 1
    print("标签总数 :", db.count())
    print("在线判题机:", [j.get("id") for j in store.judges_online()])
    print("题目     :", store.list_problem_ids())
    return 0


def cmd_seed(args, cfg, db, store):
    pids = args.pid or [os.path.basename(p) for p in
                        sorted(glob.glob(os.path.join(cfg.path("problems"), "*")))
                        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "problem.json"))]
    if not pids:
        print("没有找到本地题目（data/problems/<PID>/problem.json）")
        return 1
    for pid in pids:
        push_problem(cfg, store, pid)
    store.write_meta({"seeded": now_ts()})
    store.rebuild_rank()
    print("[seed] 完成，共 %d 题" % len(pids))
    return 0


def cmd_mkproblem(args, cfg, db, store):
    d = problem_dir(cfg, args.pid)
    meta = {
        "pid": args.pid, "title": args.title or args.pid,
        "statement": args.statement or "（题面待补充）\n\n输入：\n输出：",
        "difficulty": args.difficulty, "tags": [],
        "time_limit_ms": args.tl, "memory_limit_kb": args.ml,
        "output_limit_kb": args.ol,
        "checker": args.checker, "float_eps": 1e-6,
        "total_score": 100, "case_count": 0, "visible": True,
    }
    write_file(os.path.join(d, "problem.json"), json.dumps(meta, ensure_ascii=False, indent=2))
    write_file(os.path.join(d, "tests", "01.in"), "1 2\n")
    write_file(os.path.join(d, "tests", "01.out"), "3\n")
    if args.checker == "spj":
        write_file(os.path.join(d, "checker.py"),
                   "# -*- coding: utf-8 -*-\n"
                   "# 用法: python checker.py <input> <output> <answer>，退出码 0=AC 1=WA\n"
                   "import sys\n"
                   "def main():\n"
                   "    data = open(sys.argv[1], encoding='utf-8').read().split()\n"
                   "    out = open(sys.argv[2], encoding='utf-8').read().split()\n"
                   "    ans = open(sys.argv[3], encoding='utf-8').read().split()\n"
                   "    ...  # TODO: 自定义比较逻辑\n"
                   "    return 0 if out == ans else 1\n"
                   "sys.exit(main())\n")
    print("[mkproblem] 已生成模板：%s" % d)
    print("  1) 编辑 problem.json 与 tests/*.in|*.out")
    print("  2) python admin_cli.py push --pid %s" % args.pid)
    return 0


def cmd_push(args, cfg, db, store):
    for pid in args.pid:
        push_problem(cfg, store, pid)
    return 0


def cmd_pull(args, cfg, db, store):
    for pid in args.pid:
        pull_problem(cfg, store, pid)
    return 0


def cmd_list(args, cfg, db, store):
    what = args.what
    if what == "problems":
        for p in store.list_problems():
            print("%-8s %-28s %5dms %7dKB %2d点 %s"
                  % (p.get("pid"), str(p.get("title"))[:28], p.get("time_limit_ms", 0),
                     p.get("memory_limit_kb", 0), p.get("case_count", 0),
                     "可见" if p.get("visible", True) else "隐藏"))
    elif what == "subs":
        rows = []
        for tag, raw in db.search_pairs(tag="sub:", type_="both"):
            s = store.loads(raw, None)
            if isinstance(s, dict):
                rows.append(s)
        rows.sort(key=lambda s: int(s.get("ts") or 0), reverse=True)
        for s in rows[:args.limit]:
            print("%-12s %-10s %-6s %-4s %-6s %-4s %6sms %7sKB %s"
                  % (s.get("sid"), s.get("user"), s.get("pid"), s.get("lang"),
                     s.get("status"), s.get("verdict") or "-", s.get("time_ms", 0),
                     s.get("memory_kb", 0), str(s.get("msg", ""))[:30]))
        print("共 %d 条（显示 %d）" % (len(rows), min(args.limit, len(rows))))
    elif what == "queue":
        for c in store.queue_candidates():
            print(c)
    elif what == "judges":
        for j in store.judges_online():
            print(j)
    elif what == "users":
        for u in store.list_users():
            print("%-16s nick=%-12s score=%-5s ac=%-4s sub=%-4s solved=%s"
                  % (u.get("user"), u.get("nick"), u.get("score"), u.get("ac_count"),
                     u.get("submit_count"), len(u.get("solved") or [])))
    elif what == "cmds":
        for tag, raw in db.search_pairs(tag="cmd:", type_="both"):
            print(tag, raw)
    else:
        print("未知类别: %s" % what)
        return 1
    return 0


def cmd_inspect(args, cfg, db, store):
    sid = str(args.sid)
    sub = store.get_sub(sid)
    print("=== sub:%s ===" % sid)
    print(json.dumps(sub, ensure_ascii=False, indent=2))
    res = store.get_result(sid)
    if res:
        print("=== res:%s ===" % sid)
        print(json.dumps({k: v for k, v in res.items() if k != "cases"},
                         ensure_ascii=False, indent=2))
        for c in res.get("cases", []):
            print("  case %-3s %-4s %6sms %8sKB %s" % (c.get("i"), c.get("verdict"),
                                                       c.get("time_ms"), c.get("memory_kb"),
                                                       str(c.get("msg", ""))[:60]))
    code = store.get_code(sid)
    if not code:
        # 加密提交的明文不会留在云端（判题机取码时就清掉了），改看判题机本地留存
        for name in ("main.cpp", "main.c", "main.py", "Main.java", "main.pas"):
            path = os.path.join(cfg.path("work"), sid, name)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                code = read_file(path)
                print("=== 源码取自判题机本地 %s（云端密文已按设计清除） ===" % name)
                break
    if args.code and code:
        print("=== code:%s (%d 字节) ===" % (sid, len(code)))
        print(code)
    elif args.code:
        print("（本机没有留存该提交的源码：可能已被清理或换过机器）")
    return 0


def _rejudge_targets(db, store, args):
    if args.sid:
        return [str(s) for s in args.sid]
    if args.pid:
        rows = []
        for _, raw in db.search_pairs(tag="sub:", type_="both"):
            s = store.loads(raw, None)
            if not isinstance(s, dict) or s.get("pid") not in args.pid:
                continue
            if args.all or s.get("verdict") not in ("AC", "SKIP"):
                rows.append(s)
        rows.sort(key=lambda s: int(s.get("ts") or 0))
        return [s["sid"] for s in rows[:args.limit]]
    return []


def cmd_rejudge(args, cfg, db, store):
    """默认走**候选重判**（对齐 MiniJudge）：先出候选结果，再由 apply/cancel 决定发布。"""
    targets = _rejudge_targets(db, store, args)
    if not targets:
        print("没有需要重测的提交")
        return 1
    if args.direct:
        for sid in targets:
            sub = store.get_sub(sid)
            if not sub:
                continue
            sub.update({"status": STATUS_PENDING, "verdict": "", "score": 0,
                        "msg": "重测排队中", "lease_token": "", "lease_until": 0})
            store.put_sub(sub)
            store.enqueue(sid, sub)
        print("[rejudge] 直接重测 %d 条：%s" % (len(targets), ", ".join(targets)))
    else:
        bid = store.create_rejudge_batch(targets, by=args.by or "cli", note=args.note or "")
        print("[rejudge] 已创建候选重判批次 %s，共 %d 条" % (bid, len(targets)))
        print("         判完后：admin_cli.py apply-rejudge --batch %s" % bid)
        print("         或撤销：admin_cli.py cancel-rejudge --batch %s" % bid)
    print("提示：判题机 daemon 下一轮会自动取走并重判")
    return 0


def cmd_apply_rejudge(args, cfg, db, store):
    n, err = store.apply_rejudge(args.batch)
    if err:
        print("失败:", err)
        return 1
    print("[apply-rejudge] 已发布 %d 条候选结果（批次 %s）" % (n, args.batch))
    return 0


def cmd_cancel_rejudge(args, cfg, db, store):
    n, err = store.cancel_rejudge(args.batch)
    if err:
        print("失败:", err)
        return 1
    print("[cancel-rejudge] 已撤销 %d 条候选结果（批次 %s）" % (n, args.batch))
    return 0


def cmd_batches(args, cfg, db, store):
    rows = store.list_rejudge_batches()
    if not rows:
        print("没有重判批次")
        return 0
    for b in rows[:args.limit]:
        sids = b.get("sids") or []
        ready = sum(1 for sid in sids
                    if (store.get_sub(sid) or {}).get("candidate_status") == "done")
        print("[%s] status=%-9s 候选就绪 %d/%d  by=%-8s %s"
              % (b.get("batch"), b.get("status"), ready, len(sids),
                 b.get("by"), b.get("note", "")))
    return 0


def cmd_backup(args, cfg, db, store):
    path = args.out or os.path.join(cfg.path("state"), "backup-%s.json"
                                    % time.strftime("%Y%m%d-%H%M%S"))
    n = store.backup_to_file(path, note=args.note or "")
    print("[backup] 已导出 %d 个标签 -> %s（%.1f KB）"
          % (n, path, os.path.getsize(path) / 1024.0))
    return 0


def cmd_restore(args, cfg, db, store):
    if not args.file:
        raise SystemExit("需要 --file 指定备份文件")
    wrote, skipped = store.restore_from_file(args.file, only_missing=args.only_missing)
    print("[restore] 写入 %d 个标签，跳过 %d 个（only_missing=%s）"
          % (wrote, skipped, args.only_missing))
    store.cache_drop()
    store.rebuild_rank()
    print("         本地题目缓存已清空，排行榜已刷新")
    return 0


def cmd_testusers(args, cfg, db, store):
    """生成练习用测试账号（对齐 MiniJudge 的 create-test-users）。"""
    import random as _r
    import string
    n = int(args.count or 5)
    lines = []
    for i in range(1, n + 1):
        user = "%s%d" % (args.prefix or "user", i)
        if store.get_user(user):
            lines.append("%s\t(已存在，未改动)" % user)
            continue
        pwd = "".join(_r.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        ok, res = store.create_user(user, pwd, nick=user)
        lines.append("%s\t%s" % (user, pwd) if ok else "%s\t失败: %s" % (user, res))
    out = os.path.join(cfg.path("state"), "test-accounts.txt")
    write_file(out, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n凭据已写入 %s（只把对应行交给每位参赛者）" % out)
    return 0


def cmd_keygen(args, cfg, db, store):
    """生成判题机 RSA 私钥并发布公钥到云端（前端用 oj:pubkey 加密代码）。"""
    import crypto as ojcrypto
    path = cfg.getv("crypto.private_key") or os.path.join(cfg.path("state"), "judge_key.json")
    if args.force and os.path.isfile(path):
        os.remove(path)
        print("[keygen] 已删除旧私钥 %s" % path)
    jwk = ojcrypto.load_or_create_keypair(path, int(cfg.getv("crypto.key_bits", 2048)),
                                          lambda lvl, m: print("[%s] %s" % (lvl, m)))
    pub = ojcrypto.public_jwk(jwk)
    fp = ojcrypto.fingerprint(pub)
    store.publish_pubkey(pub, fp)
    print("[keygen] 私钥: %s" % path)
    print("[keygen] 公钥已发布 oj:pubkey，指纹 %s（%d 位）" % (fp, ojcrypto.key_size(jwk) * 8))
    print("[keygen] 每次换钥匙都要重新发布，旧密文提交将无法解密")
    return 0


def cmd_pubkey(args, cfg, db, store):
    pub = store.get_pubkey()
    if not pub:
        print("云端还没有公钥，先运行：admin_cli.py keygen")
        return 1
    print(json.dumps(pub, ensure_ascii=False, indent=2)[:800])
    return 0


def cmd_import_problem(args, cfg, db, store):
    """MiniJudge 风格入口：导入题包目录（-p 可给多个 PID）。"""
    for pid in args.pid:
        push_problem(cfg, store, pid)
    return 0


def cmd_rank(args, cfg, db, store):
    snap = store.rebuild_rank()
    mode = snap.get("mode", "score")
    print("模式=%s  开赛=%s  罚时=%s 分钟/次失败  人数=%d"
          % (mode, snap.get("contest_start"), snap.get("penalty_min"), snap.get("total")))
    pids = snap.get("problems") or []
    if mode != "acm":
        print("%-4s %-16s %-6s %-5s %-6s" % ("#", "user", "score", "ac", "submit"))
        for row in snap["order"][:args.limit]:
            print("%-4s %-16s %-6s %-5s %-6s"
                  % (row["rank"], row["user"], row["score"], row["ac"], row["submit"]))
        return 0
    print("%-4s %-14s %-5s %-6s %s" % ("#", "user", "通过", "罚时", "逐题"))
    for row in snap["order"][:args.limit]:
        cells = row.get("cells") or {}
        cs = []
        for p in pids:
            c = cells.get(p)
            if not c:
                cs.append("%s:·" % p)
            elif c.get("v") == "ac":
                cs.append("%s:%d%s" % (p, c.get("t", 0),
                                       ("+%d" % c["f"]) if c.get("f") else ""))
            else:
                cs.append("%s:-%d" % (p, c.get("f", 0)))
        print("%-4s %-14s %-5s %-6s %s"
              % (row["rank"], row["user"], row["solved"], row["penalty"], " ".join(cs)))
    print("（AC 数字=距开赛分钟数，+N=通过前失败次数；-N=尚未通过的失败次数）")
    return 0


def cmd_archive(args, cfg, db, store):
    n = store.archive(ttl_h=args.ttl_hours, keep_last=args.keep)
    print("[archive] 归档 %d 条（TTL=%sh，保留最近 %d 条不归档）" % (n, args.ttl_hours, args.keep))
    return 0


def cmd_gc(args, cfg, db, store):
    n = store.recover_stale()
    s = store.cleanup_sessions()
    store.rebuild_rank()
    store.write_meta()
    print("[gc] 崩溃恢复 %d 条，清理会话 %d 个，排行榜已刷新" % (n, s))
    return 0


def cmd_stats(args, cfg, db, store):
    lang = ojjudge.Judge(cfg)
    print("标签总数 :", db.count())
    print("题目     :", len(store.list_problem_ids()))
    print("用户     :", len(store.list_users()))
    print("在线判题机:", [j.get("id") for j in store.judges_online()])
    print("可用语言 :", ", ".join(sorted(lang.available_langs())) or "无！")
    for k, v in sorted(lang.lang_status.items()):
        if v:
            print("  缺失 %-6s -> %s" % (k, ", ".join(v)))
    print("API 统计 :", db.snapshot_stats())
    return 0


def cmd_get(args, cfg, db, store):
    v = db.get(args.tag)
    print(v)
    return 0 if v is not None else 1


def cmd_put(args, cfg, db, store):
    ok = db.update(args.tag, args.value)
    print("ok" if ok else "failed")
    return 0 if ok else 1


def cmd_del(args, cfg, db, store):
    print("ok" if db.delete(args.tag) else "failed")
    return 0


def cmd_adduser(args, cfg, db, store):
    ok, res = store.create_user(args.user, args.password, args.nick, is_admin=args.admin)
    print(res if ok else ("失败: " + str(res)))
    return 0 if ok else 1


def cmd_initdb(args, cfg, db, store):
    store.write_meta()
    store.rebuild_rank()
    store.set_ann("欢迎使用 OJ-OJOJOJ", "本 OJ 由本机判题后端提供服务。")
    print("已初始化 oj:meta / rank / ann:latest")
    return 0


# ==================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser(description="OJ-OJOJOJ 运维 CLI")
    ap.add_argument("--config", default=None)
    ap.add_argument("--set", dest="overrides", action="append", default=[])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe").set_defaults(func=cmd_probe)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("initdb").set_defaults(func=cmd_initdb)
    sub.add_parser("gc").set_defaults(func=cmd_gc)

    p = sub.add_parser("seed"); p.add_argument("--pid", action="append"); p.set_defaults(func=cmd_seed)

    p = sub.add_parser("mkproblem")
    p.add_argument("--pid", required=True); p.add_argument("--title")
    p.add_argument("--statement"); p.add_argument("--difficulty", default="easy")
    p.add_argument("--tl", type=int, default=1000); p.add_argument("--ml", type=int, default=262144)
    p.add_argument("--ol", type=int, default=65536); p.add_argument("--checker", default="diff")
    p.set_defaults(func=cmd_mkproblem)

    p = sub.add_parser("push"); p.add_argument("--pid", action="append", required=True)
    p.set_defaults(func=cmd_push)
    p = sub.add_parser("pull"); p.add_argument("--pid", action="append", required=True)
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("list")
    p.add_argument("--what", default="problems",
                   choices=["problems", "subs", "queue", "judges", "users", "cmds"])
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("inspect"); p.add_argument("--sid", required=True)
    p.add_argument("--code", action="store_true"); p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("rejudge")
    p.add_argument("--sid", action="append"); p.add_argument("--pid", action="append")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--all", action="store_true", help="连 AC 的也一起重判")
    p.add_argument("--direct", action="store_true", help="直接重判，不走候选批次")
    p.add_argument("--by", default="cli"); p.add_argument("--note", default="")
    p.set_defaults(func=cmd_rejudge)

    p = sub.add_parser("apply-rejudge"); p.add_argument("--batch", required=True)
    p.set_defaults(func=cmd_apply_rejudge)
    p = sub.add_parser("cancel-rejudge"); p.add_argument("--batch", required=True)
    p.set_defaults(func=cmd_cancel_rejudge)
    p = sub.add_parser("batches"); p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_batches)

    p = sub.add_parser("backup"); p.add_argument("--out"); p.add_argument("--note", default="")
    p.set_defaults(func=cmd_backup)
    p = sub.add_parser("restore"); p.add_argument("--file"); p.add_argument("--only-missing",
                                                                          action="store_true")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("test-users"); p.add_argument("--count", type=int, default=5)
    p.add_argument("--prefix", default="user"); p.set_defaults(func=cmd_testusers)

    p = sub.add_parser("import-problem")
    p.add_argument("--pid", action="append", required=True)
    p.set_defaults(func=cmd_import_problem)

    p = sub.add_parser("keygen"); p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_keygen)
    sub.add_parser("pubkey").set_defaults(func=cmd_pubkey)

    p = sub.add_parser("rank"); p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("archive"); p.add_argument("--ttl-hours", type=float, default=24)
    p.add_argument("--keep", type=int, default=60); p.set_defaults(func=cmd_archive)

    p = sub.add_parser("get"); p.add_argument("tag"); p.set_defaults(func=cmd_get)
    p = sub.add_parser("put"); p.add_argument("tag"); p.add_argument("value")
    p.set_defaults(func=cmd_put)
    p = sub.add_parser("del"); p.add_argument("tag"); p.set_defaults(func=cmd_del)

    p = sub.add_parser("adduser")
    p.add_argument("--user", required=True); p.add_argument("--pass", dest="password", required=True)
    p.add_argument("--nick"); p.add_argument("--admin", action="store_true")
    p.set_defaults(func=cmd_adduser)

    args = ap.parse_args(argv)
    cfg, db, store = build(args)
    try:
        return args.func(args, cfg, db, store)
    except TwdbError as e:
        print("云端错误: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""环境自检：目录 / 配置 / 云端 API / 编译器 / 判题沙箱。

  python tools/selfcheck.py            # 全部检查
  python tools/selfcheck.py --fix-hint # 附带修复建议
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

OK = "[ OK ]"
BAD = "[FAIL]"
WARN = "[WARN]"


def line(tag, name, detail=""):
    print("%s %-26s %s" % (tag, name, detail))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-hint", action="store_true")
    a = ap.parse_args()

    print("=" * 78)
    print(" OJ-OJOJOJ 判题后端 环境自检   %s" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 78)

    # ---------- 1. 主机 ----------
    line(OK, "主机", "%s %s / %s 核" % (platform.system(), platform.release(),
                                        os.cpu_count()))
    line(OK, "工作区", ROOT)
    line(OK, "Python", "%s (%s)" % (sys.version.split()[0], sys.executable))

    # ---------- 2. 配置 ----------
    cfg = None
    try:
        import config as ojconfig
        cfg = ojconfig.load()
        line(OK, "配置", cfg.source)
    except Exception as e:  # noqa: BLE001
        line(BAD, "配置", "无法加载 config/oj_config.json: %r" % e)
        return 1

    # ---------- 3. 目录可写 ----------
    for name in ("data", "problems", "work", "cache", "state", "logs"):
        try:
            p = cfg.path(name)
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".write_probe")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            line(OK, "目录 " + name, p)
        except Exception as e:  # noqa: BLE001
            line(BAD, "目录 " + name, "%r" % e)

    # ---------- 4. 云端 API ----------
    try:
        from twdb import TinyWebDB
        db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                       timeout_s=cfg.getv("api.timeout_s", 15), retries=1)
        info = db.ping()
        if info.get("ok"):
            line(OK, "云端 API", "%s 标签数=%s %sms" % (cfg.getv("api.base"), info["count"], info["ms"]))
        else:
            line(BAD, "云端 API", str(info))
        t = db.search(tag="prob:", count=100, type_="tag")
        ids = t.get("__tags__", [])
        line(OK, "云端题库", "%d 个题目标签: %s" % (len(ids), ", ".join(ids[:6])))
        line(OK, "浏览页", cfg.getv("api.browse"))
    except Exception as e:  # noqa: BLE001
        line(BAD, "云端 API", "%r" % e)

    # ---------- 5. 工具链 ----------
    try:
        import judge as ojjudge
        j = ojjudge.Judge(cfg, lambda lvl, m: None)
        av = j.available_langs()
        for key, lc in sorted(cfg.lang_table().items()):
            miss = j.lang_status.get(key) or []
            if miss:
                line(WARN, "语言 " + key, "缺少 %s（该语言暂不可判）" % ", ".join(miss))
            else:
                line(OK, "语言 " + key, lc.get("name", ""))
        if not av:
            line(BAD, "可用语言", "没有可用语言，无法判题！")
    except Exception as e:  # noqa: BLE001
        line(BAD, "语言自检", "%r" % e)

    # ---------- 6. 沙箱执行器 ----------
    try:
        import runner
        d = tempfile.mkdtemp(prefix="ojcheck_")
        r = runner.run_process([sys.executable, "-c", "print('judge-ok')"],
                               cwd=d, stdin_path=os.devnull,
                               stdout_path=os.path.join(d, "o"), stderr_path=os.path.join(d, "e"),
                               time_limit_ms=8000)
        out = ""
        try:
            with open(os.path.join(d, "o")) as f:
                out = f.read().strip()
        except OSError:
            pass
        line(OK, "执行器", "%s 输出=%r 用时=%sms 内存=%sKB" % (r.status, out, r.time_ms, r.memory_kb))
        r2 = runner.run_process([sys.executable, "-c", "while True: pass"], cwd=d,
                                stdin_path=os.devnull, stdout_path=os.path.join(d, "o2"),
                                stderr_path=os.path.join(d, "e2"), time_limit_ms=700)
        line(OK if r2.status == "tle" else WARN, "超时熔断", "%s %sms（期望 tle）" % (r2.status, r2.time_ms))
        g = runner.JobGuard(65536, 1, True) if os.name == "nt" else None
        if g is not None:
            line(OK if g.ok else WARN, "Windows Job Object",
                 "可用（内存/进程数/孤儿回收）" if g.ok else "不可用: %s（退化为采样限制）" % g.reason)
            g.close()
    except Exception as e:  # noqa: BLE001
        line(BAD, "沙箱执行器", "%r" % e)

    # ---------- 6. 安全文本编解码（KV 的硬约束） ----------
    try:
        import store as store_mod
        samples = ["plain", "line1\nline2", "it's", 'q"q', "back\\slash", "tab\there",
                   "混合中文\n'单引号'\"双引号\"\\反斜杠"]
        bad = [s for s in samples if store_mod.unsafe(store_mod.safe(s)) != s]
        line(OK if not bad else BAD, "本地编码往返",
             "全部通过" if not bad else "失败: %r" % bad)
        import json as _json
        enc = _json.dumps(store_mod.safe_obj({"a": "x\ny", "b": "it's"}), ensure_ascii=False)
        line(OK if ("\\" not in enc and "\n" not in enc) else BAD, "KV 安全 JSON",
             enc[:60])
    except Exception as e:  # noqa: BLE001
        line(BAD, "本地编码往返", "%r" % e)

    # ---------- 7. 云端编码往返（实写实读） ----------
    try:
        from twdb import TinyWebDB
        from store import Store
        db2 = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                        timeout_s=cfg.getv("api.timeout_s", 15), retries=3,
                        min_interval_s=cfg.getv("api.min_interval_s", 0.45))
        st2 = Store(db2, cfg)
        probe = {"msg": "gcc: cannot execute 'x'\nsecond line", "cases": [{"note": "50%"}]}
        st2.put_json("selfcheck:enc", probe)
        back = st2.get_json("selfcheck:enc", None)
        db2.delete("selfcheck:enc")
        line(OK if back == probe else BAD, "云端编码往返",
             "引号/换行/百分号/反斜杠均无损" if back == probe else "读回不一致: %r" % (back,))
    except Exception as e:  # noqa: BLE001
        line(BAD, "云端编码往返", "%r" % e)

    # ---------- 8. 判题链路冒烟（真编译 + 真运行 + 真判定） ----------
    try:
        import judge as ojjudge
        d = os.path.join(cfg.path("work"), "_selfcheck")
        os.makedirs(d, exist_ok=True)
        j = ojjudge.Judge(cfg, lambda lvl, m: None)
        lang = "cpp" if "cpp" in j.available_langs() else ("c" if "c" in j.available_langs() else "py")
        code = {"cpp": '#include <cstdio>\nint main(){int a,b;if(scanf("%d %d",&a,&b)!=2)return 0;printf("%d\\n",a+b);return 0;}\n',
                "c": '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}\n',
                "py": "import sys\na,b=map(int,sys.stdin.read().split())\nprint(a+b)\n"}[lang]
        problem = {"pid": "SELFCHECK", "title": "self", "time_limit_ms": 2000,
                   "memory_limit_kb": 262144, "output_limit_kb": 65536,
                   "checker": "diff", "total_score": 10}
        tests = [{"i": 1, "in": "1 2\n", "out": "3\n", "score": 10}]
        sub = {"sid": "selfcheck", "lang": lang}
        (verdict, score, cases, clog, ms, kb, msg, chk) = j.judge_submission(
            sub, code, problem, tests, d)
        line(OK if verdict == "AC" else BAD, "判题链路冒烟",
             "语言=%s verdict=%s %sms %sKB" % (lang, verdict, ms, kb))
        if verdict != "AC":
            line(WARN, "  编译/运行日志", (clog or msg)[:200])
    except Exception as e:  # noqa: BLE001
        line(BAD, "判题链路冒烟", "%r" % e)

    # ---------- 9. 非对称加密链路 ----------
    try:
        import crypto as ojcrypto
        cfg_path = cfg.getv("crypto.private_key") or os.path.join(cfg.path("state"), "judge_key.json")
        jwk = ojcrypto.load_or_create_keypair(cfg_path, int(cfg.getv("crypto.key_bits", 2048)))
        pub = ojcrypto.public_jwk(jwk)
        fp = ojcrypto.fingerprint(pub)
        line(OK, "判题机密钥", "%d 位 RSA-OAEP，指纹 %s" % (ojcrypto.key_size(jwk) * 8, fp))
        sample = "line1\nit's \"quoted\" — 中文注释"
        env = ojcrypto.seal(pub, sample)
        back = ojcrypto.open_sealed(jwk, env).decode("utf-8")
        line(OK if back == sample else BAD, "非对称加解密往返",
             "分块 %d，%d 字节" % (env["n"], len(sample.encode("utf-8"))))
        sig = ojcrypto.sign(jwk, b"verdict:AC")
        line(OK if ojcrypto.verify(pub, b"verdict:AC", sig) and not ojcrypto.verify(pub, b"x", sig) else BAD,
             "结果签名/验签", "正例通过、反例拒绝")
        import crypto as _c
        from twdb import TinyWebDB
        from store import Store
        db3 = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                        timeout_s=cfg.getv("api.timeout_s", 15), retries=3,
                        min_interval_s=cfg.getv("api.min_interval_s", 0.45))
        remote = Store(db3, cfg).get_pubkey()
        if not remote:
            line(WARN, "云端公钥", "oj:pubkey 还没发布（先运行 daemon 或 admin_cli keygen）")
        elif remote.get("fingerprint") == fp:
            line(OK, "云端公钥", "与本地私钥匹配（%s）" % fp)
        else:
            line(BAD, "云端公钥", "云端 %s ≠ 本地 %s（判题机换过密钥，需要重新发布）"
                 % (remote.get("fingerprint"), fp))
    except Exception as e:  # noqa: BLE001
        line(BAD, "非对称加密链路", "%r" % e)

    # ---------- 10. 本地题库 ----------
    try:
        pdir = cfg.path("problems")
        pids = [d for d in sorted(os.listdir(pdir))
                if os.path.isfile(os.path.join(pdir, d, "problem.json"))]
        line(OK if pids else WARN, "本地题库", "%d 题: %s" % (len(pids), ", ".join(pids)) or "空")
        for pid in pids:
            n = len([f for f in os.listdir(os.path.join(pdir, pid, "tests"))
                     if f.endswith(".in")]) if os.path.isdir(os.path.join(pdir, pid, "tests")) else 0
            line(OK if n else WARN, "  " + pid, "%d 个测试点" % n)
    except Exception as e:  # noqa: BLE001
        line(BAD, "本地题库", "%r" % e)

    print("-" * 78)
    if a.fix_hint:
        print("""修复建议：
  * 缺 C/C++ 编译器：把便携式工具链解压到 D:\\OJ\\tools\\w64devkit，
    然后在 config/oj_config.json 的 paths.toolchain_dirs 里加入 "D:\\\\OJ\\\\tools\\\\w64devkit\\\\bin"
    （或把该 bin 目录加入系统 PATH），再重跑本自检。
  * 缺 Python：config/oj_config.json -> paths.python 指向可用解释器绝对路径。
  * 云端 API 失败：确认 api.base 与 user/secret 正确、网络可达。
  * 判题不安全：本机判题只做弱隔离，正式对外请用独立用户 + 容器/WSL + 断网。""")
    print("自检结束。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""中控台 API 端到端自测：状态 / 一键启停 / 参数保存 / 热重载 / 运维动作。

  python tools/test_console.py [base_url]
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090").rstrip("/")


def call(path, body=None, timeout=300, head=True):
    url = BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")
    if head:
        req.add_header("X-OJ-Console", "1")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, (json.loads(raw) if raw.strip() else {})
        except ValueError:
            return e.code, {"raw": raw}
    except Exception as e:  # noqa: BLE001
        return -1, {"msg": "连接失败: %r" % e}


def check(name, cond, extra=""):
    cond = bool(cond)
    print("  %s %s%s" % ("✔" if cond else "✘", name, (" — " + str(extra)) if extra else ""))
    return cond


def main():
    ok = True
    print("== 1) 只读接口 ==")
    code, st = call("/api/status")
    ok &= check("GET /api/status", code == 200 and "running" in st,
                "running=%s pid=%s judge=%s" % (st.get("running"), st.get("pid"), st.get("judge_id")))
    ok &= check("参数白名单下发", len(st.get("editable", [])) > 10, "%d 项" % len(st.get("editable", [])))
    ok &= check("动作清单下发", len(st.get("actions", [])) > 5, "%d 个" % len(st.get("actions", [])))
    ok &= check("云端状态", (st.get("cloud") or {}).get("ok"),
                "标签数=%s 队列=%s" % ((st.get("cloud") or {}).get("count"), (st.get("cloud") or {}).get("queue")))

    print("\n== 2) 防护：缺 X-OJ-Console 头必须被拒 ==")
    code, r = call("/api/status", head=False)
    ok &= check("GET 无自定义头被拒", code == 403, "HTTP %s %s" % (code, r.get("msg", "")))
    code, r = call("/api/stop", {}, head=False)
    ok &= check("POST 无自定义头被拒", code == 403, "HTTP %s %s" % (code, r.get("msg", "")))

    print("\n== 3) 一键开关 ==")
    if st.get("running"):
        print("  · 当前在跑，先测停止（若该进程是旧版本，会走强制结束兜底）")
        code, r = call("/api/stop", {})
        print("    stop 返回: HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)[:200]))
        ok &= check("POST /api/stop", r.get("ok"), r.get("msg"))
        time.sleep(2)
        code, st2 = call("/api/status")
        ok &= check("停止后状态为未运行", not st2.get("running"), "pid=%s" % st2.get("pid"))

    code, r = call("/api/start", {"workers": 3})
    ok &= check("POST /api/start", r.get("ok"), r.get("msg"))
    time.sleep(4)
    code, st3 = call("/api/status")
    ok &= check("启动后状态为运行中", st3.get("running"), "pid=%s workers=%s" % (st3.get("pid"), st3.get("workers")))

    print("\n== 4) 暂停 / 恢复 / 热重载 ==")
    code, r = call("/api/pause", {})
    ok &= check("暂停接单", r.get("ok"), r.get("msg"))
    time.sleep(3)
    code, r = call("/api/resume", {})
    ok &= check("恢复接单", r.get("ok"), r.get("msg"))
    code, r = call("/api/reload", {})
    ok &= check("热重载配置", r.get("ok"), r.get("msg"))

    print("\n== 5) 参数保存（含非法值拦截） ==")
    code, r = call("/api/save_config", {"values": {"judge.heartbeat_interval_s": "21"}})
    ok &= check("保存合法参数", r.get("ok"), r.get("msg"))
    code, r = call("/api/save_config", {"values": {"api.value_chunk_chars": "50000"}})
    ok &= check("拦截超限分片大小", not r.get("ok"), r.get("msg"))
    code, r = call("/api/save_config", {"values": {"judge.workers": "999"}})
    ok &= check("拦截非法 worker 数", not r.get("ok"), r.get("msg"))
    code, r = call("/api/save_config", {"values": {"paths.root": "C:/evil"}})
    ok &= check("拦截白名单外字段", not r.get("ok"), r.get("msg"))
    code, r = call("/api/save_config", {"values": {"judge.heartbeat_interval_s": "20"}})
    ok &= check("改回原值", r.get("ok"), r.get("msg"))

    print("\n== 6) 运维动作 ==")
    for action in ("stats", "rank", "probe"):
        code, r = call("/api/action", {"action": action})
        ok &= check("动作 %-6s" % action, r.get("ok") and r.get("out"),
                    (r.get("out") or r.get("err") or "").strip().splitlines()[0][:70] if (r.get("out") or r.get("err")) else "")

    print("\n== 7) 日志 ==")
    code, r = call("/api/log?lines=30")
    ok &= check("日志读取", code == 200 and isinstance(r.get("lines"), list), "%d 行" % len(r.get("lines", [])))

    print("\n" + ("✅ 中控台全部检查通过" if ok else "❌ 有检查未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

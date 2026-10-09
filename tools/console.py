# -*- coding: utf-8 -*-
"""判题机中控台（本机控制面板）。

一个极简的本地 HTTP 服务，只绑 127.0.0.1，提供：

  * 状态总览：进程是否在跑、PID、在线心跳、队列深度、语言、云标签数、提交统计
  * 一键开关：启动 / 优雅停止 / 重启 / 暂停接单 / 恢复接单
  * 参数调整：直接编辑 config/oj_config.json 的关键项（带类型校验），可一键热重载
  * 运维动作：生成密钥、发布公钥、播种题库、重测批次、备份/恢复、刷榜、清理、自检
  * 实时日志：tail logs/judge.log

用法：
    python tools/console.py                # http://127.0.0.1:8090
    python tools/console.py --port 9000

安全：只监听回环地址；所有会改状态/启停进程的接口都要求
`X-OJ-Console: 1` 请求头（浏览器跨站表单无法自带自定义头，可挡掉 CSRF 式攻击）。
可选 `--token xxx` 再加一道口令。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
CONSOLE_DIR = os.path.join(ROOT, "console")
sys.path.insert(0, BACKEND)

import config as ojconfig   # noqa: E402
from twdb import TinyWebDB, TwdbError  # noqa: E402

# 中控台可以直接改的参数（白名单 + 类型 + 说明），其余字段请手改 JSON
EDITABLE = [
    ("judge.id", "str", "判题机 ID（多实例必须不同，需重启）"),
    ("judge.workers", "int", "并发 worker 数（需重启）"),
    ("judge.queue_refresh_interval_s", "float", "拉取队列间隔秒（默认 3）"),
    ("judge.cmd_poll_interval_s", "float", "命令总线轮询间隔秒"),
    ("judge.heartbeat_interval_s", "float", "心跳间隔秒"),
    ("judge.maint_interval_s", "float", "维护周期秒（归档/恢复/缓存刷新）"),
    ("judge.publish_interval_s", "float", "统计发布间隔秒"),
    ("judge.lease_seconds", "int", "任务租约秒数（超时视为失联并重试）"),
    ("judge.archive_ttl_h", "float", "提交归档 TTL 小时（0=不归档）"),
    ("judge.session_ttl_h", "float", "登录会话有效期小时"),
    ("judge.batch_user_stats", "bool", "用户统计攒批落库"),
    ("judge.share_mode", "str", "多机共判分单模式：auto(按余力分摊) / greedy(能抢就抢) / solo(独占)"),
    ("judge.adapt_rate_limit", "bool", "多机时自动放大请求间隔与轮询间隔（避免云端 503）"),
    ("judge.claim_min_prob", "float", "多机共判时自己至少占的单量比例（默认 0.08，防止被大机器饿死）"),
    ("judge.lease_renew_ratio", "float", "租约续期间隔占租约时长的比例（默认 0.4）"),
    ("judge.cluster_ttl_s", "int", "判定「同伴在线」的心跳有效秒数"),
    ("judge.public_case_detail", "bool", "对外返回逐点对比明细（期望/实际）—— **默认关闭，防泄露答案**"),
    ("judge.public_stderr", "bool", "RE 时把选手自己的报错输出回传（不含标准答案）"),
    ("judge.recover_on_start", "bool", "启动时恢复自己遗留的任务"),
    ("limits.compile_timeout_ms", "int", "编译超时毫秒"),
    ("limits.compile_log_max_bytes", "int", "编译日志截断字节"),
    ("limits.default_time_limit_ms", "int", "默认时间限制毫秒"),
    ("limits.default_memory_limit_kb", "int", "默认内存限制 KB"),
    ("limits.default_output_limit_kb", "int", "默认输出上限 KB"),
    ("limits.stderr_limit_kb", "int", "stderr 保留上限 KB"),
    ("limits.retry_max_attempts", "int", "判题机故障最大重试次数（JE）"),
    ("limits.isolate.active_process_limit", "int", "单次运行最大进程数"),
    ("limits.isolate.job_object", "bool", "启用 Windows Job Object 隔离"),
    ("api.base", "str", "云端 API 地址"),
    ("api.min_interval_s", "float", "本地最小请求间隔秒（防限流）"),
    ("api.retries", "int", "请求重试次数"),
    ("api.value_chunk_chars", "int", "单值分片字符数（上限 10000）"),
    ("crypto.enabled", "bool", "启用非对称加密接收代码"),
    ("crypto.seal_results", "bool", "结果加密回传"),
    ("checker.default", "str", "默认比较方式 tokens/exact/float/custom"),
]

ACTIONS = {
    "selfcheck": ("环境自检", ["tools/selfcheck.py"]),
    "keygen": ("生成判题机密钥并发布公钥", ["backend/admin_cli.py", "keygen"]),
    "pubkey": ("查看云端公钥", ["backend/admin_cli.py", "pubkey"]),
    "seed": ("把本地题库推到云端", ["backend/admin_cli.py", "seed"]),
    "probe": ("云端连通性与题目一览", ["backend/admin_cli.py", "probe"]),
    "stats": ("题库/用户/语言/API 统计", ["backend/admin_cli.py", "stats"]),
    "rank": ("刷新并打印排行榜", ["backend/admin_cli.py", "rank"]),
    "gc": ("崩溃恢复 + 清理会话 + 刷榜", ["backend/admin_cli.py", "gc"]),
    "archive": ("归档旧提交", ["backend/admin_cli.py", "archive"]),
    "backup": ("备份云端全部标签", ["backend/admin_cli.py", "backup"]),
    "subs": ("最近提交列表", ["backend/admin_cli.py", "list", "--what", "subs", "--limit", "15"]),
    "batches": ("重判批次", ["backend/admin_cli.py", "batches"]),
    "test-users": ("生成测试账号", ["backend/admin_cli.py", "test-users", "--count", "5"]),
    "cryptotest": ("前后端加密互通测试", ["tools/test_crypto_python.py"]),
}


def py_exe():
    return os.environ.get("OJ_PY") or sys.executable


# ============================================================ 进程与状态
class JudgeProcess(object):
    """中控台通过锁文件 + PID 存活来判断判题机是否在跑（不依赖自己启动过它）。"""

    def __init__(self, cfg, logger=print):
        self.cfg = cfg
        self.log = logger
        self.child = None
        self.lock = threading.Lock()

    def lock_path(self):
        return os.path.join(self.cfg.path("state"), "daemon.lock")

    def ctl_path(self):
        return os.path.join(self.cfg.path("state"), "ctl.json")

    @staticmethod
    def pid_alive(pid):
        if not pid:
            return False
        try:
            if os.name == "nt":
                import ctypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                h = k32.OpenProcess(0x1000, False, int(pid))
                if not h:
                    return False
                code = ctypes.c_ulong(0)
                k32.GetExitCodeProcess(h, ctypes.byref(code))
                k32.CloseHandle(h)
                return code.value == 259
            os.kill(int(pid), 0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def info(self):
        """返回 {running, pid, judge_id, started, host, alive}"""
        try:
            with open(self.lock_path(), "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        pid = int(info.get("pid") or 0)
        alive = self.pid_alive(pid)
        info.update({"running": alive, "pid": pid if alive else 0})
        return info

    def start(self, workers=None, verbose=True, extra=None):
        with self.lock:
            st = self.info()
            if st.get("running"):
                return False, "判题机已在运行（pid=%s）" % st["pid"]
            self._clear_ctl()          # 关键：清掉上一次遗留的控制指令
            args = [py_exe(), os.path.join(BACKEND, "daemon.py")]
            args += ["--workers", str(int(workers or self.cfg.getv("judge.workers", 4)))]
            if verbose:
                args.append("--verbose")
            args += list(extra or [])
            logdir = self.cfg.path("logs")
            os.makedirs(logdir, exist_ok=True)
            out = open(os.path.join(logdir, "daemon.out.log"), "a", encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            creation = 0x00000008 if os.name == "nt" else 0   # DETACHED_PROCESS
            self.child = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                          env=env, creationflags=creation, close_fds=True)
            # 等锁文件出现（说明真正起来了）
            for _ in range(40):
                time.sleep(0.25)
                if self.info().get("running"):
                    return True, "已启动 pid=%s" % self.info().get("pid")
            return True, "已拉起进程（pid=%s），锁文件尚未就绪，请查看日志" % self.child.pid

    def _clear_ctl(self):
        try:
            if os.path.isfile(self.ctl_path()):
                os.remove(self.ctl_path())
        except OSError:
            pass

    def _write_ctl(self, cmd, wait=20):
        os.makedirs(os.path.dirname(self.ctl_path()), exist_ok=True)
        payload = {"cmd": cmd, "by": "console", "ts": int(time.time())}
        if os.path.isfile(self.ctl_path()):
            try:
                os.remove(self.ctl_path())
            except OSError:
                pass
        with open(self.ctl_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        for _ in range(int(wait * 4)):
            time.sleep(0.25)
            try:
                with open(self.ctl_path(), "r", encoding="utf-8") as f:
                    back = json.load(f)
                if back.get("ack"):
                    return True, back.get("msg", "已受理")
            except (OSError, ValueError):
                pass
        return False, "判题机没有在 %ss 内响应控制指令" % wait

    def stop(self, force_after=25):
        with self.lock:
            st = self.info()
            if not st.get("running"):
                return True, "判题机本来就没在运行"
            ok, msg = self._write_ctl("stop", wait=force_after)
            for _ in range(int(force_after * 2)):
                if not self.info().get("running"):
                    self._clear_ctl()
                    return True, "已优雅停止（%s）" % msg
                time.sleep(0.5)
            # 兜底：强杀
            pid = st["pid"]
            self.log("优雅停止超时，强制结束 pid=%s" % pid)
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, 9)
            time.sleep(1)
            try:
                os.remove(self.lock_path())
            except OSError:
                pass
            self._clear_ctl()
            return True, "已强制结束 pid=%s（下次启动会自动恢复遗留任务）" % pid

    def restart(self, **kw):
        self.stop()
        return self.start(**kw)

    def control(self, cmd):
        st = self.info()
        if not st.get("running"):
            return False, "判题机没在运行"
        return self._write_ctl(cmd, wait=10)


# ============================================================ 云端只读信息
def cloud_status(cfg):
    out = {"ok": False}
    try:
        db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                       timeout_s=cfg.getv("api.timeout_s", 15), retries=1,
                       min_interval_s=cfg.getv("api.min_interval_s", 0.45))
        t0 = time.time()
        out["count"] = db.count()
        out["ms"] = int((time.time() - t0) * 1000)
        out["ok"] = True
        try:
            tags = db.search(tag="q:", count=100, type_="tag")
            out["queue"] = len(tags.get("__tags__", []))
        except TwdbError:
            out["queue"] = -1
        try:
            j = db.get_json("judge:" + str(cfg.getv("judge.id")), None) or {}
            out["heartbeat"] = j
        except TwdbError:
            out["heartbeat"] = {}
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def tail_log(cfg, lines=200):
    path = os.path.join(cfg.path("logs"), "judge.log")
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, max(4096, lines * 220))
            f.seek(size - block)
            data = f.read().decode("utf-8", "replace")
        rows = data.splitlines()[-lines:]
        return rows
    except OSError:
        return []


def run_cli(args, timeout=180):
    cmd = [py_exe(), os.path.join(ROOT, args[0])] + list(args[1:])
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        return {"ok": r.returncode == 0, "code": r.returncode,
                "out": (r.stdout or "")[-8000:], "err": (r.stderr or "")[-4000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "out": "", "err": "超时（%ss）" % timeout}


# ============================================================ HTTP 服务
class Console(object):
    def __init__(self, cfg, token=None):
        self.cfg = cfg
        self.token = token
        self.proc = JudgeProcess(cfg, lambda m: print("[console] %s" % m))
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")

    def status(self):
        st = self.proc.info()
        cloud = cloud_status(self.cfg)
        cluster = {"judges": 0, "rows": [], "error": ""}
        try:
            sys.path.insert(0, BACKEND)
            from twdb import TinyWebDB as _T
            from store import Store as _S
            db = _T(self.cfg.getv("api.base"), self.cfg.getv("api.user"),
                    self.cfg.getv("api.secret"), min_interval_s=0.2, retries=2)
            cluster = _S(db, self.cfg).cluster_summary()
        except Exception as e:  # noqa: BLE001
            cluster["error"] = str(e)[:120]
        langs = []
        try:
            sys.path.insert(0, BACKEND)
            import judge as ojjudge
            j = ojjudge.Judge(self.cfg, lambda lvl, m: None)
            langs = sorted(j.available_langs())
        except Exception:  # noqa: BLE001
            pass
        return {
            "running": st.get("running", False),
            "pid": st.get("pid", 0),
            "judge_id": st.get("judge_id") or self.cfg.getv("judge.id"),
            "started": st.get("started", ""),
            "host": st.get("host", ""),
            "paused": bool((cloud.get("heartbeat") or {}).get("paused")),
            "busy": (cloud.get("heartbeat") or {}).get("busy"),
            "workers": (cloud.get("heartbeat") or {}).get("workers"),
            "langs": langs,
            "cloud": cloud,
            "config_path": self.cfg.source,
            "crypto": {
                "enabled": bool(self.cfg.getv("crypto.enabled", True)),
                "seal_results": bool(self.cfg.getv("crypto.seal_results", True)),
                "key_file": self.cfg.getv("crypto.private_key"),
                "key_exists": os.path.isfile(self.cfg.getv("crypto.private_key") or ""),
            },
            "editable": self.editable_values(),
            "cluster": cluster,
            "actions": [{"id": k, "label": v[0]} for k, v in ACTIONS.items()],
            "console_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "console_started": self.started,
        }

    def editable_values(self):
        rows = []
        for key, typ, desc in EDITABLE:
            rows.append({"key": key, "type": typ, "desc": desc,
                         "value": self.cfg.getv(key)})
        return rows

    def save_config(self, values):
        """校验并写回 config/oj_config.json；返回 (ok, msg, changed)"""
        allowed = {k: t for k, t, _ in EDITABLE}
        changed = []
        for key, raw in (values or {}).items():
            if key not in allowed:
                return False, "不允许修改的配置项: %s" % key, changed
            typ = allowed[key]
            try:
                if typ == "int":
                    val = int(str(raw).strip())
                elif typ == "float":
                    val = float(str(raw).strip())
                elif typ == "bool":
                    val = str(raw).strip().lower() in ("1", "true", "yes", "on")
                else:
                    val = str(raw).strip()
            except ValueError:
                return False, "%s 的值不合法: %r" % (key, raw), changed
            if key == "api.value_chunk_chars" and not (1000 <= val <= 10000):
                return False, "api.value_chunk_chars 必须在 1000~10000（实测 20000 会被云端破坏）", changed
            if key == "judge.workers" and not (1 <= val <= 64):
                return False, "judge.workers 必须在 1~64", changed
            if key == "checker.default" and val not in ("tokens", "exact", "float", "custom"):
                return False, "checker.default 只能是 tokens/exact/float/custom", changed
            if self.cfg.getv(key) != val:
                changed.append("%s: %r → %r" % (key, self.cfg.getv(key), val))
                self.cfg.setv(key, val)
        if not changed:
            return True, "没有需要保存的改动", changed
        # 整份写回（Config 就是原文件的 dict，结构保持；注释/缩进用标准 JSON）
        tmp = self.cfg.source + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self.cfg), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cfg.source)
        return True, "已保存 %d 项；点『热重载』让运行中的判题机立即生效" % len(changed), changed


class Handler(BaseHTTPRequestHandler):
    server_version = "OJConsole/1.0"
    console: Console = None

    # ---------------- 基础工具
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _guard(self):
        """仅允许本机 + 必须带自定义头（挡跨站表单）+ 可选 token。"""
        addr = self.client_address[0]
        if addr not in ("127.0.0.1", "::1", "localhost"):
            self._json({"ok": False, "msg": "中控台只允许本机访问"}, 403)
            return False
        if self.headers.get("X-OJ-Console") != "1":
            self._json({"ok": False, "msg": "缺少 X-OJ-Console 头（防跨站请求）"}, 403)
            return False
        if self.console.token and self.headers.get("X-OJ-Token") != self.console.token:
            self._json({"ok": False, "msg": "token 不正确"}, 403)
            return False
        return True

    def log_message(self, fmt, *args):
        sys.stderr.write("[console] %s - %s\n" % (self.address_string(), fmt % args))

    # ---------------- 路由
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._file(os.path.join(CONSOLE_DIR, "index.html"), "text/html; charset=utf-8")
        if path == "/assets/style.css":
            return self._file(os.path.join(CONSOLE_DIR, "style.css"), "text/css; charset=utf-8")
        if path == "/assets/console.js":
            return self._file(os.path.join(CONSOLE_DIR, "console.js"), "application/javascript; charset=utf-8")
        if path.startswith("/api/"):
            if not self._guard():          # 读接口同样要求自定义头，防跨站窥探
                return
        if path == "/api/status":
            return self._json(self.console.status())
        if path == "/api/log":
            q = urllib.parse.parse_qs(parsed.query)
            n = int((q.get("lines") or ["200"])[0])
            return self._json({"lines": tail_log(self.console.cfg, n)})
        if path == "/api/export_config":
            with open(self.console.cfg.source, "r", encoding="utf-8") as f:
                return self._json({"json": f.read()})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard():
            return
        body = self._body()
        c = self.console
        if path == "/api/start":
            ok, msg = c.proc.start(workers=body.get("workers"), verbose=bool(body.get("verbose", True)),
                                   extra=body.get("extra") or [])
            return self._json({"ok": ok, "msg": msg})
        if path == "/api/stop":
            ok, msg = c.proc.stop()
            return self._json({"ok": ok, "msg": msg})
        if path == "/api/restart":
            ok, msg = c.proc.restart(workers=body.get("workers"), verbose=True)
            return self._json({"ok": ok, "msg": msg})
        if path in ("/api/pause", "/api/resume", "/api/reload"):
            ok, msg = c.proc.control(path.split("/")[-1])
            return self._json({"ok": ok, "msg": msg})
        if path == "/api/save_config":
            ok, msg, changed = c.save_config(body.get("values"))
            return self._json({"ok": ok, "msg": msg, "changed": changed})
        if path == "/api/action":
            action = str(body.get("action") or "")
            if action not in ACTIONS:
                return self._json({"ok": False, "msg": "未知动作: %s" % action}, 400)
            label, args = ACTIONS[action]
            extra = body.get("args") or []
            res = run_cli(args + [str(x) for x in extra])
            res["label"] = label
            res["cmd"] = " ".join(args + [str(x) for x in extra])
            return self._json(res)
        if path == "/api/quick_submit":
            # 便于验证：用明文客户端提交一次（走 mock_client）
            res = run_cli(["tools/mock_client.py", "submit",
                           "--user", str(body.get("user") or "console"),
                           "--pid", str(body.get("pid") or "P1001"),
                           "--sample", str(body.get("sample") or "ac")], timeout=240)
            return self._json(res)
        return self._json({"ok": False, "msg": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="判题机中控台")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--token", default=None, help="可选访问口令")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()

    cfg = ojconfig.load(a.config)
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)

    Handler.console = Console(cfg, token=a.token)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print("=" * 72)
    print(" 判题机中控台  http://%s:%d/" % (a.bind, a.port))
    print(" 配置文件      %s" % cfg.source)
    print(" 判题机 ID     %s" % cfg.getv("judge.id"))
    print("（只监听回环地址；Ctrl+C 退出中控台，不会停止判题机）")
    if a.token:
        print(" 访问口令      %s" % a.token)
    print("=" * 72)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n中控台已停止（判题机未被停止）")


if __name__ == "__main__":
    main()

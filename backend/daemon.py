# -*- coding: utf-8 -*-
"""判题机主进程：轮询云端 → 乐观锁认领 → 编译执行判分 → 回写结果。

线程模型
--------
  [main]      心跳 / 维护（排行榜·归档·会话清理·崩溃恢复）/ 命令总线 / 回收退出
  [worker×N]  每个线程独立跑：取候选 → 认领 → 判题 → 回写

用法
----
  python daemon.py                       # 常驻，读 config/oj_config.json
  python daemon.py --workers 8 -v        # 8 并发 + 详细日志
  python daemon.py --once                # 判完当前队列就退出（适合计划任务）
  python daemon.py --set judge.poll_interval_s=1.0
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import shutil
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as ojconfig
import judge as ojjudge
from store import (Store, STATUS_PENDING, STATUS_JUDGING, STATUS_DONE,
                   new_sid, now_ts)
from twdb import TinyWebDB, TwdbError

VERSION = "1.0"


# ================================================================ 日志
class Logger(object):
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self, path=None, level="INFO", to_stdout=True):
        self.level = self.LEVELS.get(str(level).upper(), 20)
        self.to_stdout = to_stdout
        self._lock = threading.Lock()
        self._fh = None
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._fh = open(path, "a", encoding="utf-8")
            except OSError:
                self._fh = None

    def __call__(self, lvl, msg):
        n = self.LEVELS.get(str(lvl).upper(), 20)
        if n < self.level:
            return
        line = "%s [%-5s] [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), lvl,
                                      threading.current_thread().name, msg)
        with self._lock:
            if self.to_stdout:
                try:
                    print(line, flush=True)
                except Exception:  # noqa: BLE001
                    pass
            if self._fh:
                try:
                    self._fh.write(line + "\n")
                    self._fh.flush()
                except Exception:  # noqa: BLE001
                    pass

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass


# ================================================================ 判题机
class JudgeDaemon(object):
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.log = Logger(os.path.join(cfg.path("logs"), "judge.log"),
                          level="DEBUG" if args.verbose else cfg.getv("log.level", "INFO"),
                          to_stdout=not args.quiet)
        self.db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                            timeout_s=cfg.getv("api.timeout_s", 15),
                            retries=cfg.getv("api.retries", 3),
                            min_interval_s=cfg.getv("api.min_interval_s", 0.12),
                            page_size=cfg.getv("api.search_page_size", 100),
                            max_pages=cfg.getv("api.search_max_pages", 20),
                            logger=self.log)
        self.store = Store(self.db, cfg, self.log)
        self.judge = ojjudge.Judge(cfg, self.log)
        self.keypair = self._setup_crypto()
        self.store.set_keypair(self.keypair)
        self.workers = int(args.workers or cfg.getv("judge.workers", 4))
        self.stop_flag = threading.Event()
        self.paused = False
        self.ctl_ack = None
        self.boot_ts = now_ts()
        self._last_ctl_check = 0.0
        self.seen = {}
        self.seen_lock = threading.Lock()
        self.stats = {"judged": 0, "ac": 0, "ce": 0, "failed": 0, "retried": 0,
                      "cmds": 0, "recovered": 0, "archived": 0, "start_ts": now_ts()}
        self.busy = 0
        self.busy_lock = threading.Lock()
        # 本地任务队列：主循环统一向云端拉取，worker 只消费本地队列。
        # 这样 4 个 worker 不会各自去 search 云端（那是打限流的元凶）。
        self.local_queue = collections.deque()
        self.queued_sids = set()
        self.queue_cond = threading.Condition()
        self._load_seen()

    # -------------------------------------------------------------- 本地状态
    def _seen_path(self):
        return os.path.join(self.cfg.path("state"), "seen.json")

    def _load_seen(self):
        try:
            with open(self._seen_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.seen = {str(k): int(v) for k, v in data.items()}
        except (OSError, ValueError):
            self.seen = {}

    def _save_seen(self):
        with self.seen_lock:
            items = sorted(self.seen.items(), key=lambda kv: kv[1], reverse=True)
            self.seen = dict(items[:int(self.cfg.getv("judge.seen_max", 5000))])
            try:
                with open(self._seen_path(), "w", encoding="utf-8") as f:
                    json.dump(self.seen, f)
            except OSError:
                pass

    def mark_seen(self, sid):
        with self.seen_lock:
            self.seen[str(sid)] = now_ts()

    def is_seen(self, sid):
        with self.seen_lock:
            return str(sid) in self.seen

    # ---------------------------------------------------------------- 生命周期
    def _setup_crypto(self):
        """非对称加密：加载/生成判题机 RSA 私钥，并把公钥发布到云端供前端加密。"""
        if not self.cfg.getv("crypto.enabled", True):
            self.log("WARN", "crypto.enabled=false：按明文接收代码（不推荐）")
            return None
        try:
            import crypto as ojcrypto
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "加密模块不可用: %r" % e)
            return None
        path = self.cfg.getv("crypto.private_key", None) or os.path.join(
            self.cfg.path("state"), "judge_key.json")
        bits = int(self.cfg.getv("crypto.key_bits", 2048))
        jwk = ojcrypto.load_or_create_keypair(path, bits, self.log)
        pub = ojcrypto.public_jwk(jwk)
        fp = ojcrypto.fingerprint(pub)
        try:
            self.store.publish_pubkey(pub, fp)
            self.log("INFO", "公钥已发布到 oj:pubkey（指纹 %s）" % fp)
        except TwdbError as e:
            self.log("WARN", "公钥发布失败: %s" % e)
        self.log("INFO", "非对称加密就绪：%d 位 RSA-OAEP(SHA-256)，前端用 oj:pubkey 加密代码"
                 % (ojcrypto.key_size(jwk) * 8))
        return jwk

    # ---------------------------------------------------------- 中控台控制
    # 中控台（tools/console.py）通过一个本地控制文件与本进程通信：
    #   data/state/ctl.json = {"cmd":"stop|pause|resume|reload", "ts":...}
    # daemon 每轮读取一次，执行后把文件改写成 {"ack":..., "by":...}。
    # 用文件而不是杀进程：判题中途被打断会浪费一次编译，而且租约要等过期才恢复。
    def _ctl_path(self):
        return os.path.join(self.cfg.path("state"), "ctl.json")

    def _poll_control(self):
        now = time.time()
        if now - getattr(self, "_last_ctl_check", 0) < 1.5:
            return
        self._last_ctl_check = now
        try:
            with open(self._ctl_path(), "r", encoding="utf-8") as f:
                ctl = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(ctl, dict):
            return
        cmd = str(ctl.get("cmd") or "").lower()
        if not cmd or ctl.get("ack"):
            return
        # 防御：启动之前留下的旧指令（例如上次强杀残留的 stop）一律忽略
        boot = getattr(self, "boot_ts", 0)
        if int(ctl.get("ts") or 0) < boot:
            self.log("DEBUG", "忽略启动前的旧控制指令 %s（ts=%s < boot=%s）"
                     % (cmd, ctl.get("ts"), boot))
            try:
                with open(self._ctl_path(), "w", encoding="utf-8") as f:
                    json.dump({"cmd": cmd, "ack": "ignored-stale", "ts": now_ts(),
                               "pid": os.getpid()}, f)
            except OSError:
                pass
            return
        ack = {"ack": cmd, "cmd": cmd, "by": ctl.get("by", "console"), "ts": now_ts(),
               "pid": os.getpid(), "judge": self.store.judge_id}
        if cmd == "stop":
            ack["msg"] = "收到停止指令，正在优雅退出（判完手头的提交）"
            self.log("INFO", "中控台指令：停止 —— %s" % ack["msg"])
            self.stop_flag.set()
        elif cmd == "pause":
            self.paused = True
            ack["msg"] = "已暂停：不再取新提交（正在判的会判完）"
            self.log("INFO", "中控台指令：暂停")
        elif cmd == "resume":
            self.paused = False
            ack["msg"] = "已恢复接单"
            self.log("INFO", "中控台指令：恢复")
        elif cmd == "reload":
            ack["msg"] = self._reload_config()
        else:
            ack["msg"] = "未知指令: %s" % cmd
            self.log("WARN", ack["msg"])
        try:
            with open(self._ctl_path(), "w", encoding="utf-8") as f:
                json.dump(ack, f, ensure_ascii=False)
        except OSError:
            pass
        self.ctl_ack = ack

    def _reload_config(self):
        """在线重载配置：只应用可以热改的项，需要重启的项给出提示。"""
        try:
            fresh = ojconfig.load(self.cfg.source, ensure_dirs=False)
        except Exception as e:  # noqa: BLE001
            return "重载失败: %r" % e
        live = ["judge.queue_refresh_interval_s", "judge.cmd_poll_interval_s",
                "judge.heartbeat_interval_s", "judge.maint_interval_s",
                "judge.publish_interval_s", "judge.publish_min_gap_s",
                "judge.lease_seconds", "judge.lock_jitter_ms", "judge.archive_ttl_h",
                "judge.batch_user_stats", "judge.recover_on_start", "judge.seen_max",
                "judge.public_case_detail", "judge.public_stderr",
                "api.min_interval_s", "api.retries", "api.value_chunk_chars",
                "limits.compile_timeout_ms", "limits.compile_log_max_bytes",
                "limits.default_time_limit_ms", "limits.default_memory_limit_kb",
                "limits.default_output_limit_kb", "limits.stderr_limit_kb",
                "limits.retry_max_attempts", "limits.kill_grace_ms",
                "limits.isolate.active_process_limit", "limits.isolate.job_object",
                "crypto.enabled", "crypto.seal_results", "checker.default",
                "content.default"]
        changed, need_restart = [], []
        for key in live:
            old, new = self.cfg.getv(key), fresh.getv(key)
            if old != new:
                self.cfg.setv(key, new)
                changed.append("%s: %s → %s" % (key, old, new))
        for key in ("judge.workers", "judge.id", "languages", "paths"):
            if self.cfg.getv(key) != fresh.getv(key):
                need_restart.append(key)
        # 真正生效：重建 judge（语言/限制可能变了）
        try:
            self.judge = ojjudge.Judge(self.cfg, self.log)
        except Exception as e:  # noqa: BLE001
            self.log("WARN", "重建判题器失败: %r" % e)
        msg = "已热重载 %d 项" % len(changed) if changed else "配置无变化"
        if changed:
            self.log("INFO", "配置热重载: " + "; ".join(changed))
        if need_restart:
            msg += "；以下项需重启生效: " + ", ".join(need_restart)
        return msg

    def _clear_ctl(self):
        try:
            if os.path.isfile(self._ctl_path()):
                os.remove(self._ctl_path())
        except OSError:
            pass

    # ---------------------------------------------------------- 单实例锁
    # 实测教训：两个实例用同一个 judge_id 会互相抢同一个提交（租约分不清谁是谁），
    # 结果是一个进程拿密文清单去编译、另一个正常判题，判定被覆盖成 CE。
    def _lock_path(self):
        return os.path.join(self.cfg.path("state"), "daemon.lock")

    @staticmethod
    def _pid_alive(pid):
        try:
            if os.name == "nt":
                import ctypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                h = k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
                if not h:
                    return False
                code = ctypes.c_ulong(0)
                k32.GetExitCodeProcess(h, ctypes.byref(code))
                k32.CloseHandle(h)
                return code.value == 259                       # STILL_ACTIVE
            os.kill(int(pid), 0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def acquire_singleton(self):
        path = self._lock_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        pid = int(info.get("pid") or 0)
        if pid and pid != os.getpid() and self._pid_alive(pid):
            self.log("ERROR", "已经有一个判题机在跑（pid=%s judge=%s 启动于 %s）"
                     % (pid, info.get("judge_id"), info.get("started")))
            self.log("ERROR", "同机只允许一个实例；多实例请用 --allow-multi 并给每个实例不同的 judge.id")
            return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "judge_id": self.store.judge_id,
                           "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "host": os.environ.get("COMPUTERNAME", "host")}, f)
        except OSError as e:
            self.log("WARN", "写单实例锁失败（继续运行）: %r" % e)
        return True

    def release_singleton(self):
        try:
            with open(self._lock_path(), "r", encoding="utf-8") as f:
                info = json.load(f)
            if int(info.get("pid") or 0) == os.getpid():
                os.remove(self._lock_path())
        except (OSError, ValueError):
            pass

    def start(self):
        if not getattr(self.args, "allow_multi", False) and not self.acquire_singleton():
            return 2
        info = self.db.ping()
        self.log("INFO", "云端连通性: %s" % info)
        if not info.get("ok"):
            self.log("ERROR", "无法连接 TinyWebDB，请检查网络/密钥")
            return 1
        langs = self.judge.available_langs()
        self.log("INFO", "判题机 %s 启动：workers=%d 语言=%s"
                 % (self.store.judge_id, self.workers, ",".join(sorted(langs)) or "无"))
        if not langs:
            self.log("WARN", "没有任何可用语言！请先运行 tools/selfcheck.py 检查工具链")
        self.store.write_meta()
        self.store.heartbeat(self._hb_payload())
        if self.cfg.getv("judge.recover_on_start", True):
            n_left = self.store.expire_own_leases()
            if n_left:
                self.log("INFO", "作废自己上次遗留的 %d 个租约（本次启动按租约恢复）" % n_left)
        n_rec = self.store.recover_stale()
        if n_rec:
            self.log("INFO", "启动恢复：%d 个提交重新排队" % n_rec)

        threads = []
        for i in range(self.workers):
            t = threading.Thread(target=self.worker_loop, name="w%d" % i, daemon=True)
            t.start()
            threads.append(t)
        pub = threading.Thread(target=self.publisher_loop, name="pub", daemon=True)
        pub.start()
        threads.append(pub)

        if self.args.once:
            # 一次性模式：拉取 → 判完 → 连续 N 轮无活可干就退出
            idle_rounds = 0
            while not self.stop_flag.is_set():
                self.fill_queue()
                self.drain_cmds()
                time.sleep(1.0)
                with self.queue_cond:
                    empty = not self.local_queue
                if empty and self.busy == 0:
                    idle_rounds += 1
                    if idle_rounds >= 3:
                        break
                else:
                    idle_rounds = 0
            self.stop_flag.set()
        else:
            try:
                self.main_loop()
            except KeyboardInterrupt:
                self.log("INFO", "收到 Ctrl+C，正在优雅退出…")
            self.stop_flag.set()

        for t in threads:
            t.join(timeout=30)
        try:
            if self.store.flush_user_stats():
                self.store.rebuild_rank()
        except TwdbError as e:
            self.log("WARN", "退出前落库统计失败: %s" % e)
        self._save_seen()
        self.store.offline()
        self.store.write_meta()
        self.release_singleton()
        self._clear_ctl()
        self.log("INFO", "已退出。统计: %s" % json.dumps(self.stats, ensure_ascii=False))
        self.log.close()
        return 0

    def main_loop(self):
        next_hb = next_maint = next_cmd = next_fetch = 0.0
        while not self.stop_flag.is_set():
            t = time.time()
            self._poll_control()
            if t >= next_fetch:
                try:
                    self.fill_queue()
                except TwdbError as e:
                    self.log("WARN", "拉取队列失败: %s" % e)
                next_fetch = t + float(self.cfg.getv("judge.queue_refresh_interval_s", 3.0))
            if t >= next_cmd:
                self.drain_cmds()
                next_cmd = t + float(self.cfg.getv("judge.cmd_poll_interval_s", 2.0))
            if t >= next_hb:
                try:
                    self.store.heartbeat(self._hb_payload())
                except TwdbError as e:
                    self.log("WARN", "心跳失败: %s" % e)
                next_hb = t + float(self.cfg.getv("judge.heartbeat_interval_s", 15.0))
            if t >= next_maint or self.args.maint_now:
                try:
                    self.maintenance()
                except TwdbError as e:
                    self.log("WARN", "维护任务失败: %s" % e)
                next_maint = t + float(self.cfg.getv("judge.maint_interval_s", 300.0))
                self.args.maint_now = False
            time.sleep(0.4)

    # --------------------------------------------------------- 结果发布
    def publisher_loop(self):
        """用户统计与排行榜的近实时发布：队列空闲时立刻落库 + 刷榜。

        单独一个线程，避免在判题热路径上多花 HTTP 往返（云端限流很紧）。
        """
        interval = float(self.cfg.getv("judge.publish_interval_s", 2.0))
        last = 0.0
        while not self.stop_flag.is_set():
            self.stop_flag.wait(interval)
            try:
                with self.queue_cond:
                    empty = not self.local_queue
                if self.busy or not empty:
                    continue
                if not self.store.has_pending_stats():
                    continue
                if time.time() - last < float(self.cfg.getv("judge.publish_min_gap_s", 3.0)):
                    continue
                n = self.store.flush_user_stats()
                if n:
                    self.store.rebuild_rank()
                    last = time.time()
                    self.log("DEBUG", "发布统计：%d 个用户，排行榜已刷新" % n)
            except TwdbError as e:
                self.log("WARN", "发布统计失败: %s" % e)
            except Exception as e:  # noqa: BLE001
                self.log("ERROR", "发布线程异常: %r" % e)

    # --------------------------------------------------------- 任务拉取
    def fill_queue(self):
        """主循环专属：向云端拉一次待判队列 → 放进本地队列。"""
        if self.paused:
            return 0
        with self.queue_cond:
            backlog = len(self.local_queue)
        if backlog > 500:
            return 0
        cands = self.store.queue_candidates()
        if not cands or random.random() < 0.1:
            known = set(self.seen.keys()) | set(self.queued_sids)
            cands = list(cands) + self.store.unindexed_pending(seen=known)
        n = 0
        with self.queue_cond:
            for c in cands:
                sid = str(c.get("sid") or "")
                if not sid or sid in self.queued_sids:
                    continue
                # 候选重判的队列条目带 candidate 标记：绕过"已判过"去重
                if not c.get("candidate") and self.is_seen(sid):
                    continue
                self.queued_sids.add(sid)
                self.local_queue.append(c)
                n += 1
            if n:
                self.queue_cond.notify_all()
        if n:
            self.log("DEBUG", "拉取到 %d 个待判提交（本地队列 %d）" % (n, backlog + n))
        return n

    def pop_local(self, timeout=2.0):
        with self.queue_cond:
            if not self.local_queue:
                self.queue_cond.wait(timeout)
            if self.local_queue:
                return self.local_queue.popleft()
        return None

    def _hb_payload(self):
        return {"host": os.environ.get("COMPUTERNAME", "host"),
                "workers": self.workers, "busy": self.busy,
                "paused": bool(self.paused),
                "pid": os.getpid(),
                "version": VERSION,
                "langs": sorted(self.judge.available_langs()),
                "stats": {"judged": self.stats["judged"], "ac": self.stats["ac"]},
                "queue": len(self.local_queue)}

    # ------------------------------------------------------------- worker
    def worker_loop(self):
        while not self.stop_flag.is_set():
            if self.paused:
                self.stop_flag.wait(1.0)
                continue
            item = self.pop_local(timeout=2.0)
            if item is None:
                continue
            sid = str(item.get("sid") or "")
            try:
                if sid:
                    # 队列条目里的 candidate 标记直接透传给判题流程
                    self.try_process(sid, candidate=bool(item.get("candidate")))
            except TwdbError as e:
                self.log("WARN", "判题云端调用失败 sid=%s: %s" % (sid, e))
            except Exception as e:  # noqa: BLE001
                self.log("ERROR", "worker 异常 sid=%s: %r" % (sid, e))
                self.log("DEBUG", traceback.format_exc())
            finally:
                with self.queue_cond:
                    self.queued_sids.discard(sid)

    def try_process(self, sid, candidate=False):
        """领取租约并判一个提交；返回 True 表示真的判了。"""
        sub = self.store.get_sub(sid)
        if not sub:
            self.store.dequeue(sid)      # 脏队列条目
            return False
        candidate = bool(candidate or sub.get("rejudge"))
        status = sub.get("status")
        if status == STATUS_DONE and not candidate:
            self.store.dequeue(sid)
            self.mark_seen(sid)
            return False
        if candidate and sub.get("candidate_status") in ("applied", "cancelled", "done", "error"):
            self.store.dequeue(sid)       # 候选已终结，别在队列里空转
            return False
        if status == STATUS_JUDGING:
            until = int(sub.get("lease_until") or 0)
            if until > now_ts() and sub.get("judge") != self.store.judge_id:
                return False              # 别的判题机租约还有效
        token = self.store.acquire_lease(
            sid, assume_free=(status != STATUS_JUDGING), candidate=candidate)
        if not token:
            return False                  # 领取失败，让下一轮重来
        try:
            self.do_judge(sid, token, sub, candidate=candidate)
            return True
        finally:
            self.store.release_lease(sid, token)

    def do_judge(self, sid, token, sub=None, candidate=False):
        with self.busy_lock:
            self.busy += 1
        try:
            sub = sub or self.store.get_sub(sid)
            if not sub:
                return
            code, env, err = self.store.take_submission_code(sid, self.keypair)
            if err:
                self.log("WARN", "提交 %s 取码失败：%s" % (sid, err))
                self.store.fail_submission(sid, "取码失败: %s" % err, "JE",
                                           token=token, retry=False, candidate=candidate)
                self.stats["failed"] += 1
                return
            if env:
                self.log("DEBUG", "sid=%s 密文已解密（%d 段，指纹 %s），云端代码标记为判题中"
                         % (sid, env.get("n"), env.get("to")))
            client_pubkey = sub.get("client_pubkey") or None
            pid = sub.get("pid") or ""
            rev = sub.get("prob_rev") or ""
            problem, tests = self.store.get_problem_for_rev(pid, rev)
            candidate = bool(sub.get("rejudge"))
            self.log("INFO", "开始判题 sid=%s user=%s pid=%s lang=%s len=%dB rev=%s attempt=%s%s"
                     % (sid, sub.get("user"), pid, sub.get("lang"), len(code), rev or "-",
                        sub.get("attempt"), " [候选重判]" if candidate else ""))
            if not problem:
                self.store.fail_submission(sid, "题目 %s 不存在" % pid, "SKIP",
                                           token=token, retry=False, candidate=candidate)
                self.stats["failed"] += 1
                return
            workdir = os.path.join(self.cfg.path("work"), str(sid))
            t0 = time.time()
            try:
                (verdict, score, cases, clog, ms, kb, msg, checker) = self.judge.judge_submission(
                    sub, code, problem, tests, workdir)
            except Exception as e:  # noqa: BLE001
                self.log("ERROR", "判题内部异常 sid=%s: %r" % (sid, e))
                self.log("DEBUG", traceback.format_exc())
                self.store.fail_submission(sid, "判题机内部错误: %r" % e, "JE",
                                           token=token, candidate=candidate)
                self.stats["retried"] += 1
                return

            if verdict == "JE":
                # 判题机侧故障：按 attempt 有限重试（对齐 MiniJudge MAX_ATTEMPTS）
                res = self.store.fail_submission(sid, msg or "判题机故障", "JE",
                                                 token=token, candidate=candidate)
                self.stats["retried"] += 1
                self.log("WARN", "提交 %s JE：%s" % (sid, (res or {}).get("msg", msg)))
                return

            res = self.store.finish(sid, verdict, score, cases, clog, ms, kb, msg, checker,
                                    token=token, candidate=candidate,
                                    client_pubkey=client_pubkey, source=code)
            if res is None:
                self.log("WARN", "提交 %s 结果因租约失效被丢弃" % sid)
                return
            self.mark_seen(sid)
            self.stats["judged"] += 1
            if verdict == "AC":
                self.stats["ac"] += 1
            elif verdict == "CE":
                self.stats["ce"] += 1
            self.log("INFO", "判题完成 sid=%s verdict=%s score=%d %dms/%dKB 用时%.1fs"
                     % (sid, verdict, score, ms, kb, time.time() - t0))
        finally:
            with self.busy_lock:
                self.busy -= 1

    # ------------------------------------------------------------ 命令总线
    def drain_cmds(self):
        if not self.args.enable_cmd:
            return
        try:
            cmds = self.store.list_pending_cmds(limit=20)
        except TwdbError as e:
            self.log("WARN", "命令总线读取失败: %s" % e)
            return
        for c in cmds:
            if self.stop_flag.is_set():
                return
            try:
                self.handle_cmd(c)
                self.stats["cmds"] += 1
            except Exception as e:  # noqa: BLE001
                self.log("ERROR", "命令 %s 处理失败: %r" % (c.get("cid"), e))
                self.log("DEBUG", traceback.format_exc())
                try:
                    self.store.reply(c.get("cid"), False, {}, "服务端错误: %r" % e)
                except TwdbError:
                    pass

    def _auth(self, c):
        """返回 (user_dict 或 None, token)。"""
        sess = self.store.get_session(c.get("token"))
        if sess:
            return self.store.get_user(sess.get("user")), c.get("token")
        return None, None

    def handle_cmd(self, c):
        op = str(c.get("op") or "").lower()
        args = c.get("args") or {}
        cid = c.get("cid")
        user, token = self._auth(c)
        self.log("DEBUG", "cmd %s op=%s user=%s" % (cid, op, (user or {}).get("user")))

        if op == "hello":
            self.store.reply(cid, True, {
                "server": "OJ-OJOJOJ", "version": VERSION,
                "judge_id": self.store.judge_id,
                "langs": sorted(self.judge.available_langs()),
                "problems": self.store.list_problem_ids(),
                "link": self.cfg.getv("api.browse", "")}, "hello")

        elif op == "whoami":
            # 前端刷新后用 token 自检登录态，避免"看着登录了其实早失效"
            if not user:
                self.store.reply(cid, False, {}, "登录已过期，请重新登录")
            else:
                self.store.reply(cid, True, {"user": _public_user(user),
                                             "token": token}, "有效")

        elif op == "register":
            ok, res = self.store.create_user(args.get("user"), args.get("pass"),
                                             args.get("nick"),
                                             is_admin=bool(args.get("admin_key")) and
                                             args.get("admin_key") == self.cfg.getv("auth.admin_key", None))
            if ok:
                tok = self.store.new_session(res["user"])
                self.store.reply(cid, True, {"token": tok, "user": _public_user(res)}, "注册成功")
            else:
                self.store.reply(cid, False, {}, res)

        elif op == "login":
            u, msg = self.store.verify_user(args.get("user"), args.get("pass"))
            if not u:
                self.store.reply(cid, False, {}, msg)
            else:
                tok = self.store.new_session(u["user"])
                self.store.reply(cid, True, {"token": tok, "user": _public_user(u)}, "登录成功")

        elif op == "logout":
            if token:
                self.store.drop_session(token)
            self.store.reply(cid, True, {}, "已退出")

        elif op == "profile":
            if not user:
                self.store.reply(cid, False, {}, "请先登录")
            else:
                self.store.reply(cid, True, {"user": _public_user(user),
                                             "subs": [self._slim(s) for s in
                                                      self.store.submissions_of(user["user"], 20)]}, "")

        elif op == "mysubs":
            target = (args.get("user") or (user or {}).get("user"))
            if not target:
                self.store.reply(cid, False, {}, "请先登录")
            else:
                n = int(args.get("limit", 20))
                self.store.reply(cid, True,
                                 {"subs": [self._slim(s) for s in self.store.submissions_of(target, n)]}, "")

        elif op == "problem_list":
            probs = self.store.list_problems()
            out = [{"pid": p["pid"], "title": p.get("title", ""),
                    "difficulty": p.get("difficulty", ""),
                    "total_score": p.get("total_score", 100),
                    "case_count": p.get("case_count", 0),
                    "time_limit_ms": p.get("time_limit_ms", 1000),
                    "solved": bool(user and p["pid"] in (user.get("solved") or []))}
                   for p in probs]
            self.store.reply(cid, True, {"problems": out, "count": len(out)}, "")

        elif op == "stat":
            users = self.store.list_users()
            rank = self.store.get_json("rank", {}) or self.store.rebuild_rank()
            self.store.reply(cid, True, {
                "problems": len(self.store.list_problem_ids()),
                "users": len(users), "judges": self.store.judges_online(),
                "judged": self.stats["judged"], "top": rank.get("order", [])[:10]}, "")

        elif op == "newid":
            sid = new_sid()
            self.store.reply(cid, True, {"sid": sid}, "")

        elif op == "submit":
            # 便捷通道：一条命令完成提交（代码放在 args.code）
            s_user = (user or {}).get("user") or args.get("user")
            if not s_user:
                self.store.reply(cid, False, {}, "请先登录")
                return
            pid, lang, code = args.get("pid"), args.get("lang", "cpp"), args.get("code", "")
            if not self.store.get_problem(pid):
                self.store.reply(cid, False, {}, "题目不存在: %s" % pid)
                return
            sub = self.store.create_submission(s_user, pid, lang, code)
            self.store.reply(cid, True, {"sid": sub["sid"]}, "已提交")

        elif op == "judge_status":
            self.store.reply(cid, True, {
                "judge": self.store.judge_id, "busy": self.busy,
                "queue": len(self.store.queue_candidates()),
                "langs": sorted(self.judge.available_langs()),
                "stats": self.stats}, "")

        elif op == "rejudge":
            if not (user and user.get("is_admin")):
                self.store.reply(cid, False, {}, "需要管理员")
                return
            sid = str(args.get("sid") or "")
            sub = self.store.get_sub(sid)
            if not sub:
                self.store.reply(cid, False, {}, "提交不存在: %s" % sid)
                return
            if args.get("direct"):
                sub.update({"status": STATUS_PENDING, "verdict": "", "score": 0,
                            "msg": "重测排队中", "lease_token": "", "lease_until": 0})
                self.store.put_sub(sub)
                self.store.enqueue(sid, sub)
                with self.seen_lock:
                    self.seen.pop(sid, None)
                self.store.reply(cid, True, {"sid": sid}, "已直接重新入队")
            else:
                bid = self.store.create_rejudge_batch([sid], by=user.get("user"), note="cmd")
                with self.seen_lock:
                    self.seen.pop(sid, None)
                self.store.reply(cid, True, {"sid": sid, "batch": bid}, "候选重判已排队")

        elif op == "add_ann":
            if not (user and user.get("is_admin")):
                self.store.reply(cid, False, {}, "需要管理员")
                return
            n = self.store.set_ann(args.get("title", ""), args.get("body", ""))
            self.store.reply(cid, True, {"n": n}, "")

        else:
            self.store.reply(cid, False, {}, "未知操作: %s" % op)

    def _slim(self, s):
        return {k: s.get(k) for k in ("sid", "pid", "lang", "status", "verdict",
                                      "score", "time_ms", "memory_kb", "ts", "msg",
                                      "cases_passed", "case_count")}

    # -------------------------------------------------------------- 维护
    def maintenance(self):
        n_stats = self.store.flush_user_stats()
        if n_stats:
            self.log("DEBUG", "落库 %d 个用户的提交统计" % n_stats)
        n_rec = self.store.recover_stale()
        if n_rec:
            self.stats["recovered"] += n_rec
            self.log("INFO", "崩溃恢复：%d 个提交重新入队" % n_rec)
        snap = self.store.rebuild_rank()
        self.log("DEBUG", "排行榜已刷新，%d 人" % snap.get("total", 0))
        try:
            self.store.refresh_problem_cache()
        except TwdbError as e:
            self.log("WARN", "题目缓存刷新失败: %s" % e)
        n_sess = self.store.cleanup_sessions()
        if n_sess:
            self.log("DEBUG", "清理过期会话 %d 个" % n_sess)
        if self.cfg.getv("judge.archive_ttl_h", 24):
            n_arc = self.store.archive()
            if n_arc:
                self.stats["archived"] += n_arc
                self.log("INFO", "归档 %d 条旧提交（保持热命名空间有界）" % n_arc)
        self.store.write_meta()
        self._save_seen()
        # 清理超过 7 天的本地工作目录
        self._gc_workdirs()

    def _gc_workdirs(self, max_age_h=168):
        """删掉本地 work/<sid> 临时目录，只保留最近 max_age_h 小时。"""
        work = self.cfg.path("work")
        cutoff = time.time() - max_age_h * 3600
        removed = 0
        try:
            for name in os.listdir(work):
                p = os.path.join(work, name)
                if not os.path.isdir(p):
                    continue
                try:
                    if os.path.getmtime(p) < cutoff:
                        shutil.rmtree(p, ignore_errors=True)
                        removed += 1
                except OSError:
                    pass
        except OSError:
            return 0
        if removed:
            self.log("DEBUG", "清理本地工作目录 %d 个" % removed)
        return removed


def _public_user(u):
    return {k: u.get(k) for k in ("user", "nick", "score", "ac_count",
                                  "submit_count", "solved", "is_admin", "created")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OJ-OJOJOJ 判题机")
    ap.add_argument("--config", default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--once", action="store_true", help="判完当前队列就退出")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--no-cmd", dest="enable_cmd", action="store_false",
                    help="不处理命令总线（只判题）")
    ap.add_argument("--maint-now", action="store_true", help="启动后立刻跑一次维护")
    ap.add_argument("--allow-multi", action="store_true",
                    help="允许同机多实例（必须给每个实例不同的 judge.id）")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    help="覆盖配置，如 --set judge.workers=8")
    args = ap.parse_args(argv)
    cfg = ojconfig.load(args.config, args.overrides)
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    daemon = JudgeDaemon(cfg, args)
    return daemon.start()


if __name__ == "__main__":
    sys.exit(main())

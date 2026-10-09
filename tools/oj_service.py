# -*- coding: utf-8 -*-
"""判题后端的一键开关（把中控台的进程管理抽成命令行）。

    python tools/oj_service.py status      # 看状态（进程/心跳/集群/队列）
    python tools/oj_service.py start       # 启动判题机（后台常驻，无窗口）
    python tools/oj_service.py stop        # 优雅停止（超时自动强杀）
    python tools/oj_service.py restart
    python tools/oj_service.py toggle      # 在跑就停，没跑就起 —— 真·一键开关
    python tools/oj_service.py shortcut    # 在桌面创建"判题机开关"快捷方式
    python tools/oj_service.py install     # 开机自启（放启动文件夹）
    python tools/oj_service.py uninstall   # 取消开机自启
    python tools/oj_service.py watch       # 守护：挂了自动拉起（Ctrl+C 退出）

常用组合：
    status 会同时给出：本机判题机是否在跑、云端是否可达、在线判题机台数、待判队列深度。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import config as ojconfig                     # noqa: E402
from console import JudgeProcess              # noqa: E402

SHORTCUT_NAME = "OJ 判题机开关.lnk"
STARTUP_NAME = "OJ判题机.cmd"


def load_cfg():
    cfg = ojconfig.load()
    if not cfg.getv("paths.python"):
        cfg.setv("paths.python", sys.executable)
    return cfg


def cloud_view(cfg, timeout_note=True):
    """云端视角：连通性 / 集群 / 队列深度。任何失败都不抛，只降级显示。"""
    out = {"ok": False, "error": "", "cluster": None, "queue": None}
    try:
        from store import Store
        from twdb import TinyWebDB
        db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
                       min_interval_s=0.2, retries=2)
        ping = db.ping()
        out["ok"] = bool(ping.get("ok"))
        out["tags"] = ping.get("count")
        st = Store(db, cfg)
        out["cluster"] = st.cluster_summary()
        try:
            out["queue"] = len(st.queue_candidates())
        except Exception:  # noqa: BLE001
            out["queue"] = None
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:140]
    return out


def cmd_status(cfg, proc):
    st = proc.info()
    print("=" * 68)
    print(" 判题机进程")
    print("=" * 68)
    if st.get("running"):
        up = ""
        if st.get("boot_ts"):
            up = "，已运行 %d 秒" % max(0, int(time.time() - float(st["boot_ts"])))
        print("  ● 运行中  pid=%s  judge.id=%s%s" % (st["pid"], st.get("judge_id") or "?", up))
        print("    启动时间: %s" % st.get("started") or "-")
    else:
        print("  ○ 未运行（启动：oj_service.py start 或双击桌面开关）")

    print()
    v = cloud_view(cfg)
    if not v["ok"]:
        print("  云端: [X] 不可达 %s" % (v.get("error") or ""))
        return 1
    print("  云端: [OK] 可达（共 %s 个标签）" % v.get("tags"))
    cl = v.get("cluster") or {}
    rows = cl.get("rows") or []
    print()
    print("=" * 68)
    print(" 多机共判集群（在线 %d 台，总并发 %d，空闲 %d）"
          % (cl.get("judges", 0), cl.get("workers", 0), cl.get("free", 0)))
    print("=" * 68)
    if not rows:
        print("  （没有心跳：判题机没启动，或都刚下线）")
    for r in rows:
        share = r.get("share")
        print("  %-16s free=%d/%d cpu=%d%% share=%-6s mode=%-7s judged=%-5d %ds前"
              % (r["id"], r["free"], r["workers"], r["load_pct"],
                 "-" if share is None else round(share * 100) / 100.0,
                 r.get("share_mode") or "-", r["judged"], r["age_s"]))
    if v.get("queue") is not None:
        print("\n  待判队列: %d 个" % v["queue"])
    return 0


def cmd_shortcut(cfg, proc):
    """在桌面建一个 .lnk，双击即执行 toggle（模板见 tools/oj_toggle.cmd）。"""
    target = os.path.join(ROOT, "tools", "oj_service.cmd")
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "桌面")
    lnk = os.path.join(desktop, SHORTCUT_NAME)
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        "$s = $w.CreateShortcut('%s'); "
        "$s.TargetPath = '%s'; "
        "$s.Arguments = 'toggle'; "
        "$s.WorkingDirectory = '%s'; "
        "$s.Description = 'OJ 判题机：一键启动/停止'; "
        "$s.IconLocation = '%%SystemRoot%%\\System32\\shell32.dll,137'; "
        "$s.Save()" % (lnk, target, ROOT)
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    if os.path.isfile(lnk):
        print("  [OK] 已创建桌面快捷方式: %s" % lnk)
        print("    双击即「一键启动/停止」（在跑就停，没跑就起）")
        return 0
    print("  [X] 创建失败: %s %s" % (r.stdout.strip(), r.stderr.strip()))
    return 1


def cmd_install(cfg, proc):
    startup = os.path.join(os.environ.get("APPDATA", ""),
                           "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    if not os.path.isdir(startup):
        print("  [X] 找不到启动文件夹: %s" % startup)
        return 1
    path = os.path.join(startup, STARTUP_NAME)
    py = sys.executable
    body = "@echo off\r\nrem OJ 判题机开机自启（删除本文件即取消）\r\n" \
           'start "" /min "%s" "%s" start\r\n' % (py, os.path.join(ROOT, "tools", "oj_service.py"))
    with open(path, "w", encoding="gbk", errors="replace") as f:
        f.write(body)
    print("  [OK] 已安装开机自启: %s" % path)
    print("    登录后会自动启动判题机（后台常驻，无窗口）。取消：oj_service.py uninstall")
    return 0


def cmd_uninstall(cfg, proc):
    startup = os.path.join(os.environ.get("APPDATA", ""),
                           "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    path = os.path.join(startup, STARTUP_NAME)
    if os.path.isfile(path):
        os.remove(path)
        print("  [OK] 已移除开机自启: %s" % path)
    else:
        print("  （本来就没装）")
    return 0


def cmd_watch(cfg, proc, interval=20):
    """守护模式：判题机挂了就自动拉起（适合放在常驻窗口里）。"""
    print("守护模式：每 %ds 检查一次，判题机掉线自动拉起（Ctrl+C 退出）" % interval)
    while True:
        try:
            st = proc.info()
            if not st.get("running"):
                ok, msg = proc.start(verbose=False)
                print("[%s] 拉起判题机: %s" % (time.strftime("%H:%M:%S"), msg))
            else:
                print("[%s] 运行中 pid=%s" % (time.strftime("%H:%M:%S"), st["pid"]))
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n已退出守护（判题机保持运行）")
            return 0


def main():
    ap = argparse.ArgumentParser(description="判题后端一键开关")
    ap.add_argument("action", choices=["status", "start", "stop", "restart", "toggle",
                                       "shortcut", "install", "uninstall", "watch"])
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()

    cfg = load_cfg()
    proc = JudgeProcess(cfg, logger=lambda m: print("  " + str(m)))

    if a.action == "status":
        return cmd_status(cfg, proc)

    if a.action == "start":
        st = proc.info()
        if st.get("running"):
            print("  已经是运行状态（pid=%s），无需重复启动" % st["pid"])
            return 0
        ok, msg = proc.start(workers=a.workers, verbose=False)
        print("  %s" % msg)
        if not ok:
            return 1
        # 拉起后必须确认它真的活着（判题机可能启动即崩，比如配置/代码问题）
        time.sleep(6)
        st2 = proc.info()
        if not st2.get("running"):
            print("\n  [!] 进程已退出，最近日志：")
            logf = os.path.join(cfg.path("logs"), "daemon.out.log")
            try:
                with open(logf, "r", encoding="utf-8", errors="replace") as f:
                    for line in f.read().strip().splitlines()[-15:]:
                        print("      " + line)
            except OSError:
                print("      （读不到日志 %s）" % logf)
            return 1
        print("\n  [OK] 已在后台常驻（pid=%s）" % st2["pid"])
        return cmd_status(cfg, proc)

    if a.action == "stop":
        ok, msg = proc.stop()
        print("  %s" % msg)
        return 0 if ok else 1

    if a.action == "restart":
        ok, msg = proc.restart(workers=a.workers, verbose=False)
        print("  %s" % msg)
        time.sleep(1)
        return cmd_status(cfg, proc) if ok else 1

    if a.action == "toggle":
        st = proc.info()
        if st.get("running"):
            print("  当前在运行 → 停止")
            ok, msg = proc.stop()
            print("  %s" % msg)
            return 0 if ok else 1
        print("  当前未运行 → 启动")
        ok, msg = proc.start(workers=a.workers, verbose=False)
        print("  %s" % msg)
        return 0 if ok else 1

    if a.action == "shortcut":
        return cmd_shortcut(cfg, proc)
    if a.action == "install":
        return cmd_install(cfg, proc)
    if a.action == "uninstall":
        return cmd_uninstall(cfg, proc)
    if a.action == "watch":
        return cmd_watch(cfg, proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

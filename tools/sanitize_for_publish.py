# -*- coding: utf-8 -*-
"""发布前脱敏：把真实凭据从待入库文件里挪走。

  1) config/oj_config.json  ->  去掉 user/secret/admin_key/本地路径，改为占位符
  2) 同时生成 config/oj_config.local.json（不入库，保留本机可用）
  3) 文档与脚本里出现的真实 user/secret/实例号 -> 占位符
运行后请用 `git grep <secret>` 复核（应该一个字都搜不到）。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "oj_config.json")
LOCAL = os.path.join(ROOT, "config", "oj_config.local.json")
BROWSE_KEY = "api.browse"


def main():
    with open(CFG, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    user = cfg.get("api", {}).get("user", "")
    secret = cfg.get("api", {}).get("secret", "")
    admin_key = cfg.get("auth", {}).get("admin_key", "")
    browse = cfg.get("api", {}).get("browse", "")
    instance = ""
    m = re.search(r"/webdb-([A-Za-z0-9_-]+)", browse or "")
    if m:
        instance = m.group(1)
    print("检测到真实凭据: user=%r secret=%r instance=%r admin_key=%s"
          % (user, secret, instance, "有" if admin_key else "无"))

    # ---- 1) 本机私密覆盖文件（不入库）
    local = {
        "_说明": "本机私密配置（不入库）：真实 user/secret/admin_key。可安全地在这里覆盖任何配置项。",
        "api": {"user": user, "secret": secret, "browse": browse},
        "auth": {"admin_key": admin_key},
        "paths": {
            "python": cfg.get("paths", {}).get("python", ""),
            "toolchain_dirs": cfg.get("paths", {}).get("toolchain_dirs", []),
            "root": cfg.get("paths", {}).get("root", ""),
            "data": cfg.get("paths", {}).get("data", ""),
            "problems": cfg.get("paths", {}).get("problems", ""),
            "work": cfg.get("paths", {}).get("work", ""),
            "cache": cfg.get("paths", {}).get("cache", ""),
            "state": cfg.get("paths", {}).get("state", ""),
            "logs": cfg.get("paths", {}).get("logs", ""),
            "tmp": cfg.get("paths", {}).get("tmp", ""),
            "private_key": cfg.get("crypto", {}).get("private_key", ""),
        },
        "crypto": {"private_key": cfg.get("crypto", {}).get("private_key", "")},
    }
    if os.path.isfile(LOCAL):
        print("  %s 已存在，保留不覆盖（如需重置请手动删除）" % LOCAL)
    else:
        with open(LOCAL, "w", encoding="utf-8") as f:
            json.dump(local, f, ensure_ascii=False, indent=2)
        print("  已生成本机私密配置: %s" % LOCAL)

    # ---- 2) 公开配置改为占位符
    cfg["api"]["user"] = "YOUR_USER"
    cfg["api"]["secret"] = "YOUR_SECRET"
    cfg["api"]["browse"] = "https://tinywebdb.appinventor.space/webdb-你的实例编号"
    cfg.setdefault("auth", {})["admin_key"] = ""
    cfg["crypto"]["private_key"] = ""
    cfg["paths"]["python"] = ""
    cfg["paths"]["toolchain_dirs"] = []
    for k in ("root", "data", "problems", "work", "cache", "state", "logs", "tmp"):
        cfg["paths"][k] = ""
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("  已把 %s 改为占位符" % CFG)

    # ---- 3) 源码/文档里的真实凭据替换掉
    targets = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "w64devkit", "git-portable",
                                    "dist", "third_party", "data", "logs")]
        for fn in filenames:
            if fn.endswith((".py", ".js", ".md", ".json", ".sh", ".cmd", ".html")):
                targets.append(os.path.join(dirpath, fn))

    subs = []
    if instance:
        subs.append((instance, "你的实例编号"))
    if secret:
        subs.append((secret, "YOUR_SECRET"))
    if user and user != "YOUR_USER":
        subs.append((user, "YOUR_USER"))

    # 注意：用户名可能正好是项目 slug 的一部分（oj-<user>），
    # 直接全局替换会把标识符也改坏（schema "oj-ojojoj/1.0" 曾被改成 "oj-YOUR_USER/1.0"）。
    # 先把这类 slug 保护起来，替换完再还原。
    slug = "oj-" + user if user else None
    PROTECT = "\x00OJSLUG\x00"

    changed = []
    for path in targets:
        if os.path.abspath(path) in (os.path.abspath(LOCAL),):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new = text
        if slug and slug in new:
            new = new.replace(slug, PROTECT)
        for a, b in subs:
            if a and a in new:
                new = new.replace(a, b)
        if PROTECT in new:
            new = new.replace(PROTECT, slug)
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            changed.append(os.path.relpath(path, ROOT))

    print("\n已脱敏文件 (%d):" % len(changed))
    for c in sorted(changed):
        print("  -", c)


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""模拟"新克隆一台机器"：只有公开配置（无 local 覆盖）时路径是否可用。"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

tmp = os.path.join(ROOT, "data", "tmp", "fresh_config")
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp, exist_ok=True)
shutil.copy(os.path.join(ROOT, "config", "oj_config.json"), os.path.join(tmp, "oj_config.json"))

import config as ojconfig  # noqa: E402

cfg = ojconfig.load(os.path.join(tmp, "oj_config.json"), ensure_dirs=False)
print("local 覆盖文件:", cfg.local_path)
print("paths.root   :", cfg.getv("paths.root"))
for name in ("data", "problems", "work", "cache", "state", "logs", "tmp"):
    p = cfg.getv("paths." + name)
    print("  %-9s %s  %s" % (name, p, "OK" if os.path.isabs(p) else "❌ 不是绝对路径"))
print("paths.python :", cfg.getv("paths.python"))
print("crypto.key   :", cfg.getv("crypto.private_key"))
ok = (cfg.local_path is None
      and all(os.path.isabs(cfg.getv("paths." + n)) for n in
              ("data", "problems", "work", "cache", "state", "logs", "tmp"))
      and cfg.getv("paths.python"))
print("\n" + ("✅ 新克隆也能直接跑（路径自动补全）" if ok else "❌ 路径补全有问题"))
sys.exit(0 if ok else 1)

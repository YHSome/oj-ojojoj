# -*- coding: utf-8 -*-
"""重建 ACM 榜并检查结构（用真实云端数据）。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import config as ojconfig          # noqa: E402
from store import Store            # noqa: E402
from twdb import TinyWebDB         # noqa: E402

cfg = ojconfig.load()
if not cfg.getv("paths.python"):
    cfg.setv("paths.python", sys.executable)
db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
               min_interval_s=cfg.getv("api.min_interval_s", 0.45),
               retries=cfg.getv("api.retries", 5))
store = Store(db, cfg)

snap = store.rebuild_rank()
print("mode         =", snap.get("mode"))
print("contest_start=", snap.get("contest_start"))
print("penalty_min  =", snap.get("penalty_min"))
print("problems     =", snap.get("problems"))
print("users        =", snap.get("total"))
print()
print("%-4s %-12s %-6s %-6s %s" % ("#", "用户", "通过", "罚时", "逐题（pid: 状态）"))
print("-" * 78)
for r in snap.get("order", []):
    cells = r.get("cells") or {}
    cs = "  ".join(
        "%s:%s" % (p, ("AC@%dmin(+%d)" % (c["t"], c["f"])) if c["v"] == "ac" else ("错%d次" % c["f"]))
        for p, c in sorted(cells.items()))
    print("%-4s %-12s %-6s %-6s %s" % (r["rank"], r["user"], r["solved"], r["penalty"], cs))

print()
print("=== 云端 rank 标签（前端读的就是它）===")
raw = store.get_json("rank", None)
print("  存在:", bool(raw), " 字段:", sorted((raw or {}).keys()))
print("  第 1 名:", json.dumps(((raw or {}).get("order") or [{}])[0], ensure_ascii=False)[:220])

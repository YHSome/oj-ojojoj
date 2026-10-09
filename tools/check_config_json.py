# -*- coding: utf-8 -*-
"""校验配置 JSON 合法性 + 打印多机共判相关参数。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name in ("config/oj_config.json", "config/oj_config.local.example.json"):
    p = os.path.join(ROOT, name)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        print("  ✔ %s 合法（%d 个顶层键）" % (name, len(d)))
    except Exception as e:  # noqa: BLE001
        print("  ✘ %s 不合法: %r" % (name, e))
        raise SystemExit(1)

with open(os.path.join(ROOT, "config/oj_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
j = cfg.get("judge", {})
print("\n  多机共判参数：")
for k in ("share_mode", "adapt_rate_limit", "claim_min_prob", "cluster_ttl_s",
          "cluster_cache_s", "lease_seconds", "lease_renew_ratio",
          "heartbeat_interval_s", "queue_refresh_interval_s"):
    print("    judge.%-24s = %s" % (k, j.get(k, "(默认)")))

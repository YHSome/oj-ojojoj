# -*- coding: utf-8 -*-
"""一次性检查官方 Pages 上的 config.js 是否已经随重建生效。"""
import urllib.request

for path in ("assets/config.js", "index.html"):
    u = "https://yhsome.github.io/oj-ojojoj/" + path
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=20) as r:
            b = r.read().decode("utf-8", "replace")
        extra = ""
        if path.endswith("config.js"):
            extra = "  含 user: %s  含 secret: %s" % ("ojojoj" in b, "8dc7ae54" in b)
        print("  %-18s HTTP %s%s" % (path, r.status, extra))
    except Exception as e:  # noqa: BLE001
        print("  %-18s ✘ %s" % (path, str(e)[:60]))

# -*- coding: utf-8 -*-
"""量一下中控台 /api/status 的耗时，并看 cluster 字段返回了什么。"""
import json
import time
import urllib.request

for i in range(3):
    t0 = time.time()
    try:
        req = urllib.request.Request("http://127.0.0.1:8090/api/status",
                                     headers={"X-OJ-Console": "1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
        ms = int((time.time() - t0) * 1000)
        cl = d.get("cluster") or {}
        print("第 %d 次: HTTP 200  耗时 %dms  cluster.judges=%s rows=%s error=%r"
              % (i + 1, ms, cl.get("judges"), len(cl.get("rows") or []), cl.get("error", "")[:60]))
    except Exception as e:  # noqa: BLE001
        print("第 %d 次: 失败 %.1fs %s" % (i + 1, time.time() - t0, str(e)[:80]))

# -*- coding: utf-8 -*-
"""按"带版本号的地址"抓取，确认拿到的是新版（缓存键已变）。"""
import re
import urllib.request

SITES = [("官方 Pages", "https://yhsome.github.io/oj-ojojoj/"),
         ("githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/")]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                timeout=25) as r:
        return r.read().decode("utf-8", "replace")


for name, base in SITES:
    print("=" * 72)
    print(name, base)
    try:
        html = get(base)
        m = re.search(r'app\.js\?v=([^"\']+)', html)
        print("  index.html 里的资源版本号:", m.group(1) if m else "(没有版本号 → 还是旧版 HTML)")
        if not m:
            continue
        v = m.group(1)
        js = get(base + "assets/app.js?v=" + v)
        css = get(base + "assets/style.css?v=" + v)
        print("  app.js  忙碌态/慢速提示 :", ("btn-busy" in js) and ("slowWatcher" in js))
        print("  app.js  阶段文案        :", "正在把请求写入云端" in js)
        print("  app.js  提交按钮忙碌态  :", "加密提交中" in js)
        print("  style.css 转圈+进度条   :", ("oj-spin" in css) and ("progress-bar" in css))
        print("  index.html 进度行/进度条:", ('id="auth-status"' in html) and ('id="auth-progress"' in html))
        ok = ("btn-busy" in js and "slowWatcher" in js and "oj-spin" in css
              and 'id="auth-status"' in html)
        print("  => 该站点已是最新版:", "是" if ok else "否（可能还在重建/缓存）")
    except Exception as e:  # noqa: BLE001
        print("  失败:", str(e)[:90])

# -*- coding: utf-8 -*-
"""确认两个公网站点已经提供带反馈的新版前端。"""
import urllib.request

SITES = [("官方 Pages", "https://yhsome.github.io/oj-ojojoj/"),
         ("githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/")]

for name, base in SITES:
    print("=" * 70)
    print(name, base)
    try:
        with urllib.request.urlopen(urllib.request.Request(base, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            html = r.read().decode("utf-8", "replace")
        with urllib.request.urlopen(urllib.request.Request(base + "assets/app.js",
                                                           headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            js = r.read().decode("utf-8", "replace")
        with urllib.request.urlopen(urllib.request.Request(base + "assets/style.css",
                                                           headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            css = r.read().decode("utf-8", "replace")
        print("  index.html 有进度行   :", 'id="auth-status"' in html)
        print("  index.html 有进度条   :", 'id="auth-progress"' in html)
        print("  app.js   有忙碌态     :", "btn-busy" in js and "slowWatcher" in js)
        print("  app.js   有阶段文案   :", "正在把请求写入云端" in js)
        print("  style.css 有转圈动画  :", "oj-spin" in css and "progress-bar" in css)
    except Exception as e:  # noqa: BLE001
        print("  失败:", str(e)[:80])

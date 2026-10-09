# -*- coding: utf-8 -*-
"""用带随机查询串的地址绕过 CDN 对 index.html 的缓存，确认源站内容已经是新版。"""
import random
import re
import urllib.request

SITES = [("官方 Pages", "https://yhsome.github.io/oj-ojojoj/"),
         ("githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/index.html")]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                                    "Cache-Control": "no-cache"}),
                                timeout=25) as r:
        return r.read().decode("utf-8", "replace")


for name, base in SITES:
    sep = "&" if "?" in base else "?"
    url = base + sep + "nocache=" + str(random.randint(10 ** 6, 10 ** 7))
    print("=" * 72)
    print(name)
    print("  ", url)
    try:
        html = get(url)
        m = re.search(r'app\.js\?v=([^"\']+)', html)
        print("   资源版本号:", m.group(1) if m else "(没有 → 源站内容还是旧的)")
        print("   有进度行  :", 'id="auth-status"' in html)
        if m:
            js = get(url.rsplit("/", 1)[0] + "/assets/app.js?v=" + m.group(1))
            css = get(url.rsplit("/", 1)[0] + "/assets/style.css?v=" + m.group(1))
            print("   app.js    :", "btn-busy" in js and "slowWatcher" in js)
            print("   style.css :", "oj-spin" in css)
    except Exception as e:  # noqa: BLE001
        print("    失败:", str(e)[:80])

# -*- coding: utf-8 -*-
"""验证 raw.githack.com 能否当"免设置 Pages"用：HTML/CSS/JS 的 MIME 都要对。"""
import urllib.request

BASE = "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/"
FILES = ["index.html", "assets/style.css", "assets/app.js", "assets/crypto.js",
         "assets/tinywebdb.js", "", "../frontend/"]

print("=" * 78)
print("raw.githack.com（把仓库文件按正确 MIME 提供，无需任何设置）")
print("=" * 78)
ok_all = True
for f in FILES:
    url = BASE + f
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            body = r.read(500).decode("utf-8", "replace")
            ct = (r.headers.get("Content-Type") or "").split(";")[0]
            good = ct in ("text/html", "text/css", "application/javascript", "text/javascript")
            if f:
                ok_all = ok_all and (r.status == 200 and good)
            print("  %-26s HTTP %-4s %-26s %s" % (f or "(目录)", r.status, ct, "✔" if good else "✘"))
    except Exception as e:  # noqa: BLE001
        if f:
            ok_all = False
        print("  %-26s ✘ %s" % (f or "(目录)", str(e)[:50]))

print()
print("可用入口:")
print("  " + BASE + "index.html")
print()
print("资源 MIME 全部正确: %s" % ("✔ 是" if ok_all else "✘ 否"))

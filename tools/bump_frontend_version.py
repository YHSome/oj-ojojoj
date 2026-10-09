# -*- coding: utf-8 -*-
"""给 index.html 里的静态资源加上版本号，破 CDN/浏览器缓存。

    python tools/bump_frontend_version.py            # 用 git 短 SHA 当版本号
    python tools/bump_frontend_version.py v20261009  # 指定版本号

为什么需要：GitHub Pages 与 raw.githack 都会缓存 assets/*.js|css（几分钟到十几分钟），
改了前端但地址不变时，访问者拿到的还是旧文件。把 ?v=<版本> 写进地址即可立即生效。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "frontend", "index.html")
ASSETS = ("style.css", "config.js", "crypto.js", "tinywebdb.js", "app.js")


def git_version():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=15)
        sha = out.stdout.strip()
        return sha or "dev"
    except Exception:  # noqa: BLE001
        return "dev"


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else git_version()
    with open(INDEX, "r", encoding="utf-8") as f:
        html = f.read()
    before = html
    n = 0
    for a in ASSETS:
        # 匹配 assets/xxx.js 或 assets/xxx.js?v=xxx（含重新写入）
        pat = re.compile(r'(assets/%s)(\?v=[^"\']*)?' % re.escape(a))
        html, k = pat.subn(lambda m: "%s?v=%s" % (m.group(1), ver), html)
        n += k
    if html == before:
        print("没有任何改动（版本号已是 %s）" % ver)
    else:
        with open(INDEX, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        print("已更新 %d 处资源地址为 ?v=%s" % (n, ver))
    for line in html.splitlines():
        if "assets/" in line and ("<script" in line or "<link" in line):
            print("   ", line.strip())


if __name__ == "__main__":
    main()

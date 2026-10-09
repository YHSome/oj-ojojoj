# -*- coding: utf-8 -*-
"""确认 githack 的短地址（目录形式）是否直接渲染应用，并给出 Pages 收尾命令。"""
import urllib.request

URLS = [
    ("短地址(目录)", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/"),
    ("带 index.html", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/index.html"),
]
print("=" * 74)
for name, u in URLS:
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            body = r.read(6000).decode("utf-8", "replace")
        is_app = ("btn-save-creds" in body) or ("crypto.js" in body)
        print("  %-14s HTTP %s  直接是应用: %s" % (name, r.status, is_app))
        print("                 %s" % u)
    except Exception as e:  # noqa: BLE001
        print("  %-14s ✘ %s" % (name, str(e)[:60]))

print()
print("=" * 74)
print("收尾方式（二选一，都需要能访问 github.com 的设备，比如手机热点）")
print("=" * 74)
print("""
A) 分支部署（推荐，不用 Actions、不涉及 environment 保护规则）
   Settings -> Pages -> Source: Deploy from a branch -> Branch: gh-pages / (root) -> Save
   然后：https://yhsome.github.io/oj-ojojoj/
   更新前端：bash tools/publish_pages.sh

B) 保持 Actions 部署（先修环境白名单）
   Settings -> Environments -> github-pages -> Deployment branches and tags
     -> 选 All branches（或 Add deployment branch rule: main）
   然后再把 workflow 加回来。

也可以一条命令搞定 A（需要 Personal Access Token，勾 repo 或 pages:write）：
   curl -X POST -H "Authorization: Bearer <TOKEN>" \\
        -H "Accept: application/vnd.github+json" \\
        https://api.github.com/repos/YHSome/oj-ojojoj/pages \\
        -d '{"source":{"branch":"gh-pages","path":"/"}}'
""")

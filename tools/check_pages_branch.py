# -*- coding: utf-8 -*-
"""确认 gh-pages 分支内容 + githack 是否已提供新版页面（含「连接设置」）。"""
import subprocess
import urllib.request

print("=== gh-pages 分支内容 ===")
r = subprocess.run(["git", "ls-tree", "-r", "origin/gh-pages", "--name-only"],
                   capture_output=True, text=True, cwd=r"D:\OJ")
for line in (r.stdout or r.stderr).strip().splitlines():
    print("   ", line)

print()
print("=== gh-pages 是否包含新版「连接设置」面版 ===")
r2 = subprocess.run(["git", "show", "origin/gh-pages:index.html"], capture_output=True,
                    text=True, encoding="utf-8", cwd=r"D:\OJ")
has_setup = "连接设置" in (r2.stdout or "")
has_script = 'assets/config.js' in (r2.stdout or "")
print("    含连接设置面板:", has_setup)
print("    含 config.js 引用:", has_script)

print()
print("=== githack 现在提供的版本 ===")
url = "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/index.html"
try:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                timeout=25) as resp:
        body = resp.read().decode("utf-8", "replace")
    print("    HTTP", resp.status, " 含连接设置:", "连接设置" in body,
          " 含连接设置面板:", "btn-save-creds" in body)
except Exception as e:  # noqa: BLE001
    print("    失败:", str(e)[:80])

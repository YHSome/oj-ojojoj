# -*- coding: utf-8 -*-
"""GitHub 网页打不开时，照样把仓库拿下来。

    python tools/get_repo_zip.py                          # 默认拿本仓库
    python tools/get_repo_zip.py --repo YHSome/oj-ojojoj --branch main
    python tools/get_repo_zip.py --extract                # 顺带解压到 dist/

自动在多个通道之间切换（谁通用谁），全部是 HTTPS，不需要 git、不需要网页：
  1. codeload.github.com        官方打包下载端点
  2. ghproxy.net / gh-proxy.com 第三方加速镜像
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHANNELS = [
    ("codeload 官方", "https://codeload.github.com/{repo}/zip/refs/heads/{branch}"),
    ("ghproxy.net", "https://ghproxy.net/https://github.com/{repo}/archive/refs/heads/{branch}.zip"),
    ("gh-proxy.com", "https://gh-proxy.com/https://github.com/{repo}/archive/refs/heads/{branch}.zip"),
]


def download(repo, branch, out, timeout=90):
    for name, tpl in CHANNELS:
        url = tpl.format(repo=repo, branch=branch)
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oj"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] != b"PK":
                print("  [%s] 不是 zip（前 2 字节 %r），换下一个通道" % (name, data[:2]))
                continue
            with open(out, "wb") as f:
                f.write(data)
            print("  [%s] ✔ %.1f KB，用时 %.1fs" % (name, len(data) / 1024.0, time.time() - t0))
            print("       %s" % url)
            return True
        except Exception as e:  # noqa: BLE001
            print("  [%s] ✘ %s" % (name, str(e)[:70]))
    return False


def main():
    ap = argparse.ArgumentParser(description="GitHub 网页打不开时也能下载仓库")
    ap.add_argument("--repo", default="YHSome/oj-ojojoj")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--out", default=None)
    ap.add_argument("--extract", action="store_true", help="解压到 dist/ 下")
    a = ap.parse_args()

    name = a.repo.split("/")[-1]
    out = a.out or os.path.join(ROOT, "dist", "%s-%s.zip" % (name, a.branch))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    print("下载 %s@%s" % (a.repo, a.branch))
    if not download(a.repo, a.branch, out):
        print("\n所有通道都失败：可能整个 GitHub 都被阻断了，请换网络（手机热点/VPN）")
        return 1

    print("\n已保存: %s (%.1f KB)" % (out, os.path.getsize(out) / 1024.0))
    if a.extract:
        dest = os.path.join(os.path.dirname(out), "%s-%s" % (name, a.branch))
        with zipfile.ZipFile(out) as z:
            z.extractall(dest)
        top = os.listdir(dest)
        inner = os.path.join(dest, top[0]) if len(top) == 1 else dest
        n = sum(len(f) for _, _, f in os.walk(inner))
        print("已解压: %s（%d 个文件）" % (inner, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())

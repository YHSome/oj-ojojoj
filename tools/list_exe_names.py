# -*- coding: utf-8 -*-
"""列出仓库根目录下 OJ 开头的文件名（含真实码点，用来判断有没有被编码搞坏）。"""
import os

ROOT = r"D:\OJ"
for name in sorted(os.listdir(ROOT)):
    if name.startswith("OJ") or name.endswith(".exe"):
        p = os.path.join(ROOT, name)
        if os.path.isfile(p):
            cps = " ".join("U+%04X" % ord(c) for c in name[:16])
            print("%-28s %8d 字节   %s" % (name, os.path.getsize(p), cps))

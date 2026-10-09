# -*- coding: utf-8 -*-
"""当前状态全面体检：hosts 写权限 + GitHub 各端点连通性（含走代理）。"""
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
PING_IPS = ["20.205.243.166", "140.82.113.3", "140.82.112.3", "20.27.177.113"]

print("=" * 72)
print("1) hosts 文件写权限")
print("=" * 72)
try:
    with open(HOSTS, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    print("  读：OK（%d 字节，%d 行）" % (len(txt), txt.count("\n") + 1))
    has = "OJ github hosts fix" in txt
    print("  是否已有本工具段落：%s" % ("是" if has else "否"))
except Exception as e:  # noqa: BLE001
    print("  读失败：%r" % e)
print("  写权限测试（append 后立即关闭，不写入内容）：")
try:
    f = open(HOSTS, "a", encoding="utf-8")
    f.close()
    print("    ✔ 可写！现在可以直接修 hosts")
    WRITABLE = True
except Exception as e:  # noqa: BLE001
    print("    ✘ 仍不可写：%r" % e)
    WRITABLE = False

print()
print("=" * 72)
print("2) DNS 解析现状")
print("=" * 72)
for h in ("github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com"):
    try:
        ips = sorted({i[4][0] for i in socket.getaddrinfo(h, 443, proto=socket.IPPROTO_TCP)})
    except Exception as e:  # noqa: BLE001
        ips = ["失败: %r" % e]
    print("  %-30s %s" % (h, ", ".join(ips)))

print()
print("=" * 72)
print("3) 裸 TCP 443（不握手，只测端口通不通）")
print("=" * 72)
for ip in PING_IPS:
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=8)
        s.close()
        print("  %-18s ✔ %dms" % (ip, int((time.time() - t0) * 1000)))
    except Exception as e:  # noqa: BLE001
        print("  %-18s ✘ %s" % (ip, str(e)[:50]))

print()
print("=" * 72)
print("4) TLS 握手（SNI=github.com，超时放宽到 20s）")
print("=" * 72)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
for ip in PING_IPS:
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=10)
        ss = ctx.wrap_socket(s, server_hostname="github.com")
        ss.close()
        print("  %-18s ✔ 握手成功 %dms" % (ip, int((time.time() - t0) * 1000)))
    except Exception as e:  # noqa: BLE001
        print("  %-18s ✘ %s" % (ip, str(e)[:60]))

print()
print("=" * 72)
print("5) 各端点实际访问")
print("=" * 72)


def probe(url, proxy=None, timeout=15):
    try:
        if proxy:
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            r = op.open(urllib.request.Request(url, headers={"User-Agent": "oj"}), timeout=timeout)
        else:
            r = urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "oj"}), timeout=timeout)
        return "✔ %s" % r.status
    except Exception as e:  # noqa: BLE001
        return "✘ %s" % str(e)[:60]


for url in ["https://api.github.com/repos/YHSome/oj-ojojoj",
            "https://github.com/YHSome/oj-ojojoj",
            "https://codeload.github.com/YHSome/oj-ojojoj/tar.gz/refs/heads/main",
            "https://gh-proxy.com/https://github.com/YHSome/oj-ojojoj"]:
    print("  直连 %-62s %s" % (url[:62], probe(url)))

print()
print("  经本机代理 127.0.0.1:8899：")
print("       %-62s %s" % ("https://github.com/YHSome/oj-ojojoj",
                           probe("https://github.com/YHSome/oj-ojojoj",
                                 proxy="http://127.0.0.1:8899", timeout=25)))

print()
print("=" * 72)
print("6) SSH（推送通道）")
print("=" * 72)
r = subprocess.run(["/usr/bin/ssh" if os.path.exists("/usr/bin/ssh") else "ssh",
                    "-i", r"D:\OJ\data\state\ssh\github_ed25519",
                    "-o", r"UserKnownHostsFile=D:\OJ\data\state\ssh\known_hosts",
                    "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=12", "-T", "git@github.com"],
                   capture_output=True, text=True, timeout=30)
print("  " + (r.stdout or r.stderr).strip()[:120])

print()
print("=" * 72)
print("结论：hosts 可写 = %s" % WRITABLE)
print("=" * 72)

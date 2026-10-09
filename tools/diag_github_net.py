# -*- coding: utf-8 -*-
"""GitHub 访问诊断：DNS 解析 → TCP 连通 → HTTPS → 可用镜像/加速地址。"""
import json
import socket
import ssl
import sys
import time
import urllib.request

HOSTS = ["github.com", "api.github.com", "codeload.github.com",
         "raw.githubusercontent.com", "objects.githubusercontent.com",
         "ssh.github.com", "gist.github.com", "github.io"]


def dns(name):
    try:
        infos = socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({i[4][0] for i in infos})
        return ips
    except Exception as e:  # noqa: BLE001
        return ["解析失败: %r" % e]


def tcp(ip, port=443, timeout=6):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True, int((time.time() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def https(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "oj-diag"})
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(200)
        return True, r.status, int((time.time() - t0) * 1000), body[:60]
    except Exception as e:  # noqa: BLE001
        return False, None, 0, repr(e)[:120]


print("=" * 74)
print(" 1) DNS 解析（本地解析器）")
print("=" * 74)
resolved = {}
for h in HOSTS:
    ips = dns(h)
    resolved[h] = ips
    print("  %-30s %s" % (h, ", ".join(ips)))

print()
print("=" * 74)
print(" 2) TCP 443 连通性（对本地解析出的 IP）")
print("=" * 74)
for h in HOSTS:
    for ip in resolved.get(h, [])[:3]:
        if ":" in ip and not ip.count(".") == 3:
            continue
        ok, info = tcp(ip)
        print("  %-30s %-16s %s" % (h, ip, ("✔ %sms" % info) if ok else ("✘ %s" % info)))

print()
print("=" * 74)
print(" 3) HTTPS 实际访问")
print("=" * 74)
for url in ["https://github.com",
            "https://api.github.com/repos/YHSome/oj-ojojoj",
            "https://raw.githubusercontent.com/YHSome/oj-ojojoj/main/README.md",
            "https://codeload.github.com/YHSome/oj-ojojoj/tar.gz/refs/heads/main"]:
    ok, code, ms, extra = https(url)
    print("  %-62s %s" % (url, ("✔ %s %sms %s" % (code, ms, extra)) if ok else ("✘ " + str(extra))))

print()
print("=" * 74)
print(" 4) GitHub 官方公布的网段（api.github.com/meta，用于核对 DNS 是否被污染）")
print("=" * 74)
ok, code, ms, _ = https("https://api.github.com/meta")
if ok:
    req = urllib.request.Request("https://api.github.com/meta", headers={"User-Agent": "oj-diag"})
    meta = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    print("  git  :", ", ".join(meta.get("git", [])[:6]))
    print("  web  :", ", ".join(meta.get("web", [])[:6]))
    print("  api  :", ", ".join(meta.get("api", [])[:6]))
else:
    print("  取不到 meta")

print()
print("=" * 74)
print(" 5) 备用访问方式（镜像/加速）")
print("=" * 74)
for url in ["https://ghfast.top/https://github.com/YHSome/oj-ojojoj",
            "https://ghproxy.net/https://github.com/YHSome/oj-ojojoj",
            "https://gh-proxy.com/https://github.com/YHSome/oj-ojojoj",
            "https://cdn.jsdelivr.net/gh/YHSome/oj-ojojoj@main/README.md",
            "https://fastly.jsdelivr.net/gh/YHSome/oj-ojojoj@main/README.md",
            "https://raw.gitmirror.com/YHSome/oj-ojojoj/main/README.md"]:
    ok, code, ms, extra = https(url)
    print("  %-62s %s" % (url[:62], ("✔ %s %sms" % (code, ms)) if ok else ("✘ " + str(extra)[:60])))

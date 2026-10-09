# -*- coding: utf-8 -*-
"""在阻断加强的情况下，扫描"可用通道"：
   1) 大范围 IP × SNI=github.com 的 TLS 握手（找没被封的入口）
   2) SSH over 443（ssh.github.com）以及 github.com:22
   3) 对比：codeload / gh-proxy 等仍然可用的通道
"""
import socket
import ssl
import subprocess
import time

# GitHub 官方网段里常见的入口 IP（api.github.com/meta: 140.82.112.0/20 / 20.205.243.0/24 / 192.30.252.0/22）
IPS = []
IPS += ["20.205.243.%d" % i for i in (160, 165, 166, 168)]
IPS += ["140.82.%d.%d" % (a, b) for a in (112, 113) for b in (3, 4)]
IPS += ["192.30.255.%d" % i for i in (3, 4)]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def tls_ok(ip, sni="github.com", tcp_timeout=4, hand_timeout=6):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=tcp_timeout)
    except Exception as e:  # noqa: BLE001
        return False, "TCP✘ %s" % str(e)[:30]
    try:
        s.settimeout(hand_timeout)
        ss = ctx.wrap_socket(s, server_hostname=sni)
        ss.close()
        return True, "%dms" % int((time.time() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass
        return False, "TLS✘ %s" % str(e)[:30]


print("=" * 76)
print("1) IP × SNI=github.com 的 TLS 握手扫描（TCP 通 + TLS 通 = 可用入口）")
print("=" * 76)
good = []
for ip in IPS:
    ok, desc = tls_ok(ip)
    tag = "✔ 可用" if ok else "✘"
    print("  %-18s %-6s %s" % (ip, tag, desc))
    if ok:
        good.append(ip)

print()
print("=" * 76)
print("2) 同一批 IP 改成 SNI=api.github.com（看看是不是按域名封）")
print("=" * 76)
api_good = []
for ip in IPS:
    ok, desc = tls_ok(ip, sni="api.github.com")
    if ok:
        print("  %-18s ✔ %s  ← 该 IP 只是 github.com 这个 SNI 被封" % (ip, desc))
        api_good.append(ip)
print("  api 可用的 IP：%s" % (", ".join(api_good) or "无"))

print()
print("=" * 76)
print("3) SSH 通道")
print("=" * 76)
KEY = r"D:\OJ\data\state\ssh\github_ed25519"
KNOWN = r"D:\OJ\data\state\ssh\known_hosts"


def ssh_test(host, port):
    cmd = ["ssh", "-i", KEY, "-o", "UserKnownHostsFile=" + KNOWN, "-o", "IdentitiesOnly=yes",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=12",
           "-p", str(port), "-T", "git@" + host]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        out = (r.stdout + r.stderr).strip().splitlines()
        return out[0] if out else "(无输出)"
    except Exception as e:  # noqa: BLE001
        return "异常: %r" % e


for host, port in (("github.com", 22), ("ssh.github.com", 443), ("ssh.github.com", 22)):
    print("  %-18s:%-4d %s" % (host, port, ssh_test(host, port)[:90]))

print()
print("=" * 76)
print("4) 仍然可用的替代通道")
print("=" * 76)
import urllib.request  # noqa: E402


def http(url, timeout=20):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oj"}),
                                   timeout=timeout)
        return "✔ %s" % r.status
    except Exception as e:  # noqa: BLE001
        return "✘ %s" % str(e)[:50]


for u in ("https://codeload.github.com/YHSome/oj-ojojoj/tar.gz/refs/heads/main",
          "https://gh-proxy.com/https://github.com/YHSome/oj-ojojoj",
          "https://gh-proxy.com/https://raw.githubusercontent.com/YHSome/oj-ojojoj/main/README.md",
          "https://ghproxy.net/https://github.com/YHSome/oj-ojojoj/archive/refs/heads/main.zip"):
    print("  %-70s %s" % (u[:70], http(u)))

print()
print("=" * 76)
print("结论")
print("=" * 76)
print("  可用的 github.com 入口 IP: %s" % (", ".join(good) if good else "无"))
print("  SSH 情况见上（能认证成功就能继续 push）")

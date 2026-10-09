# -*- coding: utf-8 -*-
"""最终确认：当前能用什么、不能用什么（含镜像是否真的能看仓库页）。"""
import re
import socket
import ssl
import subprocess
import time
import urllib.request

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
IP = "20.205.243.166"


def tls_sni(sni, timeout=8):
    try:
        s = socket.create_connection((IP, 443), timeout=6)
        s.settimeout(timeout)
        ss = ctx.wrap_socket(s, server_hostname=sni)
        ss.close()
        return True
    except Exception as e:  # noqa: BLE001
        return "✘ %s" % str(e)[:40]


print("=" * 76)
print("1) 按 SNI 逐个试（同一 IP %s）" % IP)
print("=" * 76)
for sni in ["github.com", "api.github.com", "codeload.github.com",
            "raw.githubusercontent.com", "objects.githubusercontent.com",
            "github.githubassets.com", "gist.github.com"]:
    r = tls_sni(sni)
    print("  %-34s %s" % (sni, "✔ 通" if r is True else r))

print()
print("=" * 76)
print("2) 镜像能不能真的看到仓库页（检查页面里有没有仓库名）")
print("=" * 76)
for base in ["https://gh-proxy.com/https://github.com",
             "https://ghproxy.net/https://github.com"]:
    url = base + "/YHSome/oj-ojojoj"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(60000).decode("utf-8", "replace")
        title = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
        print("  %-52s HTTP %s" % (url[:52], r.status))
        print("      title   : %s" % (title.group(1).strip()[:70] if title else "(无)"))
        print("      含仓库名: %s" % ("oj-ojojoj" in body))
    except Exception as e:  # noqa: BLE001
        print("  %-52s ✘ %s" % (url[:52], str(e)[:50]))

print()
print("=" * 76)
print("3) 用镜像下载 zip（别人没装 git 也能拿代码）")
print("=" * 76)
for u in ["https://ghproxy.net/https://github.com/YHSome/oj-ojojoj/archive/refs/heads/main.zip",
          "https://codeload.github.com/YHSome/oj-ojojoj/zip/refs/heads/main"]:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(4096)
        print("  %-58s ✔ %s  %d+ 字节  zip签名=%s"
              % (u[:58], r.status, len(head), head[:2] == b"PK"))
    except Exception as e:  # noqa: BLE001
        print("  %-58s ✘ %s" % (u[:58], str(e)[:40]))

print()
print("=" * 76)
print("4) git 推送通道（SSH）")
print("=" * 76)
r = subprocess.run(["ssh", "-i", r"D:\OJ\data\state\ssh\github_ed25519",
                    "-o", r"UserKnownHostsFile=D:\OJ\data\state\ssh\known_hosts",
                    "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=12",
                    "-T", "git@github.com"], capture_output=True, text=True, timeout=30)
print("  github.com:22 -> " + ((r.stdout + r.stderr).strip().splitlines() or ["(空)"])[0][:100])

print()
print("=" * 76)
print("5) HTTPS git（走 github.com 的 443，预期失败）")
print("=" * 76)
try:
    out = subprocess.run(["git", "ls-remote", "https://github.com/YHSome/oj-ojojoj.git", "HEAD"],
                         capture_output=True, text=True, timeout=40)
    print("  " + (out.stdout.strip() or out.stderr.strip().splitlines()[0])[:100])
except Exception as e:  # noqa: BLE001
    print("  ✘ %r" % e)

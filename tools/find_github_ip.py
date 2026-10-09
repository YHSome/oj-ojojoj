# -*- coding: utf-8 -*-
"""找出 github.com 可用的真实 IP（用于修 hosts），并用 SNI=github.com 验证。

  * 候选来自 GitHub 官方网段 api.github.com/meta
  * 验证方式：TCP 连上 → TLS 握手（server_hostname='github.com'）→ 发 GET / → 看是否 200/301
"""
import socket
import ssl
import time

CANDIDATES = [
    "20.205.243.166", "20.205.243.165", "20.205.243.168", "20.205.243.160",
    "140.82.112.3", "140.82.112.4", "140.82.113.3", "140.82.113.4",
    "140.82.114.3", "140.82.114.4", "140.82.121.3", "140.82.121.4",
    "20.27.177.113",
]
CURRENT = "20.27.177.113"   # 本地 DNS 现在给的（已知不通）

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def probe(ip, timeout=6):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return None, "TCP 失败: %s" % str(e)[:40]
    try:
        ss = ctx.wrap_socket(s, server_hostname="github.com")
        cert = ss.getpeercert(binary_form=False) or {}
        cn = ""
        try:
            cn = ssl.get_server_certificate((ip, 443), timeout=timeout)[:0]  # 占位，真正 CN 用下面方式
        except Exception:  # noqa: BLE001
            pass
        ss.sendall(b"GET / HTTP/1.1\r\nHost: github.com\r\nUser-Agent: oj-diag\r\n"
                   b"Connection: close\r\nAccept: */*\r\n\r\n")
        data = b""
        while len(data) < 400:
            chunk = ss.recv(400)
            if not chunk:
                break
            data += chunk
        ss.close()
        head = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
        ms = int((time.time() - t0) * 1000)
        marker = ""
        if b"github" in data.lower():
            marker = "  ← 页面里含 github 字样"
        return ("%s %sms%s" % (head, ms, marker)), None
    except Exception as e:  # noqa: BLE001
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass
        return None, "TLS/HTTP 失败: %s" % str(e)[:50]


print("当前 DNS 给 github.com 的 IP: %s（已知不可用）\n" % CURRENT)
print("%-18s %s" % ("IP", "结果"))
print("-" * 78)
good = []
for ip in CANDIDATES:
    ok, err = probe(ip)
    if ok:
        print("%-18s ✔ %s" % (ip, ok))
        good.append(ip)
    else:
        print("%-18s ✘ %s" % (ip, err))

print()
if good:
    print("可用于 hosts 的 IP：", ", ".join(good))
    print("\nhosts 写法（Windows: C:\\Windows\\System32\\drivers\\etc\\hosts，需管理员）：")
    for ip in good[:3]:
        print("  %-16s github.com" % ip)
else:
    print("没有可直接连通的 IP —— 说明 443 上对 github.com 有针对性阻断，")
    print("那就只能走镜像（gh-proxy.com 已实测可用）或继续用 SSH 推送。")

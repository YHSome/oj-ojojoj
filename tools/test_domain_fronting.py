# -*- coding: utf-8 -*-
"""测试域前置（domain fronting）能否取到 github.com 页面：

  用 SNI=api.github.com 完成 TLS（这个能过），然后在 HTTP 层发 Host: github.com。
  如果 GitHub 的边缘按 Host 路由，就能拿到真正的 github.com 页面 → 可以在本机做只读镜像代理。
"""
import socket
import ssl
import time

IPS = ["20.205.243.166", "20.205.243.168", "140.82.113.3"]
SNIS = ["api.github.com", "codeload.github.com", "objects.githubusercontent.com"]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(ip, sni, host_header, path="/YHSome/oj-ojojoj"):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, 443), timeout=6)
        s.settimeout(12)
        ss = ctx.wrap_socket(s, server_hostname=sni)
    except Exception as e:  # noqa: BLE001
        return "TLS✘ %s" % str(e)[:40]
    try:
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0 oj\r\n"
               "Accept: text/html,*/*\r\nConnection: close\r\n\r\n" % (path, host_header))
        ss.sendall(req.encode())
        data = b""
        t1 = time.time()
        while len(data) < 1024 and time.time() - t1 < 15:
            chunk = ss.recv(1024)
            if not chunk:
                break
            data += chunk
        ss.close()
    except Exception as e:  # noqa: BLE001
        return "HTTP✘ %s" % str(e)[:40]
    head = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
    loc = ""
    for line in data.split(b"\r\n")[:15]:
        if line.lower().startswith(b"location:"):
            loc = " | " + line.decode("latin1", "replace")
    body_marker = ""
    low = data.lower()
    if b"github" in low:
        body_marker = " 页面含 github"
    if b"oj-ojojoj" in low:
        body_marker += " / 含仓库名"
    return "%s %dms%s%s" % (head, int((time.time() - t0) * 1000), loc, body_marker)


print("=" * 78)
print("SNI 能过 + Host 改成 github.com  →  能否拿到 github.com 的内容？")
print("=" * 78)
for sni in SNIS:
    for ip in IPS[:2]:
        r = fetch(ip, sni, "github.com")
        print("  SNI=%-32s IP=%-16s %s" % (sni, ip, r))

print()
print("=" * 78)
print("对照：SNI=api.github.com + Host=api.github.com（正常 API 调用）")
print("=" * 78)
print("  " + fetch(IPS[0], "api.github.com", "api.github.com",
                    "/repos/YHSome/oj-ojojoj"))

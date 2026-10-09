# -*- coding: utf-8 -*-
"""确认域前置拿到的是真正的 github.com 页面（而非错误页），并统计可用性。"""
import re
import socket
import ssl
import time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
IP = "20.205.243.166"


def fetch(host_header, path, sni="api.github.com", limit=20000, timeout=20):
    s = socket.create_connection((IP, 443), timeout=8)
    s.settimeout(timeout)
    ss = ctx.wrap_socket(s, server_hostname=sni)
    ss.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36\r\n"
                "Accept: text/html,application/xhtml+xml,*/*\r\n"
                "Accept-Encoding: identity\r\nConnection: close\r\n\r\n"
                % (path, host_header)).encode())
    data = b""
    t0 = time.time()
    while len(data) < limit and time.time() - t0 < timeout:
        try:
            chunk = ss.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
    ss.close()
    return data


print("=" * 78)
print("1) 域前置取仓库主页")
print("=" * 78)
d = fetch("github.com", "/YHSome/oj-ojojoj")
head = d.split(b"\r\n\r\n", 1)
print("  首行:", head[0].split(b"\r\n")[0].decode("latin1"))
body = head[1] if len(head) > 1 else b""
print("  抓取字节:", len(body))
text = body.decode("utf-8", "replace")
m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
print("  <title>:", (m.group(1).strip()[:100] if m else "(没有 title)"))
print("  含仓库名 oj-ojojoj:", "oj-ojojoj" in text)
print("  含 README 内容片段:", "判题后端" in text or "TinyWebDB" in text)

print()
print("=" * 78)
print("2) 域前置取文件页与 raw 内容")
print("=" * 78)
d2 = fetch("github.com", "/YHSome/oj-ojojoj/blob/main/README.md")
print("  blob 页:", d2.split(b"\r\n")[0].decode("latin1", "replace") if d2 else "(空)")

d3 = fetch("raw.githubusercontent.com", "/YHSome/oj-ojojoj/main/README.md")
first = d3.split(b"\r\n", 1)[0].decode("latin1", "replace") if d3 else "(空)"
print("  raw 文件:", first)
if b"200" in d3[:20]:
    body3 = d3.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in d3 else b""
    print("  内容前 80 字:", body3[:80].decode("utf-8", "replace").replace("\n", " "))

print()
print("=" * 78)
print("3) 顺带测几个资源域名（决定网页镜像能否完整）")
print("=" * 78)
for host, path in (("github.githubassets.com", "/assets/"),
                   ("avatars.githubusercontent.com", "/"),
                   ("api.github.com", "/repos/YHSome/oj-ojojoj")):
    try:
        d = fetch(host, path, sni=("api.github.com" if host != "api.github.com" else "api.github.com"))
        line = d.split(b"\r\n", 1)[0].decode("latin1", "replace") if d else "(空)"
        print("  %-32s %s" % (host, line))
    except Exception as e:  # noqa: BLE001
        print("  %-32s ✘ %r" % (host, str(e)[:50]))

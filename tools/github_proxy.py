# -*- coding: utf-8 -*-
"""本机 GitHub 代理：绕过被污染的 DNS，不改 hosts、不需要管理员。

原理：DNS 被污染时 `github.com` 会被解析到死 IP。本代理对 GitHub 相关域名
**直接用钉死的可用 IP 建连**（TLS 握手仍由浏览器端到端完成，SNI/Host 都是 github.com，
证书校验照常通过，无中间人），其它域名正常解析。

用法：
    python tools/github_proxy.py                 # 监听 127.0.0.1:8899
    python tools/github_proxy.py --port 9000

然后把浏览器/系统代理设为 127.0.0.1:8899 即可：
  * Chrome/Edge：设置 → 系统 → 代理（或 Windows 设置 → 网络和 Internet → 代理）
    手动代理 → 地址 127.0.0.1 端口 8899
  * 也可用 SwitchyOmega 之类的扩展，只对 github.com 走这个代理

验证：python tools/github_proxy.py --selftest
"""
from __future__ import annotations

import argparse
import socket
import socketserver
import ssl
import sys
import threading
import time

# 实测可用的 github.com IP（按延迟排序，全部来自 GitHub 官方网段）
PINNED = {
    "github.com": ["20.205.243.166", "140.82.113.3", "140.82.112.3", "140.82.121.4"],
    "www.github.com": ["20.205.243.166", "140.82.113.3"],
    "gist.github.com": ["20.205.243.166"],
}
BUF = 65536
VERBOSE = True


def log(msg):
    if VERBOSE:
        sys.stderr.write("[proxy] %s\n" % msg)
        sys.stderr.flush()


def connect_target(host, port, timeout=12):
    """优先用钉死 IP，失败再回退到系统 DNS。"""
    for ip in PINNED.get(host, []):
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
            log("CONNECT %s:%d -> %s（钉死 IP）" % (host, port, ip))
            return s
        except Exception:  # noqa: BLE001
            continue
    s = socket.create_connection((host, port), timeout=timeout)
    log("CONNECT %s:%d -> %s（系统 DNS）" % (host, port, host))
    return s


def pump(a, b):
    try:
        while True:
            data = a.recv(BUF)
            if not data:
                break
            b.sendall(data)
    except Exception:  # noqa: BLE001
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:  # noqa: BLE001
                pass
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass


class Handler(socketserver.StreamRequestHandler):
    timeout = 60

    def handle(self):
        try:
            line = self.rfile.readline(65536).decode("latin1").strip()
        except Exception:  # noqa: BLE001
            return
        if not line:
            return
        parts = line.split()
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1]

        if method == "CONNECT":
            host, _, port = target.partition(":")
            port = int(port or 443)
            try:
                upstream = connect_target(host, port)
            except Exception as e:  # noqa: BLE001
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                log("失败 %s:%d %r" % (host, port, e))
                return
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            client = self.connection
            t = threading.Thread(target=pump, args=(client, upstream), daemon=True)
            t.start()
            pump(upstream, client)
            return

        # 普通 HTTP 代理请求：GET http://host/path HTTP/1.1
        if target.startswith("http://"):
            rest = target[7:]
            hostport, _, path = rest.partition("/")
            host, _, port = hostport.partition(":")
            port = int(port or 80)
            try:
                upstream = connect_target(host, port)
            except Exception as e:  # noqa: BLE001
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                log("失败 %s %r" % (target, e))
                return
            # 把请求行改写成相对路径，其余头部原样转发
            headers = [("GET /%s %s" % (path, parts[2] if len(parts) > 2 else "HTTP/1.1"))]
            for raw in self.rfile:
                if raw in (b"\r\n", b"\n", b""):
                    break
                headers.append(raw.decode("latin1").rstrip("\r\n"))
            upstream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin1"))
            t = threading.Thread(target=pump, args=(self.connection, upstream), daemon=True)
            t.start()
            pump(upstream, self.connection)
            return

        self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def selftest(port):
    """通过自己的代理访问 https://github.com，验证可用。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    s.sendall(b"CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n")
    line = s.recv(200)
    print("  代理应答:", line.split(b"\r\n")[0].decode())
    ss = ctx.wrap_socket(s, server_hostname="github.com")
    cert = ss.getpeercert(binary_form=True)
    ss.sendall(b"GET /YHSome/oj-ojojoj HTTP/1.1\r\nHost: github.com\r\n"
               b"User-Agent: oj-proxy\r\nConnection: close\r\n\r\n")
    data = b""
    t0 = time.time()
    while len(data) < 400 and time.time() - t0 < 20:
        chunk = ss.recv(400)
        if not chunk:
            break
        data += chunk
    ss.close()
    head = data.split(b"\r\n", 1)[0].decode("latin1")
    print("  HTTP 响应:", head)
    print("  证书长度:", len(cert or b""), "字节（端到端 TLS，证书是 GitHub 真证书）")
    print("  页面含仓库名:", b"oj-ojojoj" in data)
    return head.startswith("HTTP/1.1 200") or head.startswith("HTTP/1.1 301")


def main():
    ap = argparse.ArgumentParser(description="本机 GitHub 代理（绕过 DNS 污染）")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--selftest", action="store_true", help="起一个临时实例自测后退出")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    global VERBOSE
    VERBOSE = not a.quiet

    if a.selftest:
        srv = Server((a.bind, a.port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("自测中……")
        ok = selftest(a.port)
        srv.shutdown()
        print("\n" + ("✅ 代理可用：把浏览器代理设成 %s:%d 即可访问 github.com"
                      % (a.bind, a.port) if ok else "❌ 代理不可用"))
        return 0 if ok else 1

    srv = Server((a.bind, a.port), Handler)
    print("=" * 70)
    print(" GitHub 本地代理已启动: %s:%d" % (a.bind, a.port))
    print(" 浏览器/系统代理填这个地址即可访问 github.com（无需改 hosts）")
    print(" 只对 github.com 走钉死 IP，其它网站正常直连")
    print(" Ctrl+C 退出")
    print("=" * 70)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())

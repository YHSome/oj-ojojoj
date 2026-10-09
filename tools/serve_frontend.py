# -*- coding: utf-8 -*-
"""前端静态服务器（可选）。

前端是**纯静态** html/js/css，直接双击 `frontend/index.html` 就能用
（TinyWebDB 官方 API 返回 `Access-Control-Allow-Origin: *`，浏览器可直连）。

但如果你想用 `http://127.0.0.1:8000` 这种更像正式站点的地址，用这个脚本：

    python tools/serve_frontend.py            # 默认 127.0.0.1:8000
    python tools/serve_frontend.py --port 9000 --bind 0.0.0.0

它只做一件事：把 `frontend/` 目录当静态站点发出去。**不做任何 API 代理**
（浏览器直接访问云端 API），所以它不参与业务逻辑，随时可以换成 nginx / VSCode Live Server。
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import socketserver
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        # 本地开发别缓存，改完刷新就生效
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s - %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((a.bind, a.port), Handler) as httpd:
        print("前端静态站点已启动: http://%s:%d/  （目录 %s）" % (a.bind, a.port, ROOT))
        print("浏览器打开后即可登录、看题、加密提交；判题机需另外运行 daemon.py")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""验证登录态自检（whoami）：前端刷新后靠它确认 token 是否还有效。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import config as ojconfig
from mock_client import rpc, make_client

USER = "sessiondemo"
PWD = "session1234"


def main():
    cfg = ojconfig.load()
    cfg.setv("paths.python", sys.executable)
    db, store = make_client(cfg)

    rep = rpc(store, "register", {"user": USER, "pass": PWD, "nick": USER})
    print("注册:", rep.get("msg"))
    rep = rpc(store, "login", {"user": USER, "pass": PWD})
    if not rep.get("ok"):
        print("登录失败:", rep.get("msg"))
        return 1
    token = rep["data"]["token"]
    print("登录成功，token =", token[:12] + "…")

    good = rpc(store, "whoami", {}, token=token)
    print("whoami(有效 token) ->", "ok" if good.get("ok") else "失败",
          "user =", (good.get("data") or {}).get("user", {}).get("user"))

    bad = rpc(store, "whoami", {}, token="deadbeef" * 4)
    print("whoami(伪造 token) ->", "ok" if bad.get("ok") else "已拒绝", "|", bad.get("msg"))

    ok = bool(good.get("ok")) and not bad.get("ok")
    print("\n" + ("✅ 登录态自检可用：有效 token 认，无效 token 拒"
                 if ok else "❌ 登录态自检异常"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

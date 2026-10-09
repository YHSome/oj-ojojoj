# -*- coding: utf-8 -*-
"""验证两个公网入口：页面能打开、配置已生效（含云端凭据）、资源齐全。"""
import urllib.request

SITES = [
    ("官方 Pages", "https://yhsome.github.io/oj-ojojoj/"),
    ("githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/"),
]


def fetch(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")


for name, base in SITES:
    print("=" * 74)
    print("%s  %s" % (name, base))
    print("=" * 74)
    try:
        # 1) 首页
        st, body, ct = fetch(base)
        print("  index.html      HTTP %s  %s" % (st, ct.split(";")[0]))
        print("    是应用页面    :", "btn-save-creds" in body or "btn-submit" in body)
        print("    引用了 config :", "assets/config.js" in body)

        # 2) 配置文件（决定"打开即可用"）
        st2, cfg, ct2 = fetch(base + "assets/config.js")
        has_user = "ojojoj" in cfg
        has_secret = "8dc7ae54" in cfg
        print("  assets/config.js HTTP %s" % st2)
        print("    已内置 user   : %s" % has_user)
        print("    已内置 secret : %s" % has_secret)

        # 3) 关键资源
        for f in ("assets/app.js", "assets/crypto.js", "assets/tinywebdb.js", "assets/style.css"):
            st3, b3, ct3 = fetch(base + f)
            print("  %-22s HTTP %s  %s  %d 字节" % (f, st3, ct3.split(";")[0], len(b3)))
        print("  => 打开即用: %s" % ("是" if (has_user and has_secret) else "否（还要手动填）"))
    except Exception as e:  # noqa: BLE001
        print("  失败:", str(e)[:100])

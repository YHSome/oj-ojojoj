# -*- coding: utf-8 -*-
"""核对线上前端已是简化版：只有 3 个标签，且公钥/连接设置等都不见了。"""
import urllib.request

SITES = [("官方 Pages", "https://yhsome.github.io/oj-ojojoj/"),
         ("githack", "https://raw.githack.com/YHSome/oj-ojojoj/main/frontend/")]

REMOVED = ['id="health"', 'id="judgekey"', 'id="btn-refresh-key"', 'id="mine-list"',
           'id="setup-status"', 'id="cfg-user"', 'data-tab="setup"', 'data-tab="about"',
           'data-tab="mine"', 'data-tab="submit"', '加密链路', '连接设置']
KEPT = ['data-tab="login"', 'data-tab="problems"', 'data-tab="rank"',
        'id="btn-login"', 'id="btn-register"', 'id="problem-list"',
        'id="rank-body"', 'id="code"', 'id="btn-submit"']

for name, base in SITES:
    print("=" * 74)
    print(name, base)
    try:
        with urllib.request.urlopen(urllib.request.Request(base, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=25) as r:
            html = r.read().decode("utf-8", "replace")
        print("  保留项:")
        for k in KEPT:
            print("    %-24s %s" % (k, "✔" if k in html else "✘ 缺少"))
        print("  已删除项:")
        bad = [r_ for r_ in REMOVED if r_ in html]
        for r_ in REMOVED:
            print("    %-24s %s" % (r_, "✔ 已移除" if r_ not in html else "✘ 还在"))
        import re
        m = re.search(r'app\.js\?v=([^"\']+)', html)
        print("  资源版本号:", m.group(1) if m else "(无)")
        print("  => %s" % ("已是简化版" if not bad else "还有残留: " + ", ".join(bad)))
    except Exception as e:  # noqa: BLE001
        print("  失败:", str(e)[:90])

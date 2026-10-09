# -*- coding: utf-8 -*-
"""核对线上前端：ACM 记分板 + 提交记录都已在，旧的公钥/连接设置仍不在。"""
import re
import urllib.request

URL = "https://yhsome.github.io/oj-ojojoj/"
KEPT = {'data-tab="mine"': '提交记录标签', 'id="mine-list"': '提交记录列表',
        'id="rank-head"': 'ACM 表头', 'class="table acm"': 'ACM 记分板样式',
        'rank.penalty': '罚时说明', 'id="btn-reload-mine"': '提交记录刷新'}
GONE = ['id="judgekey"', 'id="health"', 'id="setup-status"', 'id="cfg-user"',
        'data-tab="setup"', 'data-tab="about"', '加密链路']

with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}),
                            timeout=25) as r:
    html = r.read().decode("utf-8", "replace")
v = re.search(r'app\.js\?v=([^"\']+)', html)

print("线上页面:", URL)
print("资源版本:", v.group(1) if v else "(无)")
print("\n应当存在：")
for k, name in KEPT.items():
    print("   %-22s %s" % (name, "✔" if k in html else "✘ 缺失"))
print("\n应当已移除：")
for k in GONE:
    print("   %-18s %s" % (k, "✔" if k not in html else "✘ 还在"))

print("\n标签页:", re.findall(r'data-tab="([a-z]+)"', html))

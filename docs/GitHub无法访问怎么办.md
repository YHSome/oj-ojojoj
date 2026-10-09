# GitHub 打不开怎么办（实测排查手册）

> 结论先行：**推送/拉取走 SSH，网页被封也不影响你用 Git。**
> 只有"在浏览器上访问 github.com"这件事会被网络阻断卡住，而它的成因有三种，**对策完全不同**，
> 所以先按本文第一步定位，别急着改 hosts。

---

## 第一步：三层定位

```bash
bash tools/oj.sh ghnet      # = python tools/diag_github_net.py
```

它会把每一层都打出来。判据如下：

| 现象 | 病因 | 对应方案 |
|---|---|---|
| DNS 解析出的 IP **连不上 443**，但换成真实 IP 就能连 | **DNS 污染**（最常见） | ✅ 方案 A：钉死 hosts |
| IP 能连上（TCP 200ms），但 **TLS 握手对 `github.com` 超时，对 `api.github.com` 正常** | **SNI 级阻断** | ❌ hosts 无效 → 方案 C/D |
| 连 TCP 都超时、换 IP 也不行、SSH 也不通 | 整条链路被封 | 方案 D（换网络） |

第三种情况在本机出现过一次完整的实测记录：

```
同一 IP 20.205.243.166：
   SNI=github.com        ✘ The handshake operation timed out
   SNI=api.github.com    ✔ 215ms      ← 同一台机器、同一个 IP，只是域名不同
   SNI=codeload...       ✘ / ✔ 随阻断强度变化
SSH  github.com:22       ✔ Hi YHSome! You've successfully authenticated
```

**为什么第二种情况改 hosts 没用**：hosts 只解决"去哪里"，而 SNI 阻断发生在
"握手时明文的域名"这一层——包已经到 GitHub 的 IP 了，中间设备看到 ClientHello 里的
`github.com` 就把连接掐掉。同理，普通的本地 CONNECT 代理也救不了（它只是转发 TCP，SNI 依旧是 `github.com`）。

---

## 方案 A：钉死 DNS（仅解决"DNS 污染"这一种）

**双击 `tools\fix_hosts_admin.cmd`**（会自动提权；预览 `... dry`；还原 `... revert`）。

它往 `C:\Windows\System32\drivers\etc\hosts` 写：

```
# === OJ github hosts fix (begin) ===
20.205.243.166   github.com
20.205.243.166   www.github.com
# === OJ github hosts fix (end) ===
```

IP 用 `python tools/find_github_ip.py` 现测现取（会做 TCP + TLS(SNI=github.com) + GET / 全流程验证），
别照抄文中的 IP——它会变。

> 本机当前属于"SNI 级阻断"，所以此时跑这个脚本**验证会失败**。等阻断退回 DNS 型时它就有用。

## 方案 B：本机代理（仅解决 DNS 型 + 让你不动系统设置）

```bash
python tools/github_proxy.py     # 127.0.0.1:8899
# 然后双击 tools\browse_github.cmd（Edge 独立配置走代理，不动你日常浏览器）
# 或手动把浏览器代理设为 127.0.0.1:8899
```

原理：对 github.com 用钉死的可用 IP 建连，TLS 由浏览器端到端完成（拿到的是 GitHub 真证书）。
**同样是 DNS 型才有效**，SNI 型无效。

## 方案 C：没网页也能拿代码（实测一直可用）

```bash
python tools/get_repo_zip.py --extract
#   [codeload 官方] ✔ 217.0 KB   ← 实测 0.5 秒
#   已解压: dist/oj-ojojoj-main（97 个文件）
```

脚本会在三个通道间自动切换：`codeload.github.com` → `ghproxy.net` → `gh-proxy.com`。
适合"只想看代码/给别人发一份"的场景。

浏览器里也可以直接开这些地址（只读，别在镜像页面上登录）：

```
https://codeload.github.com/YHSome/oj-ojojoj/zip/refs/heads/main
https://ghproxy.net/https://github.com/YHSome/oj-ojojoj/archive/refs/heads/main.zip
```

## 方案 D：要真正用 github.com 网页（登录、开 issue、设 token）

只能在**网络层**解决，本机软件做不到：

1. **换网络**：手机热点 / 其他运营商线路，最省事且立刻见效；
2. **VPN / 境外代理服务**（本项目不提供，也不内置任何翻墙实现）；
3. 等阻断解除 —— 这类阻断常常是**间歇性**的（本机 30 分钟内就从"完全可用"变成"SNI 阻断"）。

---

## 永远可用的一条：Git 走 SSH

```bash
bash tools/push_github.sh YHSome/oj-ojojoj     # 推送
git pull                                       # 拉取（origin 已配成 SSH）
```

本机实测（网页 HTTPS 全断的情况下）：

```
$ ssh -T git@github.com
Hi YHSome! You've successfully authenticated, but GitHub does not provide shell access.

$ bash tools/push_github.sh YHSome/oj-ojojoj
   09e20d7..xxxxx  main -> main
```

**网页登不上 ≠ 你推不了代码。** 需要看渲染后的页面时，再考虑方案 D。

---

## 附：三种病因的一分钟判定脚本

```bash
python tools/diag_github_net.py        # 三层 + 镜像，一次全测
python tools/scan_github_channels.py   # 多 IP × 多 SNI 扫描，找幸存的入口
python tools/final_github_check.py     # 最终定性：能用什么 / 不能用什么
python tools/get_repo_zip.py --extract # 绕过网页拿代码
```

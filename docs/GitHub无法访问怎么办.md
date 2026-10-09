# GitHub 打不开怎么办（DNS 污染排查与修复）

## 一、先分清是哪一层坏了

```bash
bash tools/oj.sh ghnet          # 等价于 python tools/diag_github_net.py
```

本机实测的**真实案例**（可作为对照）：

| 域名 | 本地 DNS 解析 | TCP 443 | 结论 |
|---|---|---|---|
| `github.com` | `20.27.177.113` | ✘ 超时 | **被污染，网页打不开** |
| `www.github.com` | `20.27.177.113` | ✘ | 同上 |
| `api.github.com` | `20.205.243.168` | ✔ 276ms | 正常 |
| `codeload.github.com` | `20.205.243.165` | ✔ 244ms | 正常 |
| `raw.githubusercontent.com` | `185.199.108.133` | ✔ 236ms | 正常 |
| `ssh.github.com` | `20.205.243.160` | ✔ 231ms | 正常（**推送走这里，一直没问题**） |

关键判据：**`github.com` 的 IP 连不上，但 API/SSH/raw 全正常** —— 这不是"GitHub 挂了"，
而是**只有网页那个域名被解析到了死 IP**。而且污染是**间歇性**的（同一命令隔几分钟可能解析出不同结果），
所以表现为"有时能上有时候不能上"。

用 `python tools/find_github_ip.py` 可以列出**实测可用**的 IP（GitHub 官方网段，逐个做
TCP+TLS(SNI=github.com)+GET / 验证）。本机当前可用：`20.205.243.166`（最快）、`140.82.113.3` 等。

## 二、修复方案（按推荐度排序）

### 方案 A：钉死 DNS（永久生效，推荐）

**双击 `tools\fix_hosts_admin.cmd`** —— 会自动申请管理员权限，往
`C:\Windows\System32\drivers\etc\hosts` 写入：

```
# === OJ github hosts fix (begin) ===
20.205.243.166   github.com
20.205.243.166   www.github.com
# === OJ github hosts fix (end) ===
```

然后自动 `ipconfig /flushdns` 并验证。

* 预览（不写入）：`tools\fix_hosts_admin.cmd dry`
* 还原：`tools\fix_hosts_admin.cmd revert`
* 备份：写入前自动存 `hosts.ojbak`；还原时另存 `hosts.ojbak2`

> 如果这个 IP 后来也被阻断，把脚本里的 `$Ip` 换成 `find_github_ip.py` 输出的新 IP 即可。

### 方案 B：本机代理（不改系统、不要管理员）

```bash
python tools/github_proxy.py            # 监听 127.0.0.1:8899
python tools/github_proxy.py --selftest # 自测（已验证返回 200 + GitHub 真证书）
```

然后任选一种：

* **双击 `tools\browse_github.cmd`** —— 用 Edge 以独立配置目录打开 GitHub，只这个实例走代理，
  完全不动你平时的浏览器设置（推荐，最省事）；
* 手动把浏览器/系统代理设为 `127.0.0.1:8899`（Chrome/Edge：设置 → 系统 → 代理）；
* 命令行也能用：
  ```bash
  git -c http.proxy=http://127.0.0.1:8899 clone https://github.com/YHSome/oj-ojojoj.git
  ```

原理：代理对 `github.com` 直接用**钉死的可用 IP** 建连，TLS 由浏览器端到端完成，
SNI/Host 仍是 `github.com`，所以拿到的是 **GitHub 真证书**，不存在中间人；其它域名照常解析。

### 方案 C：镜像（只想看代码/下代码）

```bash
# 浏览仓库
https://gh-proxy.com/https://github.com/YHSome/oj-ojojoj
# 下载 zip
https://gh-proxy.com/https://github.com/YHSome/oj-ojojoj/archive/refs/heads/main.zip
```

实测：`gh-proxy.com` 可用；`ghfast.top` / `ghproxy.net` 对**网页**返回 403（但下载 release 附件可用）；
`cdn.jsdelivr.net` 本机超时。

## 三、重要：推送从来就没坏

Git 走的是 **SSH（`git@github.com:22`）**，那条路一直正常：

```
$ ssh -T git@github.com
Hi YHSome! You've successfully authenticated...

$ bash tools/push_github.sh YHSome/oj-ojojoj
   04da63b..xxxxx  main -> main
```

也就是说：**即使浏览器打不开 github.com，`git push` / `git pull` 照样能用**。
仓库本身的读写不依赖网页。

## 四、为什么不能由脚本自动改 hosts

DSH 沙箱禁止写工作区外的文件（实测 `hosts` 写入被拒绝 `Permission denied`），
所以做成了**一键脚本**：你双击运行即可（它在沙箱之外、以管理员身份执行）。

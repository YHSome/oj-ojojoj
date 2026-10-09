# OJ-OJOJOJ 判题后端（D:\OJ）

**前后端已分离**：

* **前端** = `frontend/`，**纯静态 HTML + CSS + JS**（无框架 / 无构建 / 无依赖），
  浏览器直连云端 API。代码提交前用 **RSA-OAEP 非对称加密**，结果用提交者公钥加密回传。
* **后端** = 本机判题机（`backend/daemon.py`），**每 3 秒**轮询云端取新提交 → 解密 →
  把云端该段代码改成「判题中」并清除密文 → 编译判题 → 结果经云端回传。
* 中转 = 云端 TinyWebDB（两边都只跟它说话，互不直连）。

```
浏览器(静态前端) ─┐                                  ┌─ 本机判题机(daemon.py)
                 ├──► 云端 TinyWebDB（KV 总线）◄─────┤   3 秒轮询 / 解密 / 判题 / 回写
  加密代码、解密结果 │   标签：prob sub code res q cmd  │
                 └────────────────────────────────────┘
```

* 加密链路与分离设计：[docs/加密与前后端分离.md](docs/加密与前后端分离.md)
* 架构设计与云端实测约束：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* 标签/字段契约：[docs/PROTOCOL.md](docs/PROTOCOL.md)
* 前端说明：[frontend/README.md](frontend/README.md)
* 判题语义对齐 [MiniJudge](https://github.com/Mkrari/MiniJudge)（已克隆到 `third_party/MiniJudge` 供比对）

**当前状态：端到端已实测通过**（AC/WA/CE/TLE/RE/MLE/OLE 判定、任务租约恢复、候选重判、
加密提交→解密→判题→加密结果→验签 全链路）。

---

## 1. 快速开始（Git Bash）

```bash
cd /d/OJ

bash tools/oj.sh selfcheck     # ① 环境自检（API / 编译器 / 沙箱 / 编码 / 加密 / 真判题冒烟）
bash tools/oj.sh keygen        # ② 生成判题机密钥对并发布公钥到云端
bash tools/oj.sh seed          # ③ 把本地题库推到云端
bash tools/oj.sh console       # ④ 打开判题机中控台 → http://127.0.0.1:8090
                               #    在网页上「一键启动」判题机、调参数、看日志
bash tools/oj.sh web           # ⑤ 打开答题前端 → http://127.0.0.1:8000
                               #    （也可以直接双击 frontend/index.html）
```

> 不想用中控台也可以直接 `bash tools/oj.sh daemon` 前台跑判题机。

**不开浏览器也能验证前端代码**（Node 加载同一份前端 JS 跑真实链路）：

```bash
bash tools/oj.sh e2e a-plus-b ac    # 期望 AC 100
bash tools/oj.sh e2e a-plus-b wa    # 期望 WA
bash tools/oj.sh e2e a-plus-b ce    # 期望 CE
bash tools/oj.sh cryptotest         # Python ↔ 浏览器 WebCrypto 加解密互通
bash tools/oj.sh ctl                # 中控台 API 自测
```

---

## 1.1 判题机中控台（一键开关 + 参数调整）

`bash tools/oj.sh console` → <http://127.0.0.1:8090>

| 区域 | 能力 |
|---|---|
| 状态卡 | 运行/停止/已暂停、PID、判题机 ID、启动时间、云端可达性与标签数、待判队列、可用语言 |
| **一键开关** | **启动 / 停止 / 重启**；停止是**优雅停机**（判完手头的提交再退，自动释放租约）；另有暂停接单 / 恢复接单 / 热重载配置 |
| 参数调整 | 28 个可在线修改的参数（轮询间隔、并发数、租约、限制、防限流、加密开关、比较方式…），带类型校验与非法值拦截，保存后点「热重载」立即生效 |
| 运维动作 | 环境自检、生成密钥、查看公钥、播种题库、云端探测、统计、刷榜、清理、归档、备份、提交列表、重判批次、测试账号、加密互通测试 |
| 快速验证 | 选题目+样例，一键明文提交一次看判题是否正常 |
| 日志 | 实时 tail `logs/judge.log` |

**安全**：只监听 `127.0.0.1`；所有 `/api/*` 都要带 `X-OJ-Console: 1` 自定义请求头
（跨站表单无法自带自定义头 → 挡掉 CSRF 式攻击）；可用 `--token xxx` 再加口令。

**控制协议**：中控台不杀进程，而是写本地控制文件 `data/state/ctl.json`
（`stop/pause/resume/reload`），daemon 每 1.5 秒轮询一次并回写 ack，
所以「停止」不会打断正在判的那份提交。


---

## 2. 目录速览

| 路径 | 作用 |
|---|---|
| `frontend/` | **纯静态前端**：`index.html` + `assets/{style.css,crypto.js,tinywebdb.js,app.js}` |
| `console/` | **判题机中控台页面**：一键开关 + 参数调整 + 日志 |
| `tools/console.py` | 中控台后端（本机 HTTP，127.0.0.1，控制文件驱动的启停） |
| `backend/crypto.py` | 纯标准库 RSA：RSA-OAEP(SHA-256) 分块加解密 + PKCS#1 v1.5 签名（与浏览器 WebCrypto 互测通过） |
| `backend/twdb.py` | TinyWebDB REST 客户端（重试 / 限速 / 503 退避 / 软删除容错 / 坏标签兜底） |
| `backend/store.py` | 领域层：题目、提交、用户、排行榜、命令总线、**任务租约**、安全文本层、分片值、密文信封 |
| `backend/runner.py` | 沙箱执行：超时熔断、Job Object 内存限制、**执行期输出监控（真 OLE）**、峰值内存采样 |
| `backend/judge.py` | 编译矩阵 + 比较器（`tokens/exact/float/custom`）+ 逐点独立目录 + 判分 |
| `backend/daemon.py` | 主进程：3 秒轮询、解密取码、worker 池、发布线程、心跳/维护、崩溃恢复、单实例锁 |
| `backend/admin_cli.py` | 运维：keygen/pubkey/seed/import-problem/push/pull/rejudge(候选批次)/rank/archive/backup/restore/adduser/test-users |
| `tools/oj.sh` | Git Bash 快捷入口（推荐） |
| `tools/e2e_frontend.js` | 用**真实前端 JS** 在 Node 里跑加密端到端 |
| `tools/test_crypto_python.py` | Python ↔ 浏览器 WebCrypto 加解密/签名互通测试 |
| `tools/serve_frontend.py` | 前端静态站点服务器（可选） |
| `tools/mock_client.py` | 明文提交的模拟客户端（自测/兼容） |
| `tools/selfcheck.py` | 环境自检（含真编译真判题冒烟 + 编码往返） |
| `tools/probe_*.py` `diag*.py` | 云端约束与环境诊断脚本（研究用，结论已写进文档） |
| `third_party/MiniJudge/` | 上游参考项目（判题语义/题包格式对齐用） |
| `data/problems/<PID>/` | 题库本地副本（兼容 MiniJudge 题包：`problem.json` + `statement.md` + `tests/NN.in|.ans`） |
| `data/state/judge_key.json` | 判题机 RSA 私钥（**泄露等于源码可被解密，注意保管**） |
| `data/work/<SID>/` | 每次提交的编译运行产物（7 天自动清理） |
| `logs/judge.log` | 判题日志 |

---

## 3. 常用运维

```bash
bash tools/oj.sh probe                          # 云端连通性
bash tools/oj.sh stats                          # 题库/用户/语言/API 统计
bash tools/oj.sh client hello                    # 命令总线自检
bash tools/oj.sh client login --user alice --pass 1234
bash tools/oj.sh client submit --user alice --pid P1001 --lang cpp --file /d/OJ/ac.cpp
bash tools/oj.sh inspect --sid 517224342 --code
bash tools/oj.sh rejudge --pid P1001             # 非 AC 的提交全部重测
bash tools/oj.sh rank ; bash tools/oj.sh gc ; bash tools/oj.sh admin archive --ttl-hours 24
bash tools/oj.sh admin adduser --user admin --pass 你的密码 --admin
bash tools/oj.sh admin mkproblem --pid P1003 --title "最大值"
bash tools/oj.sh admin push --pid P1003          # 推题（自动生成内容指纹 rev，判题机缓存自动失效）
```

## 4. 加新题

```bash
bash tools/oj.sh admin mkproblem --pid P1003 --title "最大值"
# 编辑 data/problems/P1003/problem.json 与 tests/01.in、01.out ...
bash tools/oj.sh admin push --pid P1003
```
测试点分数写在 `problem.json` 的 `cases` 里（按文件名对应），未写则平均分。
要特判就把 `checker` 设为 `spj` 并放 `checker.py`（argv = 输入 / 选手输出 / 标准答案，退出 0=AC）。

---

## 5. 判题机行为要点

* **队列**：前端写 `q:<SID>`；判题机每 3 秒扫一次 `q:`（常量级小集合），`sub:` 全表兜底。
* **取码**：加密提交 → 拉密文 → 私钥解密 → 云端 `code:<SID>` 立刻改成「判题中」并删除全部密文分片。
* **认领**：任务租约（`lease_token` + `lease_until` + `attempt`）；写回结果前校验租约，陈旧结果丢弃。
* **崩溃恢复**：启动时先作废自己遗留的租约，再把失联任务按 JE 有限重试（最多 3 次）。
* **归档**：`done` 超过 24h 的提交瘦身到 `arc:<SID>` 并删 `sub:/code:/res:`，让 `search` 永远有界。
* **落库节奏**：用户统计攒批，队列空闲时由发布线程统一写 `usr:` 并刷新 `rank`（近实时）。
* **优雅退出**：中控台「停止」或 Ctrl+C → 停止取任务 → 等 worker → 落库统计 → 刷榜 → 释放租约 → 写 `judge:<id>.ts=0`。
* **单实例**：同机第二个判题机会被 `data/state/daemon.lock` 硬拦（多实例请 `--allow-multi` 且用不同 `judge.id`）。

## 6. 云端 API 的硬约束（本项目所有设计的出发点）

| 约束 | 后果 | 本项目的对策 |
|---|---|---|
| `search` 单次 ≤100 条、省略 `count` 只回 1 条、顺序不可依赖 | 枚举/排序都不靠谱 | `count=100`+分页、本地按 `ts` 排序、热队列+归档 |
| **换行/单引号/反斜杠会破坏 `get` 的 JSON** | 代码与编译日志"写得进读不出" | 安全文本层（`store.safe/unsafe`，前端 `SafeText`/`Uri.Decode`） |
| 服务端会 503 限流 | 请求一密就失败 | 单取任务线程 + 本地队列 + 题目缓存 + 自适应退避 |
| 无原子自增 / 无 CAS | 不能做计数器与原子锁 | 时间戳主键 + 写后读回乐观锁 |
| 标签名长了读不回 | 静默丢数据 | 标签名一律短且结构化 |

## 7. 安全提醒

本机判题是**弱隔离**（无容器/seccomp）。Windows 侧已用 Job Object 限制内存、进程数（8）与孤儿回收，
但正式对外请：判题机跑独立用户、目录只授予该用户、用容器/WSL + cgroup、并**断网**（防火墙禁出站）。
最稳做法：执行面放 Linux 容器，本机只保留 `twdb.py + store.py + daemon.py` 协议层。

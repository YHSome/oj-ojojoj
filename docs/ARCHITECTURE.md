# OJ-OJOJOJ 判题后端 · 逻辑架构设计

> 主机：本工作区 `D:\OJ` 作为**判题后端（Judge Host）**
> 前端：**纯静态网页** `frontend/`（HTML/CSS/JS，浏览器直连云端）
> 云端存储：`http://tinywebdb.appinventor.space/webdb-你的实例编号`（HTTPS 同域）
> 云 API：`POST http://tinywebdb.appinventor.space/api`，`user=YOUR_USER`，`secret=YOUR_SECRET`

> **v2 变更**：前端已从"App Inventor 积木"改为**纯静态 HTML+JS+CSS 网页**，
> 代码提交前用**非对称加密（RSA-OAEP）**封装；详见
> [docs/加密与前后端分离.md](加密与前后端分离.md) 与 [frontend/README.md](../frontend/README.md)。
> 判题语义对齐 [MiniJudge](https://github.com/Mkrari/MiniJudge)（8 种判定 + JE、任务租约、
> `tokens/exact/float` 比较、题包规范、候选重判、备份恢复）。

---

## 1. 一句话架构

```
┌──────────────────────────┐        TinyWebDB REST (POST /api)
│  App Inventor 前端        │   ─────────────────────────────────────┐
│  · 题目列表 / 题面        │   update / get / search / count        │
│  · 提交代码 / 看结果      │   <─────────────────────────────────  │
└──────────────────────────┘                                        ▼
                                                    ┌───────────────────────────────┐
                                                    │  云端 KV「数据库 + 消息总线」  │
                                                    │  prob: test: sub: code: res:  │
                                                    │  usr: sess: q: lock: cmd:     │
                                                    │  reply: rank ann: judge:      │
                                                    └───────────────┬───────────────┘
                                                                    │ 轮询 q: / cmd:
┌───────────────────────────────────────────────────────────────────▼──────────────┐
│                        本机 Judge Host（D:\OJ）                                  │
│  daemon.py  多 worker 轮询 → 乐观锁认领 → 拉题/测试数据 → 沙箱编译执行 → 回写结果 │
│  runner.py  超时杀进程 / 内存限制（Job Object）/ 输出上限 / 峰值内存采样         │
│  judge.py   编译矩阵 · 评测机(diff/float/spj) · 逐点判分                         │
│  store.py   领域层（题目/提交/用户/排行榜/命令总线）                              │
│  twdb.py    TinyWebDB 客户端（重试 + 限速 + JSON 编解码）                          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**核心判断**：TinyWebDB 只是 KV（无事务、无 CAS、`search` 有 100 条上限、返回**无序**），
所以把「需要权威计算」的事全部放到本机 daemon：真正的一致性由 **写后读回的乐观锁** 保证，
前端只做纯粹的读写标签，不做任何需要原子性的操作。

---

## 2. 已实测的 API 语义（设计前提，不是猜测）

| 动作 | 请求参数 | 实测返回 |
|---|---|---|
| `update` | `tag`,`value` | `{"status":"success"}` |
| `get` | `tag` | `{"prob:P1001": "{\"pid\":...}"}`（单键字典，**值为字符串**） |
| `delete` | `tag` | 无内容（幂等，删不存在的标签也成功） |
| `count` | — | `{"count":"N"}` |
| `search` | `no`,`count`,`tag`,`type` | `type=both` → `{"tag":"value",...}`；`type=tag` → `{"tag":[...]}`；`tag=X` 为**子串包含**匹配 |

### 2.1 硬限制（全部实测确认，已固化进代码）

| # | 实测结论 | 影响 | 对策 |
|---|---|---|---|
| 1 | `search` 省略 `count` 时默认只返回 **1 条** | 以为能拿到全部，实际只回一条 | 客户端强制 `count=100` 并分页 |
| 2 | `search` 单次最多 **100** 条 | 大量提交时枚举不全 | 热队列 `q:` + 归档（§5） |
| 3 | `search`/`get` 返回**顺序不可依赖** | 队列顺序错乱 | 用 value 里的 `ts` 在本地排序 |
| 4 | `search` 的 `tag` 是**子串包含**匹配 | `P1001` 也能命中 `prob:P1001` | 命名空间用 `前缀:`，刻意避开子串碰撞 |
| 5 | 标签名长度 **~100 可用、200 读回 `null`** | 长标签名会静默丢失 | 所有标签名短且结构化 |
| 6 | 单值长度 ≥ **5000 字符**实测无损 | 不必做分片 | — |
| 7 | **真换行/制表符/控制字符不做转义** | `get` 返回非法 JSON，**解析直接失败** | 安全文本层（§2.2） |
| 8 | **单引号被转义成 `\'`（非法 JSON 转义）** | 只要内容含 `'`，该标签就读不回来 | 安全文本层（§2.2） |
| 9 | **反斜杠被静默吃掉** | 内容悄悄损坏 | 安全文本层（§2.2） |
| 10 | 双引号转义正确（`\"`） | 可以用 | — |
| 11 | 无原子自增 / 无 CAS | 无法用中央计数器、无法原子抢锁 | 时间戳主键 + 写后读回乐观锁（§4.3） |
| 12 | 服务端会限流（**HTTP 503**） | 请求打多了直接失败 | 自适应退避 + 单取任务线程 + 本地缓存（§5.1） |
| 13 | 单值 **10000 字符可用、20000 字符被破坏** | 长代码/长结果存不下 | 按 8000 字符分片到 `code:<SID>:i` / `res:<SID>:i` |
| 14 | **`delete` 是软删除**：search/count 消失但 `get` 返回 `"null"` | 误判"标签还在" | 客户端把字面量 `"null"` 视作不存在 |
| 15 | 官方 API 有 `Access-Control-Allow-Origin: *`，但**不支持自定义请求头** | 纯静态前端可直连，但只能用表单式简单请求 | 前端只用 `application/x-www-form-urlencoded` |
| 16 | 同机两个判题机实例（同 `judge_id`）会互相抢同一提交 | 判定被覆盖（实测被覆盖成 CE） | `data/state/daemon.lock` 单实例锁 + `--allow-multi` |
| 17 | **JSON 数组值会被服务端自动解析**：值形如 `["P1001"]` 时 `get` 返回数组，而对象 `{"k":1}` 仍返回字符串 | 前端对它 `JSON.parse` 会把数组强转成 `a,b,c` 而报错 → 题目列表空白 | 读到非字符串就直接用；前后端都按"可能是已解析值"处理 |
| 18 | 解析顺序：**必须先 `JSON.parse` 再反转义** | 先反转义会把 `%0A` 变成真换行 → JSON 里出现裸换行 → 解析失败（题面/编译日志全中招） | 固定顺序 parse→unsafeObj（`tinywebdb.js: getJson` / `store.read_chunked`） |

### 2.2 安全文本层（safe/unsafe）—— 必须前后端一起做

因为第 7/8/9 条，**任何含换行、单引号或反斜杠的文本都不能直接进 KV**。
本后端在 `store.py` 里加了一层百分号转义：

```
safe("it's")          -> "it%27s"
safe("a\nb")          -> "a%0Ab"
safe('printf("%d")')  -> 'printf("%25d")'
unsafe(...)           // 单遍扫描还原，正确处理 %250A 这类嵌套
```
* 编码字符集：`%`、`\`、`'`、以及所有 `0x00-0x1F`、`0x7F` 控制字符。
* 写入前 `safe_obj()` 递归转义 JSON 里所有字符串；读出后 `unsafe_obj()` 还原。
* 结果保证：**不含反斜杠、不含真换行**，因此对云端永远合法。
* 前端（App Inventor）**必须做同样的编码**：发之前 `SafeText(text)`，读之后 `Uri.Decode(text)`。
  见 `docs/FRONTEND_AI2.md` §2.5。

> 这一层是本项目能跑通的关键。没有它，`code:`（必然含换行）与 `res:`（编译日志常含单引号）
> 都会变成"写进去、读不出来"的死标签，而且**一个坏标签会让整页 `search` 一起解析失败**。

### 2.3 容错兜底

* `twdb.search_pairs()` 在整页 JSON 解析失败时，自动退化为 `type=tag` 枚举标签名 + 逐条 `get`，
  跳过错标签，保证枚举不中断。
* `update` 未收到 `{"status":"success"}` 会告警并计入重试。


---

## 3. 标签（Tag）Schema —— 前后端唯一契约

所有值均为 JSON 字符串。

### 3.1 元信息 / 命名空间

| Tag | 值 | 维护者 |
|---|---|---|
| `oj:meta` | `{schema,ver,updated,judges:[...]}` | daemon |
| `idx:problems` | `["P1001","P1002",...]` 有序题号表（仅展示用） | 管理员 CLI |
| `rank` | `{ts,order:[{user,score,ac,submit,last_ts}]}` | daemon 定期重建 |
| `ann:latest` / `ann:<n>` | `{n,title,body,ts}` | 管理员 CLI |

### 3.2 题目

| Tag | 值 |
|---|---|
| `prob:<PID>` | `{pid,title,statement,difficulty,tags[],time_limit_ms,memory_limit_kb,output_limit_kb,checker,float_eps,case_count,total_score,visible,created,rev,updated}`，`rev` = 题面+测试点的 sha1 前 12 位，用于让判题机缓存自动失效 |
| `test:<PID>:<idx>` | `{i,score,in,out}`；大数据题用引用式：`{i,score,in_ref:"tin:...",out_ref:"tout:..."}` |
| `tin:<PID>:<idx>` / `tout:<PID>:<idx>` | 原始输入 / 输出文本（大测试点专用） |

### 3.3 提交（热路径，刻意拆三块）

| Tag | 值 |
|---|---|
| `q:<SID>` | `{sid,ts,pid,lang,user}` —— **队列标签**，只在待判期间存在，判完即删 |
| `sub:<SID>` | `{sid,user,pid,lang,status,ts,judge,verdict,score,time_ms,memory_kb,cases_passed,case_count,msg}` |
| `code:<SID>` | 源码原文（不套 JSON，避免转义膨胀；前端"查看我的代码"直接读它） |
| `res:<SID>` | `{sid,verdict,score,cases:[{i,verdict,time_ms,memory_kb,msg}],compile_log,checker}` |
| `lock:<SID>` | `{judge,ts,nonce}` —— 认领锁 |
| `arc:<SID>` | 归档后的瘦身结果（`sub:` 被删除后仍可查历史） |

`status ∈ {pending, judging, done, failed}`；`verdict ∈ {AC,WA,TLE,MLE,RE,CE,OLE,PE,PAC,UD,SKIP}`
（`PAC` = 部分分，`UD` = 未知错误，`PE` = 格式错，`OLE` = 输出超限）。

### 3.4 用户 / 会话

| Tag | 值 |
|---|---|
| `usr:<user>` | `{user,nick,salt,pwd,created,is_admin,submit_count,ac_count,score,solved[],best{pid:score},last_ts}`，`pwd=sha256(salt+":"+pass)` |
| `sess:<token>` | `{token,user,ts,expire}` |

> App Inventor 没有 sha256。所以**注册/登录走命令总线**（§6），由 daemon 完成加盐哈希，前端只读结果。

### 3.5 命令总线（前端 → 后端的 RPC）

| Tag | 值 |
|---|---|
| `cmd:<CID>` | `{cid,op,args{},user,token,status,ts}`，`status ∈ {pending,done,error}` |
| `reply:<CID>` | `{ok,data{},msg,ts}` |
| `lb:<SID>` | `{n,title,body,ts}` |（保留） |

支持 `op`：`hello` `register` `login` `logout` `profile` `mysubs` `problem_list` `stat`
`newid` `rejudge`(admin) `add_ann`(admin) `judge_status`。

### 3.6 判题机自身

| Tag | 值 |
|---|---|
| `judge:<judge_id>` | `{id,host,ts,workers,busy,cpu,version}` 心跳，`search?tag=judge:` 即"在线判题机" |

---

## 4. 数据流

### 4.1 提交一次题（端到端）

```
前端                           云端 KV                          本机 daemon
 │  update cmd:<CID> {op:newid} │                                  │
 │────────────────────────────► │ ◄── search?tag=cmd: ─────────────│ (轮询)
 │                              │ ──── update reply:<CID> {sid} ──►│
 │  get reply:<CID>             │                                  │
 │◄─────────────────────────────│                                  │
 │  update code:<SID> = 源码     │                                  │
 │  update sub:<SID> = {...pending}                                │
 │  update q:<SID>   = {ts,...}  │                                  │
 │────────────────────────────► │ ── search?tag=q:&count=100 ─────►│
 │                              │                                  │ 排序 → 认领(乐观锁)
 │                              │ ◄── update lock:<SID> ───────────│
 │                              │ ◄── update sub:<SID>.status=judging
 │                              │ ◄── get test:P1001:* / 本地缓存  │
 │                              │     编译 → 逐点执行 → 判分        │
 │                              │ ◄── update res:<SID> ────────────│
 │                              │ ◄── update sub:<SID> 终态 ───────│
 │                              │ ◄── delete q:<SID> / lock:<SID> ─│
 │  get sub:<SID> (轮询)         │                                  │
 │◄─────────────────────────────│                                  │
 │  get res:<SID> (详情)         │                                  │
```

### 4.2 判题机状态机（每个提交）

```
pending ──claim(乐观锁)──► judging ──AC/WA/TLE/...──► done
   ▲                        │
   │                        └─ lock 超时(LOCK_TTL) 且 status=judging  ──► 回退 pending（崩溃恢复）
   │                        └─ 编译失败 ──► done(CE)
   └─ 无编译器/数据缺失 ──► failed(SKIP/UD)
```

### 4.3 乐观锁认领（无 CAS 环境下的正确做法）

```
1. 读出 lock:<SID>；若存在且 now-ts < LOCK_TTL(180s) → 跳过（别人在判）
2. 写入 lock:<SID> = {judge:me, ts:now, nonce:rand}
3. 抖动 sleep 300~800ms（打散并发窗口）
4. 回读 lock:<SID>；nonce == mine → 认领成功；否则放弃（对手赢了）
5. 把 sub:<SID>.status 置 judging，然后开始判题
```
**为什么安全**：TinyWebDB 无原子性，但「写→等→读」把并发窗口收敛为「后写者赢」，
配合抖动，双判概率极低；万一双判，结果内容一致（同代码同数据），只是浪费算力。

---

## 5. 容量与一致性策略

### 5.1 针对云端限流（HTTP 503）的架构决策

实测：轮询稍密就会 503。因此**不是每个 worker 各自去云端轮询**，而是：

```
[主循环 fetcher]  每 queue_refresh_interval_s(4s) 拉一次 q: 队列  ←── 全进程只有它碰云端
        │  填充
        ▼
[本地队列 deque]   worker×N 从这里取（完全不产生 HTTP）
        │
        ├─ 题目/测试点：本地文件缓存 cache/problems.json（TTL 120s + rev 指纹校验）
        ├─ 认领锁：pending 提交跳过"先读锁"，只花 2 次请求
        ├─ 用户统计：攒批，由 [发布线程] 在队列空闲时统一落库（每用户 1 次 get+put）
        └─ 客户端：自适应退避（503 → 指数静默 + 拉大最小间隔），成功后缓慢恢复
```

结果：判一个提交的云端往返从"十几次"降到 **约 6~8 次**，且并发量与请求量解耦。

### 5.2 其余策略

| 问题 | 对策 |
|---|---|
| `search` 单次 ≤100 | ① 热点命名空间 `q:` 只装"待判"项，随时 <100；② `count=100` + 按 `no` 分页；③ daemon 本地 `seen` 集去重 |
| 提交历史无限增长 | **归档**：`done` 且早于 `ARCHIVE_TTL(24h)` 的提交 → 写 `arc:<SID>` 瘦身结果 + 删 `sub:/code:/res:`，`search?tag=sub:` 恒定有界 |
| 无事务 | 幂等写 + 重试；结果先写 `res:` 再翻 `sub:` 状态位（前端只见一致状态） |
| 排行榜 | 队列空闲时由发布线程从 `usr:` 重建 `rank`（单写者，无竞争） |
| 会话过期 | 维护周期清理 `sess:`，`expire < now` 即删 |
| 网络抖动 | 指数退避重试 + 全局限速 + 503 自适应静默 |


---

## 6. 为什么要有「命令总线」

前端能力受限（无 sha256、无排序、无聚合、无 100 条以上列表、`search` 无序）：
把这些需求下沉为 `cmd:` RPC，daemon 是唯一可信计算方。收益：

* 密码不落地明文，`usr:<user>.pwd` 只存 `sha256(salt+":"+pwd)`；
* 「我的提交」「题目列表」「排行榜」「判题机状态」全部由 daemon 聚合后用一条 `reply:` 返回（绕开 100 条上限与无序）；
* 管理员操作（加题、重测、发公告）可校验 `is_admin`，前端无法越权写题目数据。

---

## 7. 本机目录结构（交付物）

```
D:\OJ
├─ docs\ARCHITECTURE.md          本文件
├─ docs\PROTOCOL.md              前后端接口契约（给前端开发者）
├─ docs\FRONTEND_AI2.md          App Inventor 组件/积木搭建说明
├─ config\oj_config.json         API 地址/密钥/判题机 ID/语言/限制/周期
├─ backend\
│  ├─ twdb.py                    TinyWebDB 客户端（重试/限速/503 退避/坏标签兜底）
│  ├─ store.py                   领域层（标签 Schema + 安全文本层 + 乐观锁）
│  ├─ runner.py                  沙箱执行（超时/内存/输出上限/峰值采样）
│  ├─ judge.py                   编译矩阵 + 评测机 + 判分
│  ├─ daemon.py                  主循环（fetcher/worker/发布线程/维护/心跳）
│  ├─ admin_cli.py               运维 CLI（加题/推题/重测/排行榜/归档）
│  └─ config.py                  配置加载
├─ tools\
│  ├─ oj.sh                      Git Bash 快捷入口（推荐用法）
│  ├─ mock_client.py             模拟 App Inventor 前端的端到端自测客户端
│  ├─ selfcheck.py               环境自检（含真编译真判题冒烟）
│  ├─ probe_limits.py            实测云端 KV 的长度/标签名限制
│  ├─ probe_quotes.py            实测云端 KV 的引号/反斜杠/换行行为
│  ├─ diag.py / diag2.py         编译器与环境的诊断脚本
│  └─ cleanup_probe.py           清理实验残留标签 + 重新播种
├─ data\
│  ├─ problems\<PID>\            题库本地副本（problem.json + tests + checker.py）
│  ├─ work\<SID>\                每次提交的编译/运行产物
│  ├─ cache\problems.json        题目与测试点本地缓存（TTL + rev 指纹）
│  ├─ state\seen.json            已判提交去重集
│  └─ tmp\                       编译器临时目录（必须，宿主 %TEMP% 可能不可写）
├─ logs\judge.log
├─ tools\w64devkit\              便携 C/C++ 工具链（GCC 14.1，实测可用）
├─ tools\git-portable\           便携 Git Bash（本机没有 git bash，已就地装配）
├─ start_judge.cmd / .sh  judge_once.cmd
└─ README.md
```

---

## 8. 判题执行模型（本机）

1. **编译矩阵**（`config` 可扩）：
   `cpp: g++ -O2 -std=c++17 -static`、`c: gcc -O2 -static`、`py: python -X utf8`（解释型免编译）、
   `java: javac`+`java`、`pas: fpc -O2`。编译超时 `COMPILE_TL(15s)`，编译日志截断 `COMPILE_LOG_MAX(8KB)`。
2. **运行**：stdin 文件重定向，stdout/stderr 落文件（**不用管道**，避免死锁）；
   墙钟软限 = `time_limit`，硬杀 = `time_limit × 2 + grace`，超时/超限即 TLE；
   Windows 用 **Job Object**（`JOB_OBJECT_LIMIT_PROCESS_MEMORY` + `KILL_ON_JOB_CLOSE` + `ActiveProcessLimit=8`）
   做内存上限与孤儿回收，Linux 用 `resource.setrlimit`；
   峰值内存：Job Object `PeakJobMemoryUsed`，取不到则 20ms 采样线程保底。
3. **子进程环境（两个已踩过的坑，务必保持）**：
   * 编译/运行都用 **干净且完整** 的环境（`env_replace=True`），只保留 Windows 系统变量 +
     工具链目录 + Windows 形态的 PATH 项。直接透传宿主 PATH 时（从 Git Bash 启动会是
     `/c/...:/usr/bin` 这类 MSYS 路径），gcc 会报
     `cannot execute 'cc1plus.exe': CreateProcess: No such file or directory`。
   * **编译阶段绝不能套 Job Object 的 `ActiveProcessLimit=1`**：gcc→cc1plus 是父子进程，
     限制 1 会让编译全废。当前配置：编译 `job_object=false`，运行 `active_process_limit=8`。
   * `TMP/TEMP/TMPDIR` 一律指到 `data/tmp`（宿主的 `%TEMP%` 对子进程可能不可写）。
4. **输出上限**：判完后检查 stdout 文件大小，超 `output_limit_kb` → `OLE`。
5. **评测机**：`diff`（默认：逐行去行尾空白 + 忽略末尾空行）、`strict`（逐字节）、
   `float`（`|a-b| ≤ eps` 或相对误差）、`spj`（`data/problems/<PID>/checker.py`，argv = in out ans）。
6. **判分**：单点分 = `test.score`；全过 → `AC`（满分）；有分 → `PAC`；无分 → 首个失败点的判定。
   用户总分 = **各题历史最好分之和**（`usr.best`），`solved` 只记满分题。
7. **不泄露答案（判题机只判题）**：`WA/PE/浮点不匹配` 对外只给「答案错误」，**不回期望值/实际值**；
   逐点对比明细写在判题机本地 `data/work/<SID>/__judge_detail.txt` + 判题日志，供管理员复盘。
   `TLE/MLE/OLE/RE/CE` 保留资源数据与选手**自己的**报错（不含标准答案）。
   开关：`judge.public_case_detail`（默认 false）、`judge.public_stderr`（默认 true），中控台可改。
8. **安全边界（务必知悉）**：本地判题对恶意代码只有弱隔离（无容器、无 seccomp）。
   生产建议：① 判题机跑独立用户/目录；② 断网（防火墙禁出站）或 WSL/容器 + cgroup；
   ③ `ActiveProcessLimit` 已抑制 fork 炸弹；④ 最稳是本机跑 WSL 内的 Linux judge，daemon 只做协议层。


---

## 9. 前端（App Inventor）契约摘要

前端只使用 `update / get / search / count` 与上述标签：

| 前端要做的 | 调用 |
|---|---|
| 拉题目列表 | `get(idx:problems)`，或 `search(tag=prob:, type=tag, count=100)` |
| 看题面 | `get(prob:<PID>)` |
| 注册/登录 | `update(cmd:<CID>)` → 轮询 `get(reply:<CID>)` |
| 拿提交号 | `cmd:newid` |
| 提交 | `update(code:<SID>)` + `update(sub:<SID>)` + `update(q:<SID>)` |
| 看判题进度 | `get(sub:<SID>)` → `status` 变 `done` 后 `get(res:<SID>)` |
| 我的提交 | `cmd:mysubs` |
| 排行榜 | `get(rank)` |
| 判题机是否在线 | `search(tag=judge:, count=100)` |

详细积木搭法见 `docs/FRONTEND_AI2.md`；字段级契约见 `docs/PROTOCOL.md`。

---

## 10. 运行与运维

```bash
cd /d/OJ
bash tools/oj.sh selfcheck      # 环境自检（API / 编译器 / 沙箱 / 编码 / 真判题冒烟）
bash tools/oj.sh seed           # 把本地题库推到云端
bash tools/oj.sh daemon         # 常驻判题机（Ctrl+C 优雅退出）
bash tools/oj.sh once           # 判一轮就退出（计划任务）
bash tools/oj.sh demo --pid P1001 --user alice --samples ac wa ce tle   # 端到端自测
bash tools/oj.sh rank / list --what subs / inspect --sid X / rejudge --pid P1001 / gc
```
Windows 也可直接双击 `start_judge.cmd` / `judge_once.cmd`。

**崩溃恢复**：daemon 启动时扫描 `sub:` 中 `status=judging` 且 `lock:` 已过期的提交 → 重置为 `pending` 并重入 `q:`。
**优雅退出**：Ctrl+C → 停止取任务 → 等 worker 结束 → 落库用户统计 → 刷榜 → 释放 `lock:` → 写 `judge:<id>.ts=0`。

### 10.1 实测验收记录（本机实跑，非设计推演）

| 验收项 | 结果 |
|---|---|
| 环境自检（24 项） | 全绿：API 200、GCC 14.1、Job Object 可用、超时熔断 1905ms 生效 |
| 编码往返（本地 + 云端实写实读） | 换行 / 单引号 / 双引号 / 反斜杠 / 百分号全部无损 |
| 判题链路冒烟 | 真编译真运行 → `AC` 128ms / 1828KB |
| `P1001 A+B` 提交 | `AC` 100 分（3/3）、`WA`（带"第 N 行不同"定位）、`CE`（带 gcc 原文）、`TLE`（3065ms 熔断） |
| `P1002 区间求和` 提交 | `AC` 100 分（2/2）、`PAC` 30 分（1/2，按题最好分计入排行榜） |
| 排行榜 | 正确反映 score/ac/submit，队列空闲约 3~5s 内刷新 |
| 命令总线 | `hello / register / login / submit / mysubs` 全部往返成功 |
| 限量与退避 | 遇到 503 自动静默 2~30s 并拉大间隔，恢复后自动提速，不丢任务 |

### 10.2 本机已装配的两套便携运行时

| 目录 | 用途 | 说明 |
|---|---|---|
| `tools\w64devkit\` | C/C++ 编译器（GCC 14.1，含 as/ld/make） | 本机原本没有任何编译器，已装好；`config.paths.toolchain_dirs` 指向其 `bin` |
| `tools\git-portable\` | Git Bash 5.3 + git 2.56 | 本机原本没有 git bash，已就地解压装配；命令入口见 `tools/oj.sh` |


---

## 11. 扩展路线（不改变前端契约）

| 阶段 | 内容 |
|---|---|
| v1（本交付） | 单机多 worker、C++/C/Py/Java/Pas、diff/float/spj、排行榜、命令总线、归档 |
| v2 | 交互题（`spj` 双向管道）、Special Judge 沙箱、题目权限/比赛（`contest:*`）、提交代码查重 |
| v3 | 多判题机（`judge:` 心跳 + 权重调度 + 结果多数表决）、WSL/容器强隔离、SQLite 本地镜像加速 search |
| v4 | 前端换 `webdb` 浏览页做管理员后台；埋点统计（语言分布/通过率）写 `stat:*` |

> 兼容性铁律：**前端只依赖 `docs/PROTOCOL.md` 中的标签与字段**；后端任何重构都不得改变这些标签语义。

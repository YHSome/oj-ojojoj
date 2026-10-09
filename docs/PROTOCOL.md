# 前后端接口契约（OJ-OJOJOJ v1.0）

> 后端：本机 `D:\OJ` 判题机。云端：TinyWebDB。
> **前端只依赖本文件描述的标签与字段**；后端重构不得改变这些语义。

---

## 0. 传输层

| 项 | 值 |
|---|---|
| 请求 | `POST http://tinywebdb.appinventor.space/api`（HTTPS 同域可用） |
| 编码 | `application/x-www-form-urlencoded` |
| 公共参数 | `user=YOUR_USER`、`secret=YOUR_SECRET`、`action=<update|get|delete|count|search>` |
| 浏览页 | `http://tinywebdb.appinventor.space/webdb-你的实例编号` |

响应（JSON 文本）：

| action | 参数 | 返回 |
|---|---|---|
| `update` | `tag`,`value` | `{"status":"success"}` |
| `get` | `tag` | `{"<tag>": "<value>"}`（不存在时 `{}`） |
| `delete` | `tag` | 空 |
| `count` | — | `{"count":"N"}` |
| `search` | `no`,`count`,`tag`,`type` | `type=both`→`{"tag":"value",...}`；`type=tag`→`{"tag":[...]}`；`tag` 为**子串**匹配；`count` 上限 **100**，默认 1 |

**四条铁律（实测得出，务必遵守）**
1. `search` 必须显式传 `count`（省略时默认只返回 1 条）。
2. `search` 返回**顺序不可依赖** —— 排序一律靠 value 里的 `ts`。
3. 单次最多 **100** 条；要更多得用 `no` 翻页，或改走 `cmd:` 聚合接口。
4. 所有 value 都是**字符串**，复杂结构请自行 JSON 序列化/反序列化。

### 0.1 安全文本层（**不做就会读不回来**，前端必须实现）

云端 KV 对手工拼 JSON 的转义只做了一半，实测：

| 内容 | 直接存的后果 |
|---|---|
| 真换行 / 制表符 / 控制字符 | 返回**非法 JSON** → `get` 解析失败 |
| 单引号 `'` | 被转义成 `\'`（非法转义）→ `get` 解析失败 |
| 反斜杠 `\` | 被静默吃掉 → 内容损坏 |
| 双引号 `"` | 正常（`\"`） |

所以**进入 KV 的每个字符串**都要先做百分号转义，规则只有一条：

```text
SafeText(s) = 把 [ %   \   '   换行  回车  制表  其它控制字符 ] 替换成 %XX （大写十六进制）
读回时 UnSafeText(s) = 把 %XX 还原（单遍左到右扫描，%25 不会再被二次解码）
```

前端伪代码（App Inventor 见 `FRONTEND_AI2.md` §2.5）：
```
SafeText(text)   : % -> %25, \ -> %5C, ' -> %27, 换行 -> %0A, 回车 -> %0D, 制表 -> %09
UnsafeText(text) : Uri.Decode(text)      // AI2 内置，等价于上面的还原
```
顺序必须是**先 `%` 后其它**，否则会把自己产生的 `%` 再转义一层。

**读写流程**：前端发 `value = Uri.Encode(SafeText(原文))`；收到 `value` 后 `UnsafeText(value)`。
后端 `store.py` 的 `safe()/unsafe()`、`safe_obj()/unsafe_obj()` 就是这一层的实现。


---

## 1. 标签总览

| 标签 | 谁写 | 谁读 | 说明 |
|---|---|---|---|
| `oj:meta` | 后端 | 前端 | 系统元信息、在线判题机、限制 |
| `idx:problems` | 后端 | 前端 | 题号有序数组 `["P1001","P1002"]` |
| `rank` | 后端 | 前端 | 排行榜快照 |
| `ann:latest` / `ann:<n>` | 后端 | 前端 | 公告 |
| `prob:<PID>` | 后端 | 前端 | 题面与限制 |
| `test:<PID>:<i>` | 后端 | — | 测试点（前端一般不需要读） |
| `q:<SID>` | **前端** | 后端 | 待判队列（判完由后端删除） |
| `sub:<SID>` | **前端**创建，后端更新 | 前端 | 提交状态 |
| `code:<SID>` | **前端** | 后端 | 源码原文 |
| `res:<SID>` | 后端 | 前端 | 详细结果（各点判定、编译日志） |
| `arc:<SID>` | 后端 | 前端 | 归档结果（`sub:` 被清理后仍可查） |
| `cmd:<CID>` / `reply:<CID>` | 前端写 cmd / 后端写 reply | 双向 | 命令总线（RPC） |
| `usr:<user>` / `sess:<token>` | 后端 | 后端 | 用户与登录态（前端不直接读，走 `cmd:`） |
| `judge:<judge_id>` | 后端 | 前端 | 判题机心跳 |

---

## 2. 字段定义

### 2.1 `prob:<PID>`
```json
{
  "pid": "P1001", "title": "A+B Problem",
  "statement": "题面（纯文本，建议用 \\n 换行）",
  "difficulty": "easy|medium|hard", "tags": ["入门"],
  "time_limit_ms": 1000, "memory_limit_kb": 262144, "output_limit_kb": 65536,
  "checker": "diff|strict|float|spj", "float_eps": 1e-06,
  "case_count": 3, "total_score": 100, "visible": true, "created": 1730000000
}
```

### 2.2 `sub:<SID>`（前端创建时的初始值）
```json
{ "sid":"123456789", "user":"alice", "pid":"P1001", "lang":"cpp",
  "status":"pending", "ts":1730000000, "judge":"", "verdict":"",
  "score":0, "time_ms":0, "memory_kb":0, "cases_passed":0,
  "case_count":0, "msg":"排队中" }
```
后端会把 `status` 依次改为 `judging` → `done`（或 `failed`），并补齐
`verdict/score/time_ms/memory_kb/cases_passed/case_count/msg`。

* `status`：`pending` 排队 / `judging` 评测中 / `done` 完成 / `failed` 后端异常
* `verdict`：`AC` 通过、`WA` 答案错、`TLE` 超时、`MLE` 超内存、`RE` 运行错误、
  `CE` 编译错误、`OLE` 输出超限、`PE` 格式错、`PAC` 部分分、`UD` 未知、`SKIP` 跳过

### 2.3 `res:<SID>`
```json
{ "sid":"123456789", "verdict":"WA", "score":20,
  "cases":[{"i":1,"verdict":"AC","time_ms":3,"memory_kb":1420,"score":20,"msg":"通过"},
           {"i":2,"verdict":"WA","time_ms":2,"memory_kb":1380,"score":0,"msg":"答案错误"}],
  "compile_log":"", "checker":"tokens", "ts":1730000000 }
```

> **判题机只负责判题，不回答案明细**（默认 `judge.public_case_detail=false`）：
> * `WA` / `PE` / 浮点不匹配 → `msg` 只有「答案错误 / 输出格式错误」，**不含期望值、不含实际值**，
>   防止选手用"输出钓鱼"试出隐藏测试点答案。
> * `TLE/MLE/OLE/RE/CE` → 保留资源数据与选手**自己的**报错（退出码、超时毫秒、内存、编译器报错），
>   这些不含标准答案。
> * 逐点对比明细（`第 N 个 token 不同: 期望 … 实际 …`）只写在判题机本地
>   `data/work/<SID>/__judge_detail.txt` 与判题日志里，供管理员复盘，**不进云端**。
> * 需要调试题包时可临时把 `judge.public_case_detail` 打开（中控台参数里可改）。
> * `RE` 时选手 stderr 是否回传由 `judge.public_stderr` 控制（默认开）。

### 2.4 `rank`
```json
{ "ts":1730000000, "total":3,
  "order":[{"user":"alice","nick":"alice","score":100,"ac":1,"submit":2,"rank":1}] }
```

### 2.5 命令总线
写 `cmd:<CID>`：
```json
{ "cid":"c1234567", "op":"login", "args":{"user":"alice","pass":"1234"},
  "user":"", "token":"", "status":"pending", "ts":1730000000 }
```
轮询 `reply:<CID>`：
```json
{ "ok":true, "data":{"token":"...","user":{...}}, "msg":"登录成功", "ts":1730000000 }
```

| op | args | data |
|---|---|---|
| `hello` | — | `server/version/judge_id/langs/problems/link` |
| `whoami` | —（用 `token`） | `user`；token 失效时 `ok=false`，前端据此清登录态 |
| `register` | `user,pass,nick?` | `token,user` |
| `login` | `user,pass` | `token,user` |
| `logout` | — | — |
| `profile` | — | `user,subs` |
| `mysubs` | `user?,limit?` | `subs`（绕开 100 条上限的聚合查询） |
| `problem_list` | — | `problems[{pid,title,difficulty,total_score,case_count,time_limit_ms,solved}]` |
| `stat` | — | `problems,users,judges,judged,top` |
| `newid` | — | `sid`（分配一个唯一提交号） |
| `submit` | `pid,lang,code` | `sid`（一条命令完成提交，代码随 args 传） |
| `judge_status` | — | `judge,busy,queue,langs,stats` |
| `rejudge` | `sid` | 需管理员 |
| `add_ann` | `title,body` | 需管理员 |

> `token` 由 `login/register` 返回，后续请求把它填进 `cmd.token`。
> **密码永不明文落地**：后端存 `sha256(salt+":"+pass)`。

---

## 3. 前端标准流程

### 3.1 登录
```
1) CID ← 本地生成唯一串
2) update  cmd:<CID>  {"cid":CID,"op":"login","args":{"user":U,"pass":P},"status":"pending","ts":now}
3) 每 1 秒 get reply:<CID>，直到拿到 → ok=true 时保存 data.token
```

### 3.2 题目列表 / 题面
```
题目列表 : get idx:problems              → ["P1001","P1002"]
（或聚合）: cmd:problem_list              → 含标题与是否已解决，推荐
题面     : get prob:<PID>                 → 解析 JSON 取 title/statement/...
```

### 3.3 提交（三条 update，顺序不能变）
```
SID ← 本地生成 9 位数（时间戳后 6 位 + 3 位随机），或 cmd:newid 拿
1) update code:<SID>  <源码原文>            ← 先写代码
2) update sub:<SID>   {"sid":SID,"user":U,"pid":PID,"lang":LANG,"status":"pending","ts":now,...}
3) update q:<SID>     {"sid":SID,"ts":now,"pid":PID,"lang":LANG,"user":U}   ← 最后入队
```
> 顺序不可颠倒：判题机可能在第 3 步后任意时刻取走任务，所以代码与提交记录必须先就位。

### 3.4 取结果
```
每 1~2 秒 get sub:<SID>
  status=pending/judging → 继续等（界面显示"评测中"）
  status=done            → get res:<SID> 取每点详情
  status=failed          → 后端异常，看 msg
```

### 3.5 排行榜 / 判题机在线
```
排行榜   : get rank
判题机   : search tag=judge: count=100 type=both  → 有心跳即在线的判题机
```

---

## 4. 配额与注意事项

| 事项 | 建议 |
|---|---|
| 轮询频率 | 单客户端 ≤ 1 次/秒；多客户端各自轮询自己的 `reply:`/`sub:` |
| value 大小 | 代码 ≤ 32KB（TinyWebDB 是社区公共小服务，别塞大文本）；测试数据大时后端用 `tin:/tout:` 引用式存储 |
| 提交号 | 9 位数字（后 6 位秒级时间戳 + 3 位随机），碰撞率极低；不要用自增计数器 |
| 题目列表 | 超过 100 题时不要用 `search`，改用 `cmd:problem_list` |
| 断线重连 | 任何一次调用失败就重试（3 次、指数退避）；`q:` 写入成功后即使前端崩溃，判题机照样会判 |
| 幂等 | 重复写同一个 `sub:` 是安全的；重复入队同一个 `q:` 也只会被判一次（后端有 seen 去重） |

# App Inventor 前端搭建说明（对接 D:\OJ 判题后端）

## 0. 关键结论：用 `Web` 组件，不要用 `TinyWebDB` 组件

本后端的云端接口是**带 `user/secret/action` 的自定义 REST**（`/api`），
App Inventor 内置的 `TinyWebDB` 组件只会发标准协议（`getvalue/storeavalue`），
**对不上**。所以前端一律使用 **Web 组件 + 手搓 form body**：

```
Web1.Url            = "http://tinywebdb.appinventor.space/api"
Web1.PostText(text, "http://tinywebdb.appinventor.space/api")
```
`text` 形如 `user=YOUR_USER&secret=YOUR_SECRET&action=update&tag=sub%3A123&value=...`
（`value` 必须用 `Uri.Encode` 转义）

---

## 1. 组件清单

| 组件 | 用途 |
|---|---|
| `Web1`（Web） | 所有 API 调用（POST） |
| `Uri1`（Uri） | `Uri.Encode(值)` 转义 |
| `Clock1`（Clock，Timer） | 轮询判题结果（`TimerInterval=1500`） |
| `Notifier1` | 提示 |
| 每个界面：`ListView1` / `Label` / `TextBox` / `Button` | 交互 |
| `TinyDB1`（可选） | 本地记住 token 与用户名 |

**Screen 规划**：`Screen1`（登录/注册）→ `Screen_List`（题目列表）→
`Screen_Problem`（题面 + 代码框 + 提交）→ `Screen_Result`（结果详情）→
`Screen_Rank`（排行榜）→ `Screen_MySubs`（我的提交）

---

## 2. 全局过程（放在 Screen1 或公共界面，各屏拷一份）

### 2.1 发一次请求（核心）
```text
procedure ApiCall(action, tag, value, otherParams)
  local body = join(
      "user=YOUR_USER",
      "&secret=YOUR_SECRET",
      "&action=", action,
      if(tag   = "" then "" else join("&tag=",   Uri1.Encode(tag))),
      if(value = "" then "" else join("&value=", Uri1.Encode(value))),
      otherParams)                       // 例如 "&no=1&count=100&type=both"
  Web1.PostText(body, "http://tinywebdb.appinventor.space/api")
end procedure
```

### 2.2 读取一个标签
```text
procedure GetTag(tag)  →  字符串
  ApiCall("get", tag, "", "")
  // 在 Web1.GotText 里：json ← Web1.JsonTextDecode(responseContent)
  //   if is a dictionary then 返回值 = get value for key tag  （不存在返回 ""）
```

### 2.3 写入一个标签
```text
procedure SetTag(tag, value)
  ApiCall("update", tag, value, "")
  // 返回 {"status":"success"}
```

### 2.4 复杂值编解码
App Inventor 有内置列表/字典 → JSON：
```text
json文本 = Web1.JsonTextDecode? 否 —— 用下面的做法：
   写： value = Web1.JsonTextEncode?  (AI2 无 Encode)  →
       用 `List to JSON` 扩展，或手搓：  join("{", "\"sid\":\"", SID, "\",", ...)
   读： 字典 = Web1.JsonTextDecode(responseContent)   ← 组件自带，可直接解析
```
> 结论：**读用 `Web1.JsonTextDecode`**；**写用字符串拼接**（或用 JsonUtils 扩展）。
> 拼接时注意所有字符串值都要套双引号、数字不要套引号。

---

### 2.5 安全文本层（**必须做，否则中文换行/单引号会读不回来**）

云端 KV 的转义只做了一半：**换行、单引号、反斜杠都会破坏 `get` 的返回**（实测）。
所以发送前要转义、读回后要还原。AI2 里加两个过程：

```text
procedure SafeText(text)
  # 顺序很重要：先 % 再其它
  t = replace all(text,  "%",  "%25")
  t = replace all(t,     "\",  "%5C")
  t = replace all(t,     "'",  "%27")
  t = replace all(t,     "\n", "%0A")
  t = replace all(t,     "\r", "%0D")
  t = replace all(t,     "\t", "%09")
  return t
end procedure

procedure UnsafeText(text)
  return Uri1.Decode(text)      # AI2 内置 Uri.Decode，等价于还原
end procedure
```
> `\n`/`\r`/`\t` 在 AI2 积木里用 `join(char 10)`、`join(char 13)`、`join(char 9)` 表示。

**因此 `SetTag` / `ApiCall` 里 `value` 一律传 `SafeText(内容)`**，
读出来的 JSON 字符串一律先 `UnsafeText` 再展示/比较（尤其是 `statement`、`compile_log`、`msg`）。

---

## 3. 各屏积木要点

### 3.1 Screen1 —— 注册 / 登录
1. 「登录」按钮：
   ```text
   CID ← join("c", Clock1.SystemTime, random 1000 9999)
   写 cmd:<CID> = {"cid":"<CID>","op":"login","args":{"user":"<U>","pass":"<P>"},"status":"pending","ts":<now>}
   全局变量 WaitCID ← CID ；启动轮询
   ```
2. `Clock1.Timer`（登录轮询）：
   ```text
   读 reply:<WaitCID> → JsonTextDecode
   若 ok = true：token ← data.token，存 TinyDB，“打开 Screen_List”
   若 ok = false：Notifier 提示 data.msg
   ```
3. 「注册」：同流程，`op` 用 `register`，`args` 带 `nick`。

### 3.2 Screen_List —— 题目列表
`Screen.Initialize`：
```text
写 cmd:<CID> = {"op":"problem_list"}
轮询 reply:<CID> → data.problems（列表）→ 逐项 "P1001 A+B Problem" 塞进 ListView1
```
点击某项 → `打开 Screen_Problem 并传 pid`。

> 不想用命令总线时：`get idx:problems` 拿题号数组，再对每个题号 `get prob:<PID>`。
> 题目数量 >100 时必须走 `cmd:problem_list`（`search` 单次上限 100 条）。

### 3.3 Screen_Problem —— 题面 + 提交
1. `Screen.Initialize`：`get prob:<PID>` → 解析 → Label 显示 `title/statement/时限/内存`（样例可从 statement 里读）。
2. 「提交」按钮：
   ```text
   SID ← join(求余(Clock1.SystemTime, 1000000), 随机 3 位数补零)   // 9 位
   ① 写 code:<SID>  = SafeText(TextBox_Code.Text)          // 源码必须过安全文本层！
   ② 写 sub:<SID>   = {"sid":"<SID>","user":"<U>","pid":"<PID>","lang":"cpp",
                       "status":"pending","ts":<now>,"judge":"","verdict":"",
                       "score":0,"time_ms":0,"memory_kb":0,"cases_passed":0,
                       "case_count":0,"msg":"排队中"}
   ③ 写 q:<SID>     = {"sid":"<SID>","ts":<now>,"pid":"<PID>","lang":"cpp","user":"<U>"}
   全局变量 WaitSID ← SID ；Clock2.TimerEnabled ← true（1500ms）
   ```
   ⚠️ `sub:`/`q:` 这两个 JSON 里的值也要过 `SafeText`（否则以后想放带 `'` 的备注就废了）；
   字段都是 ASCII 时可直接拼字符串。
   **顺序不能变**：先代码 → 再提交记录 → 最后入队。
3. `Clock2.Timer`（结果轮询）：
   ```text
   读 sub:<WaitSID> → 解析 status
     pending/judging → Label_Status.Text ← "评测中…"
     done           → 读 res:<WaitSID> → 显示 verdict/score/耗时/内存
                      按钮表：每点 i / verdict / time_ms / msg
                      Clock2.TimerEnabled ← false
     failed         → 显示 msg
   ```

### 3.4 Screen_MySubs / Screen_Rank
```text
我的提交：写 cmd:<CID> = {"op":"mysubs","args":{"limit":20},"token":"<token>"}
         轮询 reply:<CID> → data.subs 列表
排行榜  ：get rank → 解析 order 列表（含 rank/user/score/ac/submit）
判题机  ：search tag=judge: count=100 type=both → 有心跳即在线的判题机
```

---

## 4. 语言标识（`lang`）与后端一致的取值

| lang | 语言 | 备注 |
|---|---|---|
| `cpp` | C++17 | 默认，推荐 |
| `c` | C11 | |
| `py` | Python 3 | |
| `java` / `pas` | Java / Pascal | 后端默认关闭，`config/oj_config.json` 里 `enabled:true` 后可用 |

---

## 5. 常见坑

| 现象 | 原因与对策 |
|---|---|
| `get` 返回 `{}` | 标签不存在（正常）；确认拼写与大小写 |
| `search` 只回 1 条 | 没传 `count` → 必须 `&count=100` |
| 列表顺序乱 | `search` 顺序不可依赖 → 用 `ts` 排序 |
| 提交一直"排队中" | 判题机没在跑：本机执行 `python backend\daemon.py` 或看 `judge:` 心跳 |
| 中文乱码 | 值一律 `Uri1.Encode`；后端已是 UTF-8 |
| 源码里有 `&` `+` `=` | 必须 `Uri1.Encode`，否则 form 解析会截断 |
| 提交后判成 CE 且提示"环境缺失" | 本机缺编译器，跑 `python tools\selfcheck.py` 看建议 |
| `Web.GotText` 里拿不到内容 | `responseContent` 是文本；用 `Web1.JsonTextDecode` 转字典再取键 |

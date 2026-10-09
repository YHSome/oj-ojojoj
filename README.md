# 前端（纯静态：HTML + CSS + JS，无框架、无构建、无依赖）

```
frontend/
├─ index.html            单页面（登录/题目/答题提交/我的提交/排行榜/关于）
└─ assets/
   ├─ style.css          深色主题样式
   ├─ crypto.js          RSA-OAEP(SHA-256) 分块非对称加密 + 签名验签（WebCrypto）
   ├─ tinywebdb.js       TinyWebDB REST 客户端（安全文本层 / 分片 / 503 退避）
   └─ app.js             业务逻辑（登录、看题、加密提交、轮询解密结果、榜单）
```

## 打开方式（**推荐第 2 种**）

1. 直接双击 `index.html`（`file://`）。
   ⚠️ 不推荐：浏览器把每个 `file://` 页面当作**独立不透明源**，在框架/预览里打开时会报
   `Unsafe attempt to load URL file:///... from frame with URL file:///...`，
   子资源与 `fetch` 都可能被拦，`WebCrypto` 的行为也不一致。
2. **用自带静态服务器（推荐）**：
   ```bash
   bash tools/oj.sh web            # → http://127.0.0.1:8000
   # 或 python tools/serve_frontend.py --port 8000
   ```
   `http://127.0.0.1` 属于安全上下文，`crypto.subtle` 与跨域 `fetch` 都正常，
   服务器还发了 `Cache-Control: no-store`，改完 JS 直接刷新就生效（必要时 Ctrl+F5）。

## 登录态与「我的代码」怎么保存

| 项 | 存放位置 | 说明 |
|---|---|---|
| 登录 token | 浏览器 `localStorage`（`oj_session`） | 刷新不丢；启动时用 `cmd: whoami` **自检**，失效才提示重新登录 |
| 客户端 RSA 私钥 | `sessionStorage`（`oj_client_priv`） | 同一标签页/会话内可解密历史结果；关掉标签页即失效 |
| **你提交过的源码** | `localStorage`（`oj_src_archive`） | 最多 60 份 / 300KB，超出丢最旧；判题机取码后会清掉云端密文，所以本地这份是「我的代码」的第一来源 |
| 源码（备份来源） | 云端 `res:<SID>` 密文里 | 判题机把源码一并封进**用你公钥加密**的结果里（`crypto.include_source`），换设备但同会话仍可看；明文提交不回传源码，避免泄露 |
| 源码（管理端） | 判题机本地 `data/work/<SID>/main.*` | 管理员用 `admin_cli inspect --sid X --code` 查看 |

> 隐私设计回顾：`code:<SID>` 的密文在判题机取码的瞬间就被删除，云端不会有明文代码。
> 所以「看不到自己的代码」不是 bug，而是取舍；现在用**本地存档 + 加密回传**两头补齐。


| 坑 | 现象 | 正确处理 |
|---|---|---|
| **数组会被自动解析** | 值形如 `["P1001","P1002"]` 时，云端返回的是**数组**而不是字符串；对它做 `JSON.parse` 会把数组强转成 `"P1001,P1002"` 而报错 → 题目列表空白 | `typeof 值 !== 'string'` 时直接用，不要再 parse |
| **必须先解析再反转义** | 题面/编译日志含换行，安全文本层编码成 `%0A`；若先反转义（`unsafe`）再 `JSON.parse`，JSON 字符串里出现裸换行 → 解析失败 → 题面空白 | 顺序固定为 `JSON.parse(云端原文)` → `unsafeObj(...)` |

（`assets/tinywebdb.js` 的 `getJson()` 已按这两条实现；后端 `store.read_chunked()` 同理。）

## 提交流程（页面上的每一步都在日志区可见）

| 步骤 | 前端动作 | 云端标签 |
|---|---|---|
| 1 | 读判题机公钥 | `get oj:pubkey` |
| 2 | 生成会话密钥对（结果只有自己能解） | — |
| 3 | `crypto.subtle` RSA-OAEP 分块加密源码（每块 ≤190 字节） | 写 `code:<SID>:0…k` 分片 |
| 4 | 写密文清单（含 `alg/sha256/to`） | 写 `code:<SID>` |
| 5 | 写提交记录（附自己的公钥，用于结果回传） | 写 `sub:<SID>` |
| 6 | 入队 | 写 `q:<SID>` |
| 7 | 轮询提交状态 | 读 `sub:<SID>` / `code:<SID>` |
| 8 | 后端取码后：云端代码变「判题中」、密文分片被清除 | `code:<SID>` = `{state:"judging"}` |
| 9 | 判完：结果用**你的公钥**加密回传 + 判题机签名 | 读 `res:<SID>` + `res:<SID>:i` |
| 10 | 用本机私钥解密 + 用 `oj:pubkey` 验签 | — |

## 判题结果里会看到什么（判题机只判题，不回答案）

| 判定 | 你会看到 |
|---|---|
| `AC` | 通过 + 每点用时/内存 |
| `WA` | **只有「答案错误」**（不回期望值/实际值，防止输出钓鱼） |
| `PE` | 输出格式错误 |
| `TLE` / `MLE` / `OLE` | 超时毫秒 / 内存占用 / 输出大小（这些不含标准答案） |
| `RE` | 退出码 + **你自己程序的报错输出**（异常堆栈、段错误），不含标准答案 |
| `CE` | 编译器原文报错（你自己的语法/类型错误） |
| `JE` | 判题机内部错误，可原样重测 |

逐点对比明细（`第 N 个 token 不同: 期望 … 实际 …`）只留在判题机本地
（`data/work/<SID>/__judge_detail.txt` 与 `logs/judge.log`），管理员复盘用；
需要调试题包时可由中控台把 `judge.public_case_detail` 临时打开。

## 安全说明（务必知悉）
* 源码在云端**只以密文存在**：RSA-OAEP(SHA-256, 2048) 分块加密，每块 ≤190 字节。
  纯非对称、无对称密钥，判题机取码后立即删除密文分片并把代码标签改成「判题中」。
* 结果是**用客户端公钥**加密回传的，只有那个浏览器会话的私钥能解开；同时附判题机签名，
  前端用 `oj:pubkey` 验签，防止伪造结果。
* 客户端私钥存放在 `sessionStorage`：**关闭标签页即失效**，刷新页面仍可解密（同一会话）。
  换浏览器/清空会话后再看历史提交，只能看到结果摘要（verdict/分数），看不到逐点详情。
* 这是"够用的工程化处置"，不是端到端加密的学术标准：没有前向保密、没有证书链，
  页面本身由静态服务器提供——**请只在你信任的网络里部署**，对外请上 HTTPS。

## 兼容性

| 环境 | 状态 |
|---|---|
| Chrome / Edge / Firefox 现代版本 | ✅ |
| `file://` 直接打开 | ⚠️ 能用但受限，建议用 `tools/oj.sh web`（http://127.0.0.1:8000） |
| 手机浏览器 | ✅（响应式布局） |
| IE / 老版本 Safari | ❌ 没有 WebCrypto |

> 页面加载时会检查 `crypto.subtle`，不可用会直接提示换浏览器。

## 登录态与「我的代码」保存在哪

| 项 | 位置 | 说明 |
|---|---|---|
| 登录 token | `localStorage.oj_session` | 刷新不丢；启动时用 `cmd: whoami` **自检**，只有失效才提示重新登录 |
| 客户端 RSA 私钥 | `sessionStorage.oj_client_priv` | 同一标签页会话内可解密历史结果，关掉标签页即失效 |
| **提交过的源码** | `localStorage.oj_src_archive` | 最多 60 份 / 300KB，超出丢最旧 —— 「我的提交」里的代码第一来源 |
| 源码（备份） | 云端 `res:<SID>` 密文内 | 判题机把源码一并封进**用你公钥加密**的结果（`crypto.include_source`）；明文提交不回传源码，避免泄露 |
| 源码（管理端） | 判题机 `data/work/<SID>/main.*` | `admin_cli inspect --sid X --code` |

> 「看不到自己的代码」原本不是 bug 而是隐私取舍：`code:<SID>` 的密文在判题机取码瞬间就被删除。
> 现在用**本地存档 + 加密回传**两头补齐，两种情况下都能看到。

## 自测（不开浏览器也能验证前端代码）

仓库里用 **Node 加载同一份 `crypto.js` + `tinywebdb.js`** 跑真实端到端：

```bash
node tools/e2e_frontend.js a-plus-b ac      # 期望 AC 100 分
node tools/e2e_frontend.js a-plus-b wa      # 期望 WA
node tools/e2e_frontend.js a-plus-b ce      # 期望 CE
```

它会真实注册账号、加密源码、写云端、等判题机判完、解密结果并验签。

# 来源与致谢

## 参考项目

* **[MiniJudge](https://github.com/Mkrari/MiniJudge)**（Mkrari）——Windows 本地轻量 OJ。
  本项目的**判题语义**大量对齐它：8 种判定（含 `JE`）、任务租约与有限重试、
  `tokens/exact/float` 比较器、题包规范（`problem.json` + `statement.md` + `tests/NN.in|.ans`）、
  题目版本固定（内容摘要 ≠ 提交时的版本就按旧版本判）、候选重判批次、备份恢复、
  「同一账号同一题只计一次通过」的练习榜思路。
  * MiniJudge 源码**未包含在本仓库中**（`third_party/` 已被 `.gitignore` 排除）。
    需要比对时自行 `git clone https://github.com/Mkrari/MiniJudge.git`。
  * MiniJudge 仓库未声明开源许可证；本仓库只参考其**设计思想与文件格式**，不复制其代码。

* **TinyWebDB / App Inventor**（MIT）——云端 KV 中转服务，本项目只使用其公开 REST 接口。

## 本项目自行实现的部分

* 云端 KV 之上的整套 OJ 协议：标签 Schema、命令总线（RPC）、安全文本层、
  单值分片、软删除容错、坏标签兜底、100 条 `search` 上限的队列/归档策略。
* **纯标准库 RSA**（`backend/crypto.py`）：RSA-OAEP(SHA-256) 分块加解密 +
  RSASSA-PKCS1-v1_5 签名，与浏览器 WebCrypto 逐字节互测通过。
* Windows 沙箱执行（Job Object 内存/进程数限制、执行期输出监控、超时熔断、峰值内存采样）。
* 纯静态前端（无框架/无构建）与判题机中控台。

## 未随仓库分发的第三方运行时

| 组件 | 用途 | 获取方式 |
|---|---|---|
| w64devkit（MinGW-w64 GCC） | C/C++ 判题编译 | <https://github.com/skeeto/w64devkit/releases>，解压到 `tools/w64devkit` |
| PortableGit | Git Bash（本机脚本用） | <https://github.com/git-for-windows/git/releases>，解压到 `tools/git-portable` |

两者都已在 `.gitignore` 中排除，请自行下载；它们的许可证随各自发行包提供。

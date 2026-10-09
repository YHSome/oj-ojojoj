# 发布到 GitHub 指南

> 本机现状：**github.com 直连不通**（只有 `ghfast.top` 这类**只读**镜像可用），
> 且本机没有任何 GitHub 凭据。所以仓库已经**准备就绪**，推送需要在能访问 GitHub 的环境里做一次，
> 或者把 `dist/oj-ojojoj.bundle`（单文件）拷过去推。

---

## 1. 已经帮你做完的事

| 项 | 状态 |
|---|---|
| 敏感信息清理 | 真实 `user`/`secret`/实例号/管理员口令已从**所有待入库文件**中移除（`git grep` 复核为 0 命中） |
| 密钥隔离 | 真实凭据改放 `config/oj_config.local.json` 与 `frontend/assets/config.js`，两者都已 `.gitignore` |
| 运行数据 | `data/work`（选手源码）、`data/state`（判题机**私钥**）、备份快照、日志全部排除 |
| 大文件 | `tools/w64devkit`(319M)、`tools/git-portable`(406M)、`tools/dist`(308M)、`third_party/` 全部排除 |
| 许可证 | `LICENSE`（MIT，请改成你的名字）、`CREDITS.md`（说明 MiniJudge 只是设计参考、未复制其代码） |
| 可移植性 | `config.py` 在 `paths.root` 不存在时自动回落到仓库目录，clone 到任何位置都能跑 |
| 提交历史 | 已按模块拆成多个提交（见 §3） |

## 2. 推送前请先做的两件小事

```bash
cd /d/OJ
# ① 换成你自己的名字/邮箱（会写进提交历史）
git config user.name  "你的名字"
git config user.email "你的邮箱@example.com"
git commit --amend --reset-author -m "chore: 初始化仓库骨架与发布配置"   # 可选：改写首个提交作者
# ② 如果刚才的 amend 改了历史，把后续提交也一起重写
git rebase --root --exec 'git commit --amend --no-edit --reset-author'  # 可选
```

## 3. 已生成的提交历史

```
chore:  初始化仓库骨架（.gitignore / LICENSE / CREDITS / 配置示例）
feat:   判题后端（云端 KV 协议层 + 沙箱执行 + 评测核心 + 任务租约）
feat:   纯静态前端与 RSA-OAEP 非对称加密提交链路
feat:   判题机中控台（一键开关 / 参数热重载 / 运维动作）
docs:   架构、实测约束、前后端契约与前端说明
test:   自检与回归脚本（含加密互通 / 不泄露答案 / 中控台 API）
```

## 4. 推送（任选一种）

### 方式 A：单文件 bundle（推荐，本机网络受限时最省事）

```bash
# 本机生成（已生成过就在 D:\OJ\dist\oj-ojojoj.bundle）
git bundle create D:/OJ/dist/oj-ojojoj.bundle --all

# 把 oj-ojojoj.bundle 拷到一台能上 GitHub 的机器，然后：
git clone oj-ojojoj.bundle oj-ojojoj && cd oj-ojojoj
git remote set-url origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin --all
git push origin --tags
```

### 方式 B：直接用 GitHub CLI（在有网机器上）

```bash
gh auth login
gh repo create oj-ojojoj --public --source=. --push
```

### 方式 C：手动建仓库后推送

```bash
# 在网页上新建空仓库（不要勾选 README/.gitignore），然后：
cd /d/OJ
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git branch -M main
git push -u origin main
# 需要凭据：用户名填 GitHub 用户名，密码填 Personal Access Token（不是登录密码）
#   生成：GitHub → Settings → Developer settings → Personal access tokens → Fine-grained，
#         权限只需 Contents: Read and write
```

### 如果本机哪天能直连 GitHub 了，也可以直接推

```bash
cd /d/OJ
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main        # 提示输入用户名 + PAT
```

## 5. 推送后的自查清单

```bash
git ls-files | wc -l                     # 应该只有几十个文件
git count-objects -vH                    # 仓库体积应该 < 1 MB
git grep -n "YOUR_SECRET\|BEGIN RSA\|judge_key" -- . ':!*example*'   # 只应命中示例文件
git status --porcelain                   # 应该是空的
```

**绝对不要**把下面这些提交上去（已在 `.gitignore`，但仍请人工确认）：

* `data/state/judge_key.json` —— 判题机私钥，泄露等于所有加密提交可被解密
* `config/oj_config.local.json` / `frontend/assets/config.js` —— 云端写权限
* `data/work/**` —— 选手源码
* `data/state/backup-*.json` —— 云端全量快照（含所有提交结果）

## 6. 换个域名/实例后要改什么

| 文件 | 改什么 |
|---|---|
| `config/oj_config.local.json` | `api.user` / `api.secret` / `api.browse` |
| `frontend/assets/config.js` | 同上（前端要直连云端） |
| `config/oj_config.json` | 一般不用动（只放占位符与默认值） |

改完重启判题机与前端即可；题目重新 `bash tools/oj.sh seed` 推到你的实例。

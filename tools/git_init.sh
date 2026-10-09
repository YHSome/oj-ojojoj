#!/usr/bin/env bash
# ==========================================================================
#  初始化/提交/打包 一体化脚本（幂等，可反复执行）
#    bash tools/git_init.sh init     仅初始化并打印将要提交的文件
#    bash tools/git_init.sh commit   按模块提交
#    bash tools/git_init.sh bundle   生成 dist/oj-ojojoj.bundle
# ==========================================================================
set -uo pipefail
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

AUTHOR_NAME="${OJ_GIT_NAME:-OJ-OJOJOJ}"
AUTHOR_MAIL="${OJ_GIT_EMAIL:-oj-ojojoj@users.noreply.github.com}"

ensure_identity() {
  git config user.name  >/dev/null 2>&1 || git config user.name  "$AUTHOR_NAME"
  git config user.email >/dev/null 2>&1 || git config user.email "$AUTHOR_MAIL"
}

do_init() {
  if [ ! -d .git ]; then
    git init -q -b main
    echo "已初始化 git 仓库（分支 main）"
  else
    echo "已是 git 仓库"
  fi
  ensure_identity
  git add -A
  echo
  echo "=== 将要提交的文件（$(git diff --cached --name-only | wc -l) 个） ==="
  git diff --cached --name-only
  echo
  echo "=== 体积 ==="
  git diff --cached --stat | tail -1
}

do_commit() {
  ensure_identity
  # 注意：分组提交时**不能**先 git add -A，否则第一个提交会把所有文件带走
  git reset -q
  commit_group() {
    local msg="$1"; shift
    git add -A -- "$@" 2>/dev/null
    if ! git diff --cached --quiet; then
      git commit -q -m "$msg"
      echo "  ✔ $msg  [$(git show --stat --oneline HEAD | tail -1 | sed 's/^ *//')]"
    fi
  }

  commit_group "chore: 初始化仓库骨架（.gitignore / LICENSE / CREDITS / 配置示例）" \
    .gitignore .gitattributes LICENSE CREDITS.md config

  commit_group "feat: 判题后端（云端 KV 协议层 + 沙箱执行 + 评测核心 + 任务租约）" \
    backend

  commit_group "feat: 纯静态前端与 RSA-OAEP 非对称加密提交链路" \
    frontend

  commit_group "feat: 判题机中控台（一键开关 / 参数热重载 / 运维动作）" \
    console tools/console.py

  commit_group "docs: 架构、实测约束、前后端契约与前端说明" \
    README.md docs

  commit_group "test: 自检与回归脚本（加密互通 / 不泄露答案 / 中控台 API）" \
    tools start_judge.cmd start_judge.sh judge_once.cmd

  commit_group "feat: 题库样例（A+B / 区间求和）" \
    data/problems

  git add -A
  if ! git diff --cached --quiet; then
    git commit -q -m "chore: 其余文件"
    echo "  ✔ chore: 其余文件"
  fi
  echo
  echo "=== 提交历史 ==="
  git log --oneline
  echo
  echo "=== 仓库概况 ==="
  echo "文件数: $(git ls-files | wc -l)"
  echo "提交数: $(git rev-list --count HEAD)"
}

do_bundle() {
  mkdir -p dist
  rm -f dist/oj-ojojoj.bundle
  git bundle create dist/oj-ojojoj.bundle --all >/dev/null
  echo "已生成 dist/oj-ojojoj.bundle（$(du -h dist/oj-ojojoj.bundle | cut -f1)）"
  echo "拷到能上 GitHub 的机器后："
  echo "  git clone oj-ojojoj.bundle oj-ojojoj && cd oj-ojojoj"
  echo "  git remote set-url origin https://github.com/<你>/<仓库>.git"
  echo "  git push -u origin --all"
}

case "${1:-init}" in
  init)   do_init ;;
  commit) do_commit ;;
  bundle) do_bundle ;;
  *) echo "用法: bash tools/git_init.sh [init|commit|bundle]"; exit 2 ;;
esac

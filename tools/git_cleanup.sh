#!/usr/bin/env bash
# 清掉不该入库的垃圾，然后重建 git 仓库
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

echo "=== 删除外部运行时/临时残留 ==="
rm -rf tools/git-tar dist ojcheck_* 2>/dev/null
rm -rf data/tmp/* 2>/dev/null
rm -rf tools/dist/*.exe tools/dist/*.zip tools/dist/*.bz2 2>/dev/null
find /d/OJ -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
echo "  done"

echo
echo "=== 重建 git 仓库 ==="
rm -rf .git
git init -q -b main
git config user.name  "${OJ_GIT_NAME:-OJ-OJOJOJ}"
git config user.email "${OJ_GIT_EMAIL:-oj-ojojoj@users.noreply.github.com}"

echo
echo "=== git 将跟踪的文件 ==="
git add -A 2>/dev/null
git diff --cached --name-only | head -80
echo "..."
echo "文件总数: $(git diff --cached --name-only | wc -l)"
echo "暂存体积: $(git diff --cached --stat | tail -1)"

echo
echo "=== 可疑项复核（应为空） ==="
git diff --cached --name-only | grep -Ei 'judge_key|oj_config\.local\.json|assets/config\.js$|data/work/|data/state/|\.log$|w64devkit|git-portable|git-tar|third_party' || echo "  ✔ 无"

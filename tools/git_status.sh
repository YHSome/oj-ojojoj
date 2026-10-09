#!/usr/bin/env bash
# 仓库最终状态一览
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

echo "=== 提交历史 ==="
git log --oneline

echo
echo "=== 工作区状态（空 = 干净） ==="
git status --porcelain

echo
echo "=== 概况 ==="
echo "  跟踪文件: $(git ls-files | wc -l)"
echo "  提交数  : $(git rev-list --count HEAD)"
echo "  仓库体积: $(git count-objects -vH | grep size-pack | cut -d' ' -f2-)"
echo "  文件总大小: $(git ls-files -z | xargs -0 du -ch 2>/dev/null | tail -1 | cut -f1)"
echo "  分支    : $(git branch --show-current)"

echo
echo "=== 发布的单文件 bundle ==="
ls -la dist/oj-ojojoj.bundle

echo
echo "=== 顶层结构 ==="
git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn | head -12

#!/usr/bin/env bash
# 检查脱敏脚本是否误伤了标识符（把 oj-ojojoj 里的 ojojoj 也替换了）
cd /d/OJ || exit 1

echo "=== 所有含 YOUR_USER / YOUR_SECRET 的位置 ==="
git grep -n -e "YOUR_USER" -e "YOUR_SECRET" -- . | sed 's/^/  /'

echo
echo "=== 疑似被误伤的标识符（schema / 项目名 / slug） ==="
git grep -n -e "oj-YOUR_USER" -e "OJOJOJ" -- . | head -20 | sed 's/^/  /'
